"""Claude CLI 데몬 SDK 초기화 및 전역 관리."""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 전역 인스턴스
_manager = None
_chat_daemon = None
_chat_binder = None
_initialized = False


async def init_chat_sdk():
    """SDK 초기화. Board 시작 시 호출."""
    global _manager, _chat_daemon, _chat_binder, _initialized

    cli_path = os.getenv("CLAUDE_CLI_PATH", "claude")
    model = os.getenv("CLAUDE_MODEL", "claude-opus-4-20250514")
    project_path = os.getenv("CHAT_PROJECT_PATH", os.getcwd())
    initial_command = os.getenv("CHAT_INITIAL_COMMAND")
    thinking_budget = os.getenv("CHAT_THINKING_BUDGET", "high")
    max_tokens_str = os.getenv("CHAT_MAX_TOKENS")
    max_tokens = int(max_tokens_str) if max_tokens_str else None

    try:
        from claude_core import (
            DaemonManager, ClaudeDaemon,
            ChatBinder, create_chat_daemon_config,
        )

        config = create_chat_daemon_config(
            cli_path=cli_path,
            model=model,
            project_path=project_path,
            initial_command=initial_command,
            thinking_budget=thinking_budget,
            max_tokens=max_tokens,
        )

        _manager = DaemonManager()
        _chat_daemon = ClaudeDaemon(config, settings=None, manager=_manager)
        _manager.register(_chat_daemon)
        _chat_binder = ChatBinder(config, _manager)

        # Warmup
        await _chat_binder.warmup()
        _initialized = True
        logger.info("Chat SDK 초기화 완료: cli=%s, model=%s", cli_path, model)

    except ImportError:
        logger.warning("claude-core SDK 미설치 — 채팅 기능 placeholder 모드")
        _initialized = False
    except Exception as e:
        logger.error("Chat SDK 초기화 실패: %s", e)
        _initialized = False


async def shutdown_chat_sdk():
    """SDK 정리. Board 종료 시 호출."""
    global _manager, _chat_binder, _initialized
    if _chat_binder:
        await _chat_binder.shutdown()
    if _manager:
        await _manager.shutdown_all()
    _initialized = False
    logger.info("Chat SDK 종료 완료")


def is_sdk_available() -> bool:
    return _initialized


def get_chat_binder():
    return _chat_binder


def get_chat_daemon():
    return _chat_daemon
