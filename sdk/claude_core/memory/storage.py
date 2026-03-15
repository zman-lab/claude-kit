"""
SQLite 기반 메모리 저장소.
asyncio.Lock으로 단일 writer 보장, WAL 모드로 읽기/쓰기 동시성 지원.

의존성 분리 (원본 대비 변경사항):
    - CHECK 제약조건 제거 → Python 레벨 검증
    - 생성자: db_path 대신 MemoryConfig 받음
    - save(): MemoryType enum 대신 문자열 비교
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from .config import MemoryConfig
from .models import MemoryItem, MemorySaveRequest

logger = logging.getLogger(__name__)

# DDL: 스키마 전체 (CHECK 제약조건 제거됨)
_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    tags TEXT DEFAULT '[]',
    author TEXT DEFAULT '',
    source_conversation TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    accessed_at TEXT DEFAULT (datetime('now')),
    access_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    version INTEGER DEFAULT 1,
    superseded_by INTEGER REFERENCES memories(id),
    UNIQUE(type, key, version)
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key, content, tags,
    content=memories,
    content_rowid=id,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, content, tags)
    VALUES (new.id, new.key, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, tags)
    VALUES ('delete', old.id, old.key, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, tags)
    VALUES ('delete', old.id, old.key, old.content, old.tags);
    INSERT INTO memories_fts(rowid, key, content, tags)
    VALUES (new.id, new.key, new.content, new.tags);
END;

CREATE TABLE IF NOT EXISTS failure_relations (
    failure_id INTEGER REFERENCES memories(id),
    related_failure_id INTEGER REFERENCES memories(id),
    relation_type TEXT DEFAULT 'same_root_cause',
    PRIMARY KEY (failure_id, related_failure_id)
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_type_key ON memories(type, key);
CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(is_active);
CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(accessed_at);

-- Stage2 Write Gate 큐 영속화 (재시작 후 복원용)
CREATE TABLE IF NOT EXISTS pending_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class MemoryStorage:
    """SQLite 메모리 저장소. asyncio.Lock으로 단일 writer 보장."""

    def __init__(self, config: MemoryConfig):
        self._db_path = config.db_path
        self._config = config
        self._write_lock = asyncio.Lock()
        self._conn: Optional[aiosqlite.Connection] = None
        self._conn_lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        """연결을 lazy하게 생성하고 재사용한다. 연결이 닫혔으면 재생성."""
        async with self._conn_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                self._conn.row_factory = aiosqlite.Row
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA busy_timeout=5000")
                await self._conn.commit()
                logger.info("SQLite 연결 생성: %s", self._db_path)
            return self._conn

    async def close(self) -> None:
        """연결을 명시적으로 닫는다. 애플리케이션 종료 시 호출."""
        async with self._conn_lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
                logger.info("SQLite 연결 닫힘: %s", self._db_path)

    async def initialize(self) -> None:
        """DB 파일 생성 + 스키마 초기화."""
        # DB 디렉토리 생성
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        async with self._write_lock:
            conn = await self._get_conn()
            # executescript는 BEGIN...END 트리거 정의를 올바르게 처리
            # PRAGMA 구문을 제외하고 DDL만 실행 (executescript는 자체 커밋 포함)
            ddl_only = "\n".join(
                line for line in _SCHEMA_SQL.splitlines()
                if not line.strip().upper().startswith("PRAGMA")
            )
            await conn.executescript(ddl_only)
        logger.info("메모리 DB 초기화 완료: %s", self._db_path)

    def _validate_type(self, type_str: str) -> None:
        """타입 유효성 검사. Python 레벨에서 CHECK 제약조건 대체."""
        if type_str not in self._config.all_types:
            raise ValueError(
                f"알 수 없는 메모리 타입: '{type_str}' "
                f"(허용된 타입: {self._config.all_types})"
            )

    def _row_to_item(self, row) -> MemoryItem:
        """DB 행 -> MemoryItem 변환."""
        def parse_dt(val: Optional[str]) -> Optional[datetime]:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except Exception:
                return None

        return MemoryItem(
            id=row["id"],
            type=row["type"],  # 문자열 그대로 (enum 변환 없음)
            key=row["key"],
            content=row["content"],
            metadata=json.loads(row["metadata"] or "{}"),
            tags=json.loads(row["tags"] or "[]"),
            author=row["author"] or "",
            source_conversation=row["source_conversation"],
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            accessed_at=parse_dt(row["accessed_at"]),
            access_count=row["access_count"] or 0,
            is_active=bool(row["is_active"]),
            version=row["version"] or 1,
            superseded_by=row["superseded_by"],
        )

    async def save(self, req: MemorySaveRequest, author: str = "") -> MemoryItem:
        """메모리 저장. profile/tool은 version 증가 + superseded_by 갱신."""
        # Python 레벨 타입 검증
        type_str = req.type if isinstance(req.type, str) else req.type.value
        self._validate_type(type_str)

        effective_author = author or req.author
        tags_json = json.dumps(req.tags, ensure_ascii=False)
        metadata_json = json.dumps(req.metadata, ensure_ascii=False)
        source = req.source_conversation
        if source and len(source) > 500:
            source = source[:500]

        async with self._write_lock:
            conn = await self._get_conn()

            # version 기반 upsert 대상: profile, tool
            if type_str in ("profile", "tool"):
                cursor = await conn.execute(
                    "SELECT id, version FROM memories "
                    "WHERE type=? AND key=? AND is_active=1 "
                    "ORDER BY version DESC LIMIT 1",
                    (type_str, req.key),
                )
                existing = await cursor.fetchone()
                new_version = (existing["version"] + 1) if existing else 1

                cursor = await conn.execute(
                    """INSERT INTO memories
                       (type, key, content, metadata, tags, author, source_conversation, version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (type_str, req.key, req.content, metadata_json,
                     tags_json, effective_author, source, new_version),
                )
                new_id = cursor.lastrowid

                if existing:
                    await conn.execute(
                        "UPDATE memories SET superseded_by=? WHERE id=?",
                        (new_id, existing["id"]),
                    )
            else:
                cursor = await conn.execute(
                    """INSERT INTO memories
                       (type, key, content, metadata, tags, author, source_conversation)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (type_str, req.key, req.content, metadata_json,
                     tags_json, effective_author, source),
                )
                new_id = cursor.lastrowid

            await conn.commit()

            cursor = await conn.execute(
                "SELECT * FROM memories WHERE id=?", (new_id,)
            )
            row = await cursor.fetchone()
            return self._row_to_item(row)

    async def get(self, id: int) -> Optional[MemoryItem]:
        """ID로 단일 메모리 조회."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM memories WHERE id=?", (id,))
        row = await cursor.fetchone()
        return self._row_to_item(row) if row else None

    async def soft_delete(self, id: int) -> None:
        """소프트 삭제 (is_active=0)."""
        async with self._write_lock:
            conn = await self._get_conn()
            await conn.execute(
                "UPDATE memories SET is_active=0, updated_at=datetime('now') WHERE id=?",
                (id,),
            )
            await conn.commit()

    async def update_accessed(self, id: int) -> None:
        """accessed_at, access_count 갱신."""
        async with self._write_lock:
            conn = await self._get_conn()
            await conn.execute(
                """UPDATE memories
                   SET accessed_at=datetime('now'), access_count=access_count+1
                   WHERE id=?""",
                (id,),
            )
            await conn.commit()

    async def get_by_type_key(
        self, type: str, key: str, active_only: bool = True
    ) -> list[MemoryItem]:
        """타입 + 키로 메모리 조회."""
        conn = await self._get_conn()
        query = "SELECT * FROM memories WHERE type=? AND key=?"
        params = [type, key]
        if active_only:
            query += " AND is_active=1"
        query += " ORDER BY version DESC"
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_item(r) for r in rows]

    async def add_pending_analysis(self, conversation: str, user_id: str) -> int:
        """Stage2 분석 대기 항목을 DB에 저장. 재시작 후 복원에 사용."""
        async with self._write_lock:
            conn = await self._get_conn()
            cursor = await conn.execute(
                "INSERT INTO pending_analyses (conversation, user_id) VALUES (?, ?)",
                (conversation, user_id),
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_pending_analyses(self) -> list[dict]:
        """저장된 미처리 Stage2 분석 항목 전체 반환."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, conversation, user_id FROM pending_analyses ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [{"id": r["id"], "conversation": r["conversation"], "user_id": r["user_id"]} for r in rows]

    async def delete_pending_analysis(self, id: int) -> None:
        """처리 완료된 Stage2 항목을 DB에서 삭제."""
        async with self._write_lock:
            conn = await self._get_conn()
            await conn.execute("DELETE FROM pending_analyses WHERE id=?", (id,))
            await conn.commit()

    async def get_stats(self) -> dict:
        """타입별 카운트 및 DB 크기 반환."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT type, COUNT(*) as cnt FROM memories WHERE is_active=1 GROUP BY type"
        )
        rows = await cursor.fetchall()
        counts = {row[0]: row[1] for row in rows}

        db_size = Path(self._db_path).stat().st_size if Path(self._db_path).exists() else 0
        return {"counts": counts, "db_size_bytes": db_size}
