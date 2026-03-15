"""AI 모델 비용 계산 유틸리티.

모델별 토큰 단가 관리 + 누적 비용 추적 + 환율 변환.
프로젝트별로 가격표를 확장하거나 환율을 변경할 수 있음.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


# ── 모델 가격표 (USD per 1M tokens) ──

DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x (2025~)
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Claude 3.5
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.0},
}

DEFAULT_FALLBACK_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0}
DEFAULT_KRW_PER_USD: float = 1450.0


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    fallback: dict[str, float] | None = None,
    krw_per_usd: float = DEFAULT_KRW_PER_USD,
) -> tuple[float, float]:
    """토큰 기반 비용 계산.

    Args:
        model: 모델 ID
        input_tokens: 입력 토큰 수
        output_tokens: 출력 토큰 수
        pricing: 커스텀 가격표 (None이면 기본값)
        fallback: 미지정 모델 시 기본 단가
        krw_per_usd: 환율

    Returns:
        (cost_usd, cost_krw) — 소수점 반올림 적용
    """
    price_table = pricing or DEFAULT_MODEL_PRICING
    fb = fallback or DEFAULT_FALLBACK_PRICING
    model_price = price_table.get(model, fb)
    cost_usd = (
        input_tokens * model_price["input"] + output_tokens * model_price["output"]
    ) / 1_000_000
    return round(cost_usd, 6), round(cost_usd * krw_per_usd, 2)


def make_usage_dict(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "",
    provider: str = "",
    cost_usd: float | None = None,
    cost_krw: float | None = None,
    **extra: object,
) -> dict:
    """통일된 usage_dict 생성 헬퍼.

    모든 AIProvider 구현체가 이 함수로 usage_dict를 만들면
    키 누락/불일치 없이 일관된 구조 보장.
    """
    d: dict = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model": model,
        "provider": provider,
        "cost_usd": cost_usd,
        "cost_krw": cost_krw,
    }
    d.update(extra)
    return d


# ── 누적 비용 추적기 ──


@dataclass
class CostTracker:
    """세션/서비스 단위 비용 누적 추적.

    thread-safe (Lock 사용).

    Usage:
        tracker = CostTracker()
        tracker.record(usage_dict)
        print(tracker.summary())
    """

    total_usd: float = 0.0
    total_krw: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    request_count: int = 0
    by_model: dict[str, dict[str, float | int]] = field(default_factory=dict)
    by_provider: dict[str, dict[str, float | int]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record(self, usage: dict) -> None:
        """usage_dict를 누적 기록."""
        with self._lock:
            cost_usd = usage.get("cost_usd") or 0.0
            cost_krw = usage.get("cost_krw") or 0.0
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            model = usage.get("model", "unknown")
            provider = usage.get("provider", "unknown")

            self.total_usd += cost_usd
            self.total_krw += cost_krw
            self.total_input_tokens += in_tok
            self.total_output_tokens += out_tok
            self.request_count += 1

            # 모델별
            if model not in self.by_model:
                self.by_model[model] = {
                    "usd": 0.0, "krw": 0.0, "input": 0, "output": 0, "count": 0
                }
            m = self.by_model[model]
            m["usd"] += cost_usd  # type: ignore[operator]
            m["krw"] += cost_krw  # type: ignore[operator]
            m["input"] += in_tok  # type: ignore[operator]
            m["output"] += out_tok  # type: ignore[operator]
            m["count"] += 1  # type: ignore[operator]

            # 프로바이더별
            if provider not in self.by_provider:
                self.by_provider[provider] = {"usd": 0.0, "krw": 0.0, "count": 0}
            p = self.by_provider[provider]
            p["usd"] += cost_usd  # type: ignore[operator]
            p["krw"] += cost_krw  # type: ignore[operator]
            p["count"] += 1  # type: ignore[operator]

    def summary(self) -> dict:
        """현재 누적 요약 반환."""
        with self._lock:
            return {
                "total_usd": round(self.total_usd, 6),
                "total_krw": round(self.total_krw, 2),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "request_count": self.request_count,
                "by_model": dict(self.by_model),
                "by_provider": dict(self.by_provider),
            }

    def reset(self) -> dict:
        """누적 초기화 (초기화 전 요약 반환)."""
        with self._lock:
            s = self.summary()
            self.total_usd = 0.0
            self.total_krw = 0.0
            self.total_input_tokens = 0
            self.total_output_tokens = 0
            self.request_count = 0
            self.by_model.clear()
            self.by_provider.clear()
            return s
