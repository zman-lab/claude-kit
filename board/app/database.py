"""DB 연결 설정 및 마이그레이션 관리."""

import logging
import os
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = os.getenv("DB_PATH", "/app/data/board.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)

logger = logging.getLogger(__name__)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    dbapi_conn.execute("PRAGMA busy_timeout=30000")


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -- 마이그레이션 레지스트리 --

def _ensure_migrations_table(conn):
    """마이그레이션 추적 테이블 생성 (없으면)."""
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ")"
    ))
    conn.commit()


def _is_migration_applied(conn, name: str) -> bool:
    result = conn.execute(text("SELECT 1 FROM _migrations WHERE name = :name"), {"name": name})
    return result.fetchone() is not None


def _mark_migration_applied(conn, name: str):
    conn.execute(text("INSERT INTO _migrations (name) VALUES (:name)"), {"name": name})
    conn.commit()


def _migrate_board_tags(conn):
    """Board 테이블에 allowed_tags, allowed_prefixes, default_tag 컬럼 추가."""
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("boards")}
    if "allowed_tags" not in columns:
        conn.execute(text("ALTER TABLE boards ADD COLUMN allowed_tags TEXT"))
    if "allowed_prefixes" not in columns:
        conn.execute(text("ALTER TABLE boards ADD COLUMN allowed_prefixes TEXT"))
    if "default_tag" not in columns:
        conn.execute(text("ALTER TABLE boards ADD COLUMN default_tag VARCHAR(50)"))
    conn.commit()

    # 팀 게시판: allowed_tags + default_tag
    conn.execute(text(
        "UPDATE boards SET allowed_tags = 'work,todo,issue,done,knowhow', default_tag = 'work' "
        "WHERE category = 'team' AND allowed_tags IS NULL"
    ))
    conn.commit()
    logger.info("Board 태그/프리픽스 컬럼 추가 완료")


def _migrate_add_attachments(conn):
    """Attachment 테이블 생성."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            filename VARCHAR(255) NOT NULL,
            stored_name VARCHAR(255) NOT NULL UNIQUE,
            file_size INTEGER NOT NULL,
            mime_type VARCHAR(100),
            uploader VARCHAR(100) NOT NULL,
            is_deleted BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attachments_post_id ON attachments(post_id)"))
    conn.commit()
    logger.info("attachments 테이블 생성 완료")


def _migrate_add_teams_table(conn):
    """teams 테이블 생성."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            slug VARCHAR(50) NOT NULL UNIQUE,
            icon VARCHAR(10) DEFAULT '📋',
            color VARCHAR(20) DEFAULT '#6366f1',
            color_dark VARCHAR(20),
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_teams_slug ON teams(slug)"))
    conn.commit()
    logger.info("teams 테이블 생성 완료")


_MIGRATIONS = [
    ("001_board_tags", _migrate_board_tags),
    ("002_add_attachments", _migrate_add_attachments),
    ("003_add_teams_table", _migrate_add_teams_table),
]


def _run_migrations():
    """등록된 마이그레이션을 순서대로 실행 (이미 적용된 것은 스킵)."""
    with engine.connect() as conn:
        _ensure_migrations_table(conn)
        for name, fn in _MIGRATIONS:
            if _is_migration_applied(conn, name):
                continue
            logger.info(f"마이그레이션 실행: {name}")
            fn(conn)
            _mark_migration_applied(conn, name)
            logger.info(f"마이그레이션 완료: {name}")


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_migrations()
