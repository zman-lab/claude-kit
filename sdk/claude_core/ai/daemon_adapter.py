"""DaemonProvider — ClaudeDaemon을 AIProvider 인터페이스로 래핑.

claude-core의 ClaudeDaemon.ask_stream()을 AIProvider 인터페이스에 맞춰서
DualAIProvider에 주입 가능하게 만드는 어댑터.

이벤트 타입:
  "text"    → 텍스트 청크
  "done"    → 완료 (full_text, duration)
  "error"   → 에러
  "keepalive", "tool_status" → 무시
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from .base import AIProvider
from .cost import make_usage_dict
from .errors import AIProviderError, DaemonNotRunningError

if TYPE_CHECKING:
    from claude_core.daemon.claude import ClaudeDaemon

logger = logging.getLogger(__name__)


class DaemonProvider(AIProvider):
    """ClaudeDaemon.ask_stream()을 AIProvider 인터페이스로 래핑.

    Args:
        daemon: ClaudeDaemon 인스턴스
        instance_id: DaemonManager에서 사용할 인스턴스 ID (기본: "default")
    """

    def __init__(self, daemon: ClaudeDaemon, instance_id: str = "default"):
        self._daemon = daemon
        self._instance_id = instance_id

    async def generate(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> tuple[str, dict]:
        """ask_stream() 전체 소비 후 (text, usage_dict) 반환."""
        full_text = ""
        usage = make_usage_dict(model="claude-daemon", provider="daemon")

        try:
            async for chunk_json in self._daemon.ask_stream(
                prompt=prompt,
                system_prompt=system or None,
            ):
                data = json.loads(chunk_json)
                msg_type = data.get("type", "")

                if msg_type == "text":
                    full_text += data.get("content", "")
                elif msg_type == "done":
                    full_text = data.get("full_text", full_text)
                    usage["duration"] = data.get("duration", 0.0)
                elif msg_type == "error":
                    error_msg = data.get("message", "daemon 오류")
                    raise AIProviderError(
                        f"DaemonProvider 오류: {error_msg}", provider="daemon"
                    )
        except ProcessLookupError:
            raise DaemonNotRunningError("Daemon 프로세스가 종료됨")
        except json.JSONDecodeError as e:
            logger.warning("Daemon 응답 JSON 파싱 실패: %s", e)

        return full_text, usage

    async def generate_stream(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> AsyncIterator[str | dict]:
        """ask_stream() 이벤트를 파싱하여 텍스트 청크 yield, 마지막에 usage yield."""
        usage = make_usage_dict(model="claude-daemon", provider="daemon")

        try:
            async for chunk_json in self._daemon.ask_stream(
                prompt=prompt,
                system_prompt=system or None,
            ):
                data = json.loads(chunk_json)
                msg_type = data.get("type", "")

                if msg_type == "text":
                    content = data.get("content", "")
                    if content:
                        yield content
                elif msg_type == "done":
                    usage["duration"] = data.get("duration", 0.0)
                    yield usage
                elif msg_type == "error":
                    error_msg = data.get("message", "daemon 오류")
                    raise AIProviderError(
                        f"DaemonProvider 오류: {error_msg}", provider="daemon"
                    )
                # keepalive, tool_status → 무시
        except ProcessLookupError:
            raise DaemonNotRunningError("Daemon 프로세스가 종료됨")

    async def close(self):
        """리소스 정리 — DaemonManager가 관리하므로 no-op."""
        pass
