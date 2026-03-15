"""AI 프로바이더 추상 인터페이스.

모든 AI 프로바이더(SDK, CLI, Daemon, OpenAI 호환 등)가
이 인터페이스를 구현하면 DualAIProvider로 통합 라우팅 가능.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class AIProvider(ABC):
    """AI 서비스 추상 인터페이스 (프로바이더 패턴).

    모든 구현체는 동일한 시그니처를 따르며,
    usage_dict 반환 형식도 통일.

    usage_dict keys:
        input_tokens, output_tokens, total_tokens,
        model, provider, cost_usd, cost_krw
    """

    @abstractmethod
    async def generate(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> tuple[str, dict]:
        """텍스트 생성 (비스트리밍).

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트 (빈 문자열이면 프로바이더 기본값)
            model: 모델 ID (None이면 프로바이더 기본 모델)

        Returns:
            (response_text, usage_dict)
        """
        ...

    @abstractmethod
    async def generate_stream(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> AsyncIterator[str | dict]:
        """스트리밍 텍스트 생성.

        텍스트 청크(str)를 yield하고, 마지막에 usage_dict(dict)를 yield.

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트
            model: 모델 ID

        Yields:
            str: 텍스트 청크
            dict: 마지막에 usage_dict
        """
        ...

    @abstractmethod
    async def close(self):
        """리소스 정리"""
        ...
