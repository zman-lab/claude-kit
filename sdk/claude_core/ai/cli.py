"""CLIProvider — Claude CLI subprocess 프로바이더.

claude CLI를 --output-format json 으로 호출하여
실제 사용 모델, 토큰 수, 비용을 메타데이터에서 추출.

JSON 파싱 실패 시 plain text 폴백 지원.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import statistics
import time
from collections.abc import AsyncIterator

from .base import AIProvider
from .cost import DEFAULT_KRW_PER_USD, make_usage_dict
from .errors import AIProviderError, AITimeoutError, ProviderNotConfiguredError

logger = logging.getLogger(__name__)


class CLIProvider(AIProvider):
    """Claude CLI를 subprocess로 호출하는 AIProvider 구현체.

    --output-format json 으로 호출하여 실제 사용 모델, 토큰 수,
    비용을 메타데이터에서 추출.

    Args:
        claude_path: claude CLI 경로 (None이면 PATH에서 자동 탐색)
        timeout: CLI 프로세스 타임아웃 (초, 기본 900=15분)
        chunk_size: 시뮬레이션 스트리밍 청크 크기 (문자 수, 기본 50)
        krw_per_usd: 원/달러 환율 (기본 DEFAULT_KRW_PER_USD)
    """

    def __init__(
        self,
        claude_path: str | None = None,
        timeout: float = 900,
        chunk_size: int = 50,
        krw_per_usd: float = DEFAULT_KRW_PER_USD,
    ):
        if claude_path is not None:
            self.claude_path = claude_path
        else:
            self.claude_path = shutil.which("claude")
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.krw_per_usd = krw_per_usd
        # 인스턴스별 응답시간 통계
        self._response_times: list[float] = []

    async def generate(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> tuple[str, dict]:
        """Claude CLI로 텍스트 생성.

        --output-format json 으로 호출하여
        메타데이터(실제 모델, 토큰, 비용) 추출.
        JSON 파싱 실패 시 plain text 폴백.

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트 (빈 문자열이면 생략)
            model: 모델 ID (None이면 CLI 기본 모델)

        Returns:
            (response_text, usage_dict)

        Raises:
            ProviderNotConfiguredError: claude CLI 경로가 없을 때
            AITimeoutError: 프로세스 타임아웃
            AIProviderError: 프로세스 실패 (returncode != 0)
        """
        if not self.claude_path:
            raise ProviderNotConfiguredError(
                "cli", hint="claude CLI가 설치되어 있지 않습니다"
            )

        cmd = [self.claude_path, "--print", "--output-format", "json"]
        if model:
            cmd.extend(["--model", model])
        if system:
            cmd.extend(["--system-prompt", system])

        # CLAUDECODE 환경변수 제거 (중첩 세션 방지)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        started = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            raise AITimeoutError(self.timeout, provider="cli")

        elapsed = time.monotonic() - started

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                "Claude CLI 오류 (exit=%d, %.1fs): %s",
                proc.returncode,
                elapsed,
                error_msg,
            )
            raise AIProviderError(
                f"Claude CLI 오류 (exit={proc.returncode}): {error_msg}",
                provider="cli",
            )

        raw = stdout.decode("utf-8", errors="replace").strip()
        result, usage_dict = self._parse_json_response(
            raw, requested_model=model, krw_per_usd=self.krw_per_usd
        )
        self._record_stat(elapsed, len(result), usage_dict.get("model", "unknown"))
        return result, usage_dict

    @staticmethod
    def _parse_json_response(
        raw: str,
        requested_model: str | None = None,
        krw_per_usd: float = DEFAULT_KRW_PER_USD,
    ) -> tuple[str, dict]:
        """CLI JSON 응답에서 텍스트와 메타데이터 추출.

        JSON 파싱 실패 시 plain text 폴백.

        Args:
            raw: CLI stdout 원본
            requested_model: 요청 시 지정한 모델 (폴백용)
            krw_per_usd: 환율

        Returns:
            (result_text, usage_dict)
        """
        fallback_model = requested_model or "claude-cli"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("CLI JSON 파싱 실패, plain text 폴백")
            return raw, make_usage_dict(
                model=fallback_model,
                provider="cli",
                cost_usd=None,
                cost_krw=None,
            )

        result = data.get("result", "")
        usage = data.get("usage", {})
        model_usage = data.get("modelUsage", {})

        # modelUsage의 첫 번째 키가 실제 사용 모델
        actual_model = next(iter(model_usage), fallback_model)
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cost_usd = data.get("total_cost_usd")
        cost_krw = round(cost_usd * krw_per_usd, 2) if cost_usd else None

        return result, make_usage_dict(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=actual_model,
            provider="cli",
            cost_usd=cost_usd,
            cost_krw=cost_krw,
        )

    def _record_stat(
        self, elapsed: float, chars: int, model: str = "unknown"
    ) -> None:
        """응답시간 기록 + 통계 로그."""
        self._response_times.append(elapsed)
        times = self._response_times

        n = len(times)
        mean = sum(times) / n
        med = statistics.median(times)
        mn = min(times)
        mx = max(times)

        logger.info(
            "Claude CLI 응답 완료 | 모델: %s | 이번: %.1fs %d자 "
            "| 통계(n=%d) 평균:%.1fs 중앙:%.1fs 최소:%.1fs 최대:%.1fs",
            model,
            elapsed,
            chars,
            n,
            mean,
            med,
            mn,
            mx,
        )

    async def generate_stream(
        self, prompt: str, system: str = "", model: str | None = None
    ) -> AsyncIterator[str | dict]:
        """CLI 시뮬레이션 스트리밍 — 전체 응답을 chunk_size 단위로 분할 yield.

        실제 CLI는 스트리밍을 지원하지 않으므로
        generate()로 전체 응답을 받은 뒤 청크 단위로 나눠 yield.
        마지막에 usage_dict(dict)를 yield.

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트
            model: 모델 ID

        Yields:
            str: 텍스트 청크
            dict: 마지막에 usage_dict
        """
        full_response, usage_dict = await self.generate(prompt, system, model)
        for i in range(0, len(full_response), self.chunk_size):
            yield full_response[i : i + self.chunk_size]
            await asyncio.sleep(0.01)
        yield usage_dict

    async def close(self) -> None:
        """리소스 정리 — CLI는 프로세스 기반이므로 no-op."""
        pass
