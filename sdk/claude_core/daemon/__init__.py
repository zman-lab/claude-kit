"""Daemon 모듈 공개 API."""
from .base import BaseDaemon
from .claude import ClaudeDaemon, create_claude_config, create_memory_daemon_config, create_tool_daemon_config
from .config import DaemonConfig, PoolConfig, PoolMode, create_pool_config
from .manager import DaemonManager, PoolManager
from .models import DaemonProcess, DaemonStatus, ProcessState, PoolStats, PoolEvent
from .pool import BatchProcessor, DaemonPool, SlotState, RoutingStrategy, IdleFirstStrategy
from ..ai.errors import PoolAcquireTimeoutError

# Optional: FastAPI 라우터 (fastapi 미설치 시 import 실패해도 모듈 로드에 영향 없음)
try:
    from .status_router import create_status_router
except ImportError:
    create_status_router = None  # type: ignore[assignment, misc]

__all__ = [
    "BaseDaemon",
    "BatchProcessor",
    "ClaudeDaemon",
    "create_claude_config",
    "create_memory_daemon_config",
    "create_pool_config",
    "create_status_router",
    "create_tool_daemon_config",
    "DaemonConfig",
    "DaemonManager",
    "DaemonPool",
    "DaemonProcess",
    "DaemonStatus",
    "IdleFirstStrategy",
    "PoolAcquireTimeoutError",
    "PoolConfig",
    "PoolEvent",
    "PoolManager",
    "PoolMode",
    "PoolStats",
    "ProcessState",
    "RoutingStrategy",
    "SlotState",
]
