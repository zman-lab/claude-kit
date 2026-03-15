"""
SDK 내부 공용 모델.
ClaudeBot의 ClaudeResponse를 SDK 내부로 흡수하여 외부 의존성을 제거한다.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClaudeResponse:
    """Claude CLI 응답 모델."""
    text: str
    session_id: Optional[str] = None
    is_error: bool = False
    duration: float = 0.0
