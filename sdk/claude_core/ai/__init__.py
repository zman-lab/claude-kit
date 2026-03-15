"""claude-core AI 프로바이더 모듈.

AIProvider ABC + DualAIProvider 라우팅 + DaemonProvider 어댑터
+ CLIProvider subprocess + 비용 계산 + 에러 계층.
"""

from .base import AIProvider
from .cli import CLIProvider
from .cost import (
    DEFAULT_FALLBACK_PRICING,
    DEFAULT_KRW_PER_USD,
    DEFAULT_MODEL_PRICING,
    CostTracker,
    calculate_cost,
    make_usage_dict,
)
from .daemon_adapter import DaemonProvider
from .dual import DualAIProvider
from .errors import (
    AIAuthenticationError,
    AIConnectionError,
    AIInvalidRequestError,
    AIMaxTokensExceeded,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    ClaudeCoreError,
    DaemonBusyError,
    DaemonError,
    DaemonNotRunningError,
    PoolAcquireTimeoutError,
    ProviderNotConfiguredError,
)

__all__ = [
    # Base
    "AIProvider",
    # Routing
    "DualAIProvider",
    # Providers
    "CLIProvider",
    "DaemonProvider",
    # Cost
    "calculate_cost",
    "make_usage_dict",
    "CostTracker",
    "DEFAULT_MODEL_PRICING",
    "DEFAULT_FALLBACK_PRICING",
    "DEFAULT_KRW_PER_USD",
    # Errors
    "ClaudeCoreError",
    "AIProviderError",
    "AITimeoutError",
    "AIConnectionError",
    "AIRateLimitError",
    "AIAuthenticationError",
    "AIInvalidRequestError",
    "AIMaxTokensExceeded",
    "DaemonError",
    "DaemonNotRunningError",
    "DaemonBusyError",
    "PoolAcquireTimeoutError",
    "ProviderNotConfiguredError",
]
