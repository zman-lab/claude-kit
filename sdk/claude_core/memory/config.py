"""
메모리 시스템 통합 설정.
Settings 의존성을 제거하고 모든 메모리 설정을 하나의 dataclass로 통합한다.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MemoryConfig:
    """메모리 시스템 통합 설정."""

    # Storage
    db_path: str = "memory.db"

    # Types
    base_types: list[str] = field(default_factory=lambda: [
        "profile", "knowledge", "failure", "tool", "decision"
    ])
    custom_types: list[str] = field(default_factory=list)

    # Search
    search_limit: int = 5
    rerank_threshold: int = 4
    char_limit: int = 6000

    # Half-lives (일 단위, None=감쇠없음)
    half_lives: dict[str, Optional[float]] = field(default_factory=lambda: {
        "profile": None,
        "knowledge": 90.0,
        "failure": 180.0,
        "tool": None,
        "decision": 365.0,
    })

    # Type priority weights
    type_priority: dict[str, float] = field(default_factory=lambda: {
        "failure": 1.5,
        "tool": 1.3,
        "knowledge": 1.0,
        "decision": 1.0,
        "profile": 1.0,
    })

    # Write Gate
    write_gate_enabled: bool = True
    force_save_triggers: list[str] = field(default_factory=lambda: [
        "기억해", "메모해", "저장해", "remember", "save this"
    ])
    skip_greetings: list[str] = field(default_factory=lambda: [
        "안녕", "ㅎㅇ", "hi", "hello", "ㄱㅅ", "감사", "고마워"
    ])
    min_message_length: int = 5
    stage2_prompt: Optional[str] = None    # None이면 기본 프롬프트 사용
    confidence_threshold: float = 0.7

    # Maintenance
    maintenance_hour: int = 4              # KST 기준
    decay_threshold: float = 0.1           # 이 이하면 soft delete

    # Vector (optional)
    vector_enabled: bool = False
    vector_model: str = "all-MiniLM-L6-v2"  # sentence-transformers 모델
    vector_dim: int = 384

    @property
    def all_types(self) -> list[str]:
        """기본 + 커스텀 타입 전체."""
        return self.base_types + self.custom_types

    def validate(self) -> None:
        """설정 유효성 검사. 커스텀 타입이 기본 타입과 겹치면 ValueError."""
        overlap = set(self.base_types) & set(self.custom_types)
        if overlap:
            raise ValueError(f"커스텀 타입이 기본 타입과 겹침: {overlap}")
