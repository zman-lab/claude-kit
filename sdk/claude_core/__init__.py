"""
claude-core: Claude CLI daemon management & memory system SDK.

ClaudeBot의 daemon + memory 모듈을 독립 패키지로 추출하여
여러 프로젝트에서 공용으로 사용할 수 있게 한다.
"""

# Daemon
from claude_core.daemon.config import DaemonConfig
from claude_core.daemon.base import BaseDaemon
from claude_core.daemon.claude import (
    ClaudeDaemon,
    DaemonSettings,
    create_claude_config,
    create_memory_daemon_config,
    create_tool_daemon_config,
    create_chat_daemon_config,
)
from claude_core.daemon.chat_binder import ChatBinder
from claude_core.daemon.manager import DaemonManager
from claude_core.daemon.pool import DaemonPool
from claude_core.daemon.models import ProcessState, DaemonProcess, DaemonStatus

# Memory
from claude_core.memory.config import MemoryConfig
from claude_core.memory.models import (
    MemoryType, MemoryItem, MemorySaveRequest,
    MemorySearchResult, WriteGateResult,
)
from claude_core.memory.storage import MemoryStorage
from claude_core.memory.search import MemorySearcher
from claude_core.memory.write_gate import WriteGate
from claude_core.memory.service import MemoryService
from claude_core.memory.maintenance import MemoryMaintenance

# AI Provider (v0.2.0)
from claude_core.ai.base import AIProvider
from claude_core.ai.dual import DualAIProvider
from claude_core.ai.daemon_adapter import DaemonProvider
from claude_core.ai.cost import (
    calculate_cost,
    make_usage_dict,
    CostTracker,
    DEFAULT_MODEL_PRICING,
)
from claude_core.ai.errors import (
    ClaudeCoreError,
    AIProviderError,
    AITimeoutError,
    AIConnectionError,
    AIRateLimitError,
    AIAuthenticationError,
    AIInvalidRequestError,
    AIMaxTokensExceeded,
    DaemonError,
    DaemonNotRunningError,
    DaemonBusyError,
    PoolAcquireTimeoutError,
    ProviderNotConfiguredError,
)

# Utils (v0.2.0)
from claude_core.utils.json_repair import repair_json, parse_json_safe

# Models
from claude_core.models import ClaudeResponse

__version__ = "1.1.0.0"

__all__ = [
    # Daemon
    "DaemonConfig",
    "BaseDaemon",
    "ClaudeDaemon",
    "DaemonSettings",
    "create_claude_config",
    "create_memory_daemon_config",
    "create_tool_daemon_config",
    "create_chat_daemon_config",
    "ChatBinder",
    "DaemonManager",
    "DaemonPool",
    "ProcessState",
    "DaemonProcess",
    "DaemonStatus",
    # Memory
    "MemoryConfig",
    "MemoryType",
    "MemoryItem",
    "MemorySaveRequest",
    "MemorySearchResult",
    "WriteGateResult",
    "MemoryStorage",
    "MemorySearcher",
    "WriteGate",
    "MemoryService",
    "MemoryMaintenance",
    # AI Provider
    "AIProvider",
    "DualAIProvider",
    "DaemonProvider",
    "calculate_cost",
    "make_usage_dict",
    "CostTracker",
    "DEFAULT_MODEL_PRICING",
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
    # Utils
    "repair_json",
    "parse_json_safe",
    # Models
    "ClaudeResponse",
]
