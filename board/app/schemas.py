"""Pydantic 스키마 정의."""

import re

from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# -- Team --

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    icon: str = "📋"
    color: str = "#6366f1"
    color_dark: str | None = None
    description: str = ""
    sort_order: int = 0

    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v):
        if not v:
            raise ValueError('슬러그는 필수입니다')
        if not re.match(r'^[a-z0-9][a-z0-9_-]*$', v):
            raise ValueError('슬러그는 영어 소문자, 숫자, -, _ 만 사용 가능합니다')
        if len(v) > 30:
            raise ValueError('슬러그는 30자 이하여야 합니다')
        return v


class TeamUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    color: str | None = None
    color_dark: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class TeamOut(BaseModel):
    id: int
    name: str
    slug: str
    icon: str
    color: str
    color_dark: str | None
    description: str
    sort_order: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# -- Board --

class BoardCreate(BaseModel):
    name: str
    slug: str
    category: str = "global"
    team: str | None = None
    description: str = ""
    icon: str = ""
    sort_order: int = 0


class BoardOut(BaseModel):
    id: int
    name: str
    slug: str
    category: str
    team: str | None
    description: str
    icon: str
    sort_order: int
    is_active: bool
    created_at: datetime
    post_count: int = 0

    class Config:
        from_attributes = True


# -- Post --

class PostCreate(BaseModel):
    board_slug: str
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    author: str
    prefix: str | None = None
    tag: str | None = None
    is_pinned: bool = False


class PostUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    prefix: str | None = None
    tag: str | None = None


class ReplyCreate(BaseModel):
    content: str
    author: str


class ReplyUpdate(BaseModel):
    content: str


class LikeCreate(BaseModel):
    author: str = "anonymous"


class PostOut(BaseModel):
    id: int
    board_id: int
    parent_id: int | None
    title: str | None
    content: str
    author: str
    prefix: str | None
    tag: str | None
    is_pinned: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    reply_count: int = 0
    like_count: int = 0
    liked_by: list[str] = []
    board_slug: str = ""
    board_name: str = ""

    class Config:
        from_attributes = True


# -- Auth / Password --

class VerifyRequest(BaseModel):
    password: str
    visitor_id: str | None = None

class VerifyResponse(BaseModel):
    valid: bool
    password_type: str | None = None
    label: str | None = None
    expires_at: str | None = None  # ISO8601
    expired: bool = False
    bound_to_other: bool = False

class PasswordCreate(BaseModel):
    password: str = Field(..., min_length=4)
    label: str = Field(..., min_length=1)
    password_type: str = "user"  # "admin" or "user"
    expires_hours: float | None = None  # None = 무기한

class PasswordAction(BaseModel):
    action: str  # "extend", "shorten", "expire_now", "set", "unbind"
    minutes: int | None = None

class PasswordOut(BaseModel):
    id: int
    label: str
    password_type: str
    expires_at: str | None
    expired: bool
    is_active: bool
    created_at: str
    bound_visitor_id: str | None
    password_plain: str | None


# -- Attachment --

class AttachmentOut(BaseModel):
    id: int
    post_id: int
    filename: str
    stored_name: str
    file_size: int
    mime_type: str | None
    uploader: str
    is_deleted: bool
    created_at: datetime

    class Config:
        from_attributes = True


# -- Setup --

class SetupInit(BaseModel):
    """초기 설정 요청 (admin 비밀번호 + 첫 팀 생성)."""
    admin_password: str = Field(..., min_length=4)
    admin_label: str = "초기 관리자"
    team_name: str | None = None       # 첫 팀 이름 (선택)
    team_slug: str | None = None       # 첫 팀 slug (선택)
    team_icon: str = "📋"
    team_color: str = "#6366f1"

    @field_validator('team_slug')
    @classmethod
    def validate_team_slug(cls, v):
        if not v:
            return v  # None 허용 (선택 필드)
        if not re.match(r'^[a-z0-9][a-z0-9_-]*$', v):
            raise ValueError('슬러그는 영어 소문자, 숫자, -, _ 만 사용 가능합니다')
        return v
