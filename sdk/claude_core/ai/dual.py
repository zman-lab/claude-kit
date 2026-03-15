"""DualAIProvider — 멀티 프로바이더 라우팅 레이어.

model prefix로 프로바이더를 선택:
  "sdk/claude-sonnet-..."   → SDK 프로바이더
  "cli/claude-sonnet-..."   → CLI 프로바이더
  "daemon/claude-sonnet-..." → Daemon 프로바이더
  "internal/gpt-oss-120b"   → 사내 AI (OpenAI 호환)
  "claude-sonnet-..."       → 기본 프로바이더 (default_prefix)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from .base import AIProvider
from .errors import ProviderNotConfiguredError

logger = logging.getLogger(__name__)


class DualAIProvider(AIProvider):
    """CLI + SDK + Daemon + Internal 동시 보유. model prefix로 라우팅.

    Args:
        cli: CLI 프로바이더 (필수)
        sdk: SDK 프로바이더 (필수, cli와 동일 인스턴스 가능)
        default_prefix: prefix 미지정 시 기본 프로바이더
            "sdk" | "cli" | "daemon"
        internal: 사내 AI 프로바이더 (선택)
        daemon: Daemon 프로바이더 (선택)
    """

    # 지원하는 prefix 목록
    PREFIXES = ("sdk/", "cli/", "daemon/", "internal/")

    def __init__(
        self,
        cli: AIProvider,
        sdk: AIProvider,
        default_prefix: str = "sdk",
        internal: AIProvider | None = None,
        daemon: AIProvider | None = None,
    ):
        self.cli = cli
        self.sdk = sdk
        self.default_prefix = default_prefix
        self.internal = internal
        self.daemon = daemon

    def _route(self, model: str | None) -> tuple[AIProvider, str | None]:
        """model string에서 provider prefix 분리 → (provider, pure_model)."""
        if not model:
            if self.default_prefix == "daemon" and self.daemon is not None:
                return self.daemon, None
            provider = self.sdk if self.default_prefix == "sdk" else self.cli
            return provider, None

        if model.startswith("sdk/"):
            return self.sdk, model[4:]
        if model.startswith("cli/"):
            return self.cli, model[4:]
        if model.startswith("daemon/"):
            if self.daemon is None:
                raise ProviderNotConfiguredError(
                    "daemon", hint="DAEMON_ENABLED=True로 설정하세요"
                )
            return self.daemon, model[7:]
        if model.startswith("internal/"):
            if self.internal is None:
                raise ProviderNotConfiguredError(
                    "internal", hint="INTERNAL_AI_URL을 설정하세요"
                )
            return self.internal, model[9:]

        # prefix 없으면 기본 프로바이더
        if self.default_prefix == "daemon" and self.daemon is not None:
            return self.daemon, model
        provider = self.sdk if self.default_prefix == "sdk" else self.cli
        return provider, model

    async def generate(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> tuple[str, dict]:
        provider, pure_model = self._route(model)
        return await provider.generate(prompt, system=system, model=pure_model)

    async def generate_stream(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> AsyncIterator[str | dict]:
        provider, pure_model = self._route(model)
        async for chunk in provider.generate_stream(
            prompt, system=system, model=pure_model
        ):
            yield chunk

    async def close(self):
        await self.cli.close()
        if self.sdk is not self.cli:
            await self.sdk.close()
        if self.internal is not None:
            await self.internal.close()
        if self.daemon is not None:
            await self.daemon.close()
