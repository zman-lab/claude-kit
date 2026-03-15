"""
메모리 시스템 도메인 모델.
SQLite 기반 메모리 저장소의 데이터 구조를 정의한다.

의존성 분리 (원본 대비 변경사항):
    - MemoryType: 기본 5타입은 enum으로 유지, 커스텀 타입은 문자열로 처리
    - MemoryItem.type: str로 변경 (enum 강제 해제)
    - MemorySaveRequest.type: str로 변경
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """기본 메모리 타입 (5종)."""
    PROFILE = "profile"      # 팀/시스템 영구 사실
    KNOWLEDGE = "knowledge"  # 기술 지식
    FAILURE = "failure"      # 실패 패턴
    TOOL = "tool"            # 봇이 만든 도구
    DECISION = "decision"    # 의사결정 근거

    @classmethod
    def from_str(cls, value: str) -> "MemoryType | str":
        """기본 타입이면 enum, 커스텀이면 문자열 그대로 반환."""
        try:
            return cls(value)
        except ValueError:
            return value


class MemoryItem(BaseModel):
    """메모리 저장 항목."""
    id: Optional[int] = None
    type: str                             # MemoryType enum값 또는 커스텀 타입 문자열
    key: str                              # 검색/식별용 키
    content: str                          # 핵심 내용
    metadata: dict = Field(default_factory=dict)       # JSON: 타입별 추가 필드
    tags: list[str] = Field(default_factory=list)      # 태그/키워드
    author: str = ""                      # 기록한 user_id
    source_conversation: Optional[str] = None          # 원본 대화 발췌 (최대 500자)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    accessed_at: Optional[datetime] = None
    access_count: int = 0
    is_active: bool = True
    version: int = 1
    superseded_by: Optional[int] = None               # 이전 버전 -> 최신 포인터

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


class MemorySaveRequest(BaseModel):
    """메모리 저장 요청."""
    type: str                             # MemoryType enum값 또는 커스텀 타입 문자열
    key: str
    content: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0               # Write Gate 신뢰도
    metadata: dict = Field(default_factory=dict)
    author: str = ""
    source_conversation: Optional[str] = None


class MemorySearchResult(BaseModel):
    """메모리 검색 결과."""
    item: MemoryItem
    score: float                          # FTS5 점수 * 감쇠 인자
    decay_factor: float = 1.0             # 시간 감쇠 인자 (0.0 ~ 1.0)


class WriteGateResult(BaseModel):
    """Write Gate 분류 결과."""
    should_save: bool
    memories: list[MemorySaveRequest] = Field(default_factory=list)
