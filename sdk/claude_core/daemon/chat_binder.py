"""
채팅 모드 전용 세션-프로세스 바인더.

DaemonPool의 IDLE→BUSY→CLEARING→IDLE 상태머신은 채팅 모드와 맞지 않으므로,
세션 ↔ 프로세스를 1:1로 바인딩하는 단순한 구조를 사용한다.

사용 시나리오:
    - Board 시작 시 warmup() → CLI 1개 미리 생성
    - 새 채팅 → bind(session_id) → warmup된 프로세스 할당 (없으면 on-demand spawn)
    - 대화 중 → get(session_id) → 바인딩된 프로세스 조회
    - 채팅 종료 → unbind(session_id) → session_hash 반환 + 프로세스 종료
    - 이어하기 → resume(session_id, session_hash) → 새 프로세스 + --resume
"""
import asyncio
import logging
from typing import Optional

from .config import DaemonConfig
from .models import DaemonProcess

logger = logging.getLogger(__name__)


class ChatBinder:
    """세션 ↔ 프로세스 1:1 바인딩. DaemonPool 대체."""

    def __init__(self, config: DaemonConfig, manager: "DaemonManager"):
        """
        Args:
            config: 채팅용 DaemonConfig (clear_on_release=False 권장)
            manager: DaemonManager 인스턴스
        """
        self._config = config
        self._manager = manager
        self._bindings: dict[str, DaemonProcess] = {}  # session_id → process
        self._warm_process: Optional[DaemonProcess] = None
        self._warmup_lock = asyncio.Lock()
        self._bind_lock = asyncio.Lock()

    async def warmup(self) -> None:
        """프로세스 1개 미리 생성. 보드 시작 시 호출."""
        async with self._warmup_lock:
            if self._warm_process is not None:
                return  # 이미 warmup됨
            try:
                process = await self._manager.ensure_daemon(
                    self._config.daemon_type, "__warmup__"
                )
                self._warm_process = process
                logger.info("[ChatBinder] warmup 완료: pid=%s", process.pid)
            except Exception as e:
                logger.error("[ChatBinder] warmup 실패: %s", e)
                raise

    async def bind(self, session_id: str) -> DaemonProcess:
        """새 세션에 프로세스 바인딩.

        warmup된 프로세스가 있으면 즉시 할당, 없으면 on-demand spawn.

        Args:
            session_id: 채팅 세션 식별자

        Returns:
            바인딩된 DaemonProcess

        Raises:
            RuntimeError: 이미 바인딩된 session_id
        """
        async with self._bind_lock:
            if session_id in self._bindings:
                raise RuntimeError(f"이미 바인딩된 세션: {session_id}")

            if self._warm_process is not None:
                process = self._warm_process
                self._warm_process = None
                logger.info("[ChatBinder] warmup 프로세스 할당: session=%s, pid=%s",
                            session_id, process.pid)
            else:
                logger.info("[ChatBinder] on-demand spawn: session=%s", session_id)
                process = await self._manager.ensure_daemon(
                    self._config.daemon_type, f"chat_{session_id}"
                )

            self._bindings[session_id] = process

            # 백그라운드로 다음 warmup 시작
            asyncio.create_task(self._background_warmup())

            return process

    async def unbind(self, session_id: str) -> Optional[str]:
        """세션 해제. CLI session_hash 반환.

        프로세스를 종료하고 session_hash를 반환한다.
        반환된 session_hash로 나중에 resume() 가능.

        Args:
            session_id: 채팅 세션 식별자

        Returns:
            CLI session_hash (resume용). 없으면 None.
        """
        process = self._bindings.pop(session_id, None)
        if process is None:
            logger.warning("[ChatBinder] 바인딩 없는 세션 unbind 시도: %s", session_id)
            return None

        session_hash = process.metadata.get("session_id")

        try:
            await self._manager.shutdown_daemon(
                self._config.daemon_type, process.instance_id, "chat_unbind"
            )
        except Exception as e:
            logger.error("[ChatBinder] 프로세스 종료 실패: session=%s, error=%s", session_id, e)

        # resume 전용 임시 타입 정리
        resume_type = f"chat_resume_{session_id}"
        if resume_type in self._manager.registered_types:
            try:
                await self._manager.shutdown_type(resume_type)
            except Exception:
                pass

        logger.info("[ChatBinder] unbind: session=%s, hash=%s", session_id, session_hash)
        return session_hash

    async def resume(self, session_id: str, session_hash: str) -> DaemonProcess:
        """기존 세션을 이어서 대화. --resume 플래그로 CLI 프로세스 시작.

        새 프로세스를 생성하되, CLI에 --resume <session_hash>를 전달하여
        이전 대화를 이어간다. 프로세스 종료 후에도 가능.

        Args:
            session_id: 새 세션 식별자
            session_hash: 이전 세션의 CLI session hash (unbind() 반환값)

        Returns:
            바인딩된 DaemonProcess (이전 대화 컨텍스트 포함)

        Raises:
            RuntimeError: 이미 바인딩된 session_id
        """
        import dataclasses

        async with self._bind_lock:
            if session_id in self._bindings:
                raise RuntimeError(f"이미 바인딩된 세션: {session_id}")

            # --resume 플래그가 추가된 임시 설정 생성
            resume_command = list(self._config.command) + ["--resume", session_hash]
            resume_daemon_type = f"chat_resume_{session_id}"
            resume_config = dataclasses.replace(
                self._config,
                command=resume_command,
                daemon_type=resume_daemon_type,
            )

            # 임시 daemon impl 생성 및 등록
            # ClaudeDaemon을 직접 import하면 순환 참조이므로 manager에서 기존 impl을 참조
            base_impl = self._manager.get_impl(self._config.daemon_type)

            # BaseDaemon 서브클래스를 동적으로 생성하지 않고,
            # 기존 impl의 create_daemon을 활용하되 config만 교체
            from .base import BaseDaemon

            class _ResumeWrapper(BaseDaemon):
                """resume용 임시 BaseDaemon. 기존 impl의 _build_command만 오버라이드."""
                def _build_command(self) -> list[str]:
                    # resume_config.command에 이미 --resume이 포함됨
                    # 기존 impl의 MCP 감지 로직도 적용
                    cmd = list(self._config.command)
                    mcp_path = self._config.mcp_config_path
                    if mcp_path is None:
                        if self._config.cwd:
                            from pathlib import Path
                            default_mcp = Path(self._config.cwd) / "mcp-config.json"
                            if default_mcp.exists():
                                cmd.extend(["--mcp-config", str(default_mcp)])
                    elif mcp_path == "":
                        pass
                    elif mcp_path:
                        from pathlib import Path
                        if Path(mcp_path).exists():
                            cmd.extend(["--mcp-config", mcp_path])
                    return cmd

                async def _on_process_started(self, daemon: DaemonProcess) -> None:
                    daemon.metadata["session_id"] = None

            resume_impl = _ResumeWrapper(resume_config)
            self._manager.register(resume_impl)

            try:
                process = await self._manager.ensure_daemon(resume_daemon_type, session_id)
                self._bindings[session_id] = process
                logger.info(
                    "[ChatBinder] resume: session=%s, hash=%s, pid=%s",
                    session_id, session_hash, process.pid,
                )

                # 백그라운드 warmup
                asyncio.create_task(self._background_warmup())

                return process
            except Exception:
                # 실패 시 임시 등록 정리는 하지 않음 (manager가 알아서 관리)
                raise

    async def get(self, session_id: str) -> Optional[DaemonProcess]:
        """바인딩된 프로세스 조회."""
        return self._bindings.get(session_id)

    def active_count(self) -> int:
        """현재 활성 바인딩 수."""
        return len(self._bindings)

    def has_warm_process(self) -> bool:
        """warmup된 프로세스 존재 여부."""
        return self._warm_process is not None

    async def shutdown(self) -> None:
        """모든 바인딩 해제 + warmup 프로세스 종료."""
        # 바인딩된 프로세스 모두 종료
        for session_id in list(self._bindings.keys()):
            await self.unbind(session_id)

        # warmup 프로세스 종료
        if self._warm_process is not None:
            try:
                await self._manager.shutdown_daemon(
                    self._config.daemon_type, self._warm_process.instance_id, "chat_shutdown"
                )
            except Exception as e:
                logger.error("[ChatBinder] warmup 프로세스 종료 실패: %s", e)
            self._warm_process = None

        logger.info("[ChatBinder] shutdown 완료")

    async def _background_warmup(self) -> None:
        """백그라운드 warmup. bind() 후 다음 채팅 대비."""
        try:
            await self.warmup()
        except Exception as e:
            logger.warning("[ChatBinder] 백그라운드 warmup 실패 (무시): %s", e)


# TYPE_CHECKING 지연 참조
if False:
    from .manager import DaemonManager
