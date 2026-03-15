"""SQLAlchemy ORM 모델 정의."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Team(Base):
    """팀 정보. 팀 생성 시 자동으로 업무게시판이 함께 생성된다."""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)           # 표시명: "alpha팀"
    slug = Column(String(50), unique=True, nullable=False, index=True)  # URL용: "alpha"
    icon = Column(String(10), default="📋")
    color = Column(String(20), default="#6366f1")         # 라이트모드 색상
    color_dark = Column(String(20), nullable=True)        # 다크모드 색상 (없으면 자동계산)
    description = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class Board(Base):
    __tablename__ = "boards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    category = Column(String(20), nullable=False)  # "team" | "global"
    team = Column(String(50), nullable=True)
    description = Column(Text, default="")
    icon = Column(String(10), default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    allowed_tags = Column(Text, nullable=True)       # comma-separated: "api,mcp,agent-sdk"
    allowed_prefixes = Column(Text, nullable=True)    # comma-separated: "[가이드],[삽질후기]"
    default_tag = Column(String(50), nullable=True)   # 미선택 시 기본 태그
    created_at = Column(DateTime, default=_utcnow)

    posts = relationship("Post", back_populates="board")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    prefix = Column(String(50), nullable=True)
    tag = Column(String(50), nullable=True)
    is_pinned = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    board = relationship("Board", back_populates="posts")
    replies = relationship(
        "Post",
        backref=backref("parent", remote_side="Post.id"),
        foreign_keys=[parent_id],
        lazy="select",
    )
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="post", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    stored_name = Column(String(255), nullable=False, unique=True)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=True)
    uploader = Column(String(100), nullable=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    post = relationship("Post", back_populates="attachments")


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (
        UniqueConstraint("post_id", "author", name="uq_like_post_author"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    author = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    post = relationship("Post", back_populates="likes")


class AccessPassword(Base):
    __tablename__ = "access_passwords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    password_hash = Column(String(64), nullable=False, index=True)  # SHA256 hex
    label = Column(String(100), nullable=False)  # "홍길동용", "테스트용"
    password_type = Column(String(10), nullable=False, default="user")  # "admin" or "user"
    expires_at = Column(DateTime, nullable=True)  # NULL = 무기한
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    bound_visitor_id = Column(String(50), nullable=True)  # 기기 바인딩
    password_plain = Column(String(100), nullable=True)  # 평문 (관리자 확인용)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=True)
    cli_session_hash = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_resumable = Column(Boolean, default=False)
    skill_command = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user", "assistant"
    content = Column(Text, nullable=False)
    is_complete = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("ChatSession", back_populates="messages")


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (
        UniqueConstraint("account", "date", "project", "model_name", name="uq_token_usage"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account = Column(String(50), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    project = Column(String(200), nullable=False)
    team = Column(String(50), nullable=False, index=True)
    model_name = Column(String(100), nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cache_creation_tokens = Column(Integer, default=0)
    cache_read_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    collected_at = Column(DateTime, default=_utcnow)
