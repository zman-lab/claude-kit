"""
CLI 데몬 추상 기본 클래스.

모든 데몬 서비스가 공유하는 프로세스 생명주기, stdin/stdout 통신,
유휴 타이머, 워밍업 풀 관리를 하나의 추상 클래스로 통합한다.

서브클래스 필수 구현:
    - _build_command() -> list[str]: 실행 명령어 구성
    - _on_process_started(daemon) -> None: 프로세스 시작 후 초기화

선택적 오버라이드:
    - _serialize_input(data) -> bytes: stdin 직렬화 (기본: JSON+LF)
    - _parse_output_line(line) -> Optional[dict]: stdout 파싱 (기본: NDJSON)
"""
import asyncio
import json
import logging
import signal
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional

from .config import DaemonConfig
from .models import DaemonProcess, DaemonStatus, ProcessState

logger = logging.getLogger(__name__)


class BaseDaemon(ABC):
    """
    CLI 데몬 추상 기본 클래스.

    프로세스 생성·종료·통신·유휴 관리·워밍업 풀 등
    공통 로직을 제공하며, 서브클래스는 명령어 구성과 초기화만 구현하면 된다.
    """

    def __init__(self, config: DaemonConfig):
        self._config = config
        self._warm_pool: list[asyncio.subprocess.Process] = []

    @property
    def config(self) -> DaemonConfig:
        return self._config

    # ------------------------------------------------------------------
    # 추상 메서드
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_command(self) -> list[str]:
        """실행할 CLI 명령어 리스트를 반환한다."""
        ...

    @abstractmethod
    async def _on_process_started(self, daemon: DaemonProcess) -> None:
        """프로세스 시작 직후 호출. 초기 핸드셰이크 등 처리."""
        ...

    # ------------------------------------------------------------------
    # 선택적 오버라이드: 직렬화 / 파싱
    # ------------------------------------------------------------------

    def _serialize_input(self, data: Any) -> bytes:
        """stdin 직렬화. 기본: JSON + 개행(LF)."""
        return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")

    def _parse_output_line(self, line: bytes) -> Optional[dict]:
        """
        stdout 한 줄 파싱. 기본: NDJSON.
        None을 반환하면 해당 줄은 무시된다.
        """
        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            return None
        try:
            return json.loads(line_str)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # 프로세스 생명주기
    # ------------------------------------------------------------------

    async def spawn_process(self) -> asyncio.subprocess.Process:
        """프로세스 1개 생성 (인스턴스 미배정).

        생성 직후 100ms 대기하여 즉시 사망(잘못된 인자 등)을 감지한다.
        즉시 사망 시 stderr를 읽어 상세 에러 메시지와 함께 예외를 발생시킨다.
        """
        cmd = self._build_command()
        env = self._config.build_env()

        logger.info(
            "[%s] 프로세스 생성 시도: cmd=%s",
            self._config.daemon_type, " ".join(cmd),
        )

        kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE if self._config.stdin_enabled else None,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env,
            "limit": self._config.stdout_limit,
        }
        if self._config.cwd:
            kwargs["cwd"] = self._config.cwd

        process = await asyncio.create_subprocess_exec(*cmd, **kwargs)

        # 즉시 사망 감지: 100ms 대기 후 프로세스가 이미 죽었는지 확인
        await asyncio.sleep(0.1)
        if process.returncode is not None:
            stderr_bytes = b""
            try:
                stderr_bytes = await asyncio.wait_for(
                    process.stderr.read(), timeout=1.0,
                )
            except Exception:
                pass
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            logger.error(
                "[%s] 프로세스 즉시 사망: pid=%d, exit_code=%d, "
                "stderr=%s, cmd=%s",
                self._config.daemon_type, process.pid,
                process.returncode, stderr_text[:500],
                " ".join(cmd),
            )
            raise RuntimeError(
                f"프로세스 즉시 사망 (exit_code={process.returncode}): "
                f"{stderr_text[:300]}"
            )

        logger.info(
            "[%s] 프로세스 생성 완료: pid=%d",
            self._config.daemon_type, process.pid,
        )
        return process

    async def create_daemon(self, instance_id: str) -> DaemonProcess:
        """
        인스턴스에 프로세스 배정.
        워밍업 풀에 살아있는 프로세스가 있으면 우선 사용하고,
        없으면 새로 생성한다.
        """
        process = self._pop_warm_process()
        if process is None:
            process = await self.spawn_process()

        daemon = DaemonProcess(
            instance_id=instance_id,
            daemon_type=self._config.daemon_type,
            process=process,
            state=ProcessState.IDLE,
        )
        await self._on_process_started(daemon)
        return daemon

    async def shutdown_process(self, daemon: DaemonProcess, reason: str = "") -> None:
        """3단계 정상 종료 (P0-4/P1-6).

        Stage 1: stdin.close() → stdin_close_timeout 대기
        Stage 2: SIGTERM → shutdown_timeout 대기
        Stage 3: SIGKILL → wait()

        각 단계에서 프로세스가 종료되면 이후 단계를 건너뛴다.
        """
        if not daemon.is_alive:
            daemon.state = ProcessState.DEAD
            return

        daemon.state = ProcessState.SHUTTING_DOWN
        proc = daemon.process

        try:
            # Stage 1: stdin.close
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
                try:
                    await asyncio.wait_for(
                        proc.wait(),
                        timeout=self._config.stdin_close_timeout,
                    )
                    logger.info(
                        "[%s:%s] stdin.close로 정상 종료 (pid=%s, reason=%s)",
                        self._config.daemon_type, daemon.instance_id,
                        daemon.pid, reason,
                    )
                    return  # 성공!
                except asyncio.TimeoutError:
                    pass  # Stage 2로

            # Stage 2: SIGTERM
            try:
                proc.terminate()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(
                    proc.wait(),
                    timeout=self._config.shutdown_timeout,
                )
                logger.info(
                    "[%s:%s] SIGTERM으로 종료 (pid=%s, reason=%s)",
                    self._config.daemon_type, daemon.instance_id,
                    daemon.pid, reason,
                )
                return
            except asyncio.TimeoutError:
                pass  # Stage 3로

            # Stage 3: SIGKILL
            try:
                proc.kill()
                await proc.wait()
                logger.warning(
                    "[%s:%s] SIGKILL 강제 종료 (pid=%s, reason=%s)",
                    self._config.daemon_type, daemon.instance_id,
                    daemon.pid, reason,
                )
            except ProcessLookupError:
                pass
        except Exception as e:
            logger.warning(
                "[%s:%s] 종료 중 오류: %s",
                self._config.daemon_type, daemon.instance_id, e,
            )
        finally:
            daemon.state = ProcessState.DEAD

    def cancel_request(self, daemon: DaemonProcess) -> bool:
        """SIGINT로 현재 요청만 중단. 프로세스 자체는 유지된다."""
        if daemon.is_alive:
            try:
                daemon.process.send_signal(signal.SIGINT)
                return True
            except (ProcessLookupError, OSError):
                pass
        return False

    # ------------------------------------------------------------------
    # stdin / stdout 통신
    # ------------------------------------------------------------------

    async def write_stdin(self, daemon: DaemonProcess, data: Any) -> None:
        """stdin에 데이터 전송. 전송 후 상태를 BUSY로 전환한다."""
        if not daemon.process.stdin:
            raise RuntimeError("stdin이 비활성화된 데몬")

        message_bytes = self._serialize_input(data)
        daemon.process.stdin.write(message_bytes)
        await daemon.process.stdin.drain()
        daemon.last_active_at = time.time()
        daemon.state = ProcessState.BUSY

    async def read_stdout_lines(
        self,
        daemon: DaemonProcess,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        stdout에서 파싱된 이벤트를 비동기 yield.

        - 3초마다 keepalive 이벤트를 yield하여 연결 유지
        - EOF 수신 시 상태를 DEAD로 전환하고 종료
        - 전체 타임아웃 초과 시 TimeoutError 발생
        """
        effective_timeout = timeout or self._config.request_timeout
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            remaining = effective_timeout - elapsed
            if remaining <= 0:
                raise TimeoutError(
                    f"stdout 읽기 타임아웃: {effective_timeout}초 초과"
                )

            try:
                line = await asyncio.wait_for(
                    daemon.process.stdout.readline(),
                    timeout=min(remaining, 3.0),
                )
            except asyncio.TimeoutError:
                if remaining <= 3.0:
                    raise TimeoutError(
                        f"stdout 읽기 타임아웃: {effective_timeout}초 초과"
                    )
                yield {"type": "keepalive"}
                continue

            if not line:  # EOF — 프로세스 사망
                stderr_text = await self._read_stderr(daemon)
                logger.warning(
                    "[%s] stdout EOF (프로세스 사망): instance=%s, pid=%s, "
                    "exit_code=%s, stderr=%s",
                    self._config.daemon_type,
                    daemon.instance_id,
                    daemon.pid,
                    daemon.process.returncode,
                    stderr_text[:500] if stderr_text else "(비어있음)",
                )
                daemon.state = ProcessState.DEAD
                return

            parsed = self._parse_output_line(line)
            if parsed is not None:
                yield parsed

    # ------------------------------------------------------------------
    # 유휴 타이머
    # ------------------------------------------------------------------

    def start_idle_timer(self, daemon: DaemonProcess, callback) -> None:
        """
        유휴 타이머 시작(또는 리셋).
        타임아웃 도달 시 callback(instance_id)이 호출된다.
        """
        self.cancel_idle_timer(daemon)
        daemon.last_active_at = time.time()
        daemon.state = ProcessState.IDLE

        async def _idle_shutdown():
            await asyncio.sleep(self._config.idle_timeout)
            if daemon.state != ProcessState.IDLE:
                return  # 활성 요청 중이면 종료하지 않음
            await callback(daemon.instance_id)

        daemon._idle_task = asyncio.create_task(_idle_shutdown())

    def cancel_idle_timer(self, daemon: DaemonProcess) -> None:
        """진행 중인 유휴 타이머를 취소한다."""
        if daemon._idle_task and not daemon._idle_task.done():
            daemon._idle_task.cancel()
            daemon._idle_task = None

    # ------------------------------------------------------------------
    # stderr 수집 유틸리티
    # ------------------------------------------------------------------

    async def _read_stderr(self, daemon: DaemonProcess) -> str:
        """죽은 프로세스의 stderr를 최대한 읽어 반환한다.

        이미 죽은 프로세스이므로 버퍼에 남은 데이터를 읽는다.
        타임아웃 1초를 적용하여 blocking을 방지한다.
        """
        if not daemon.process.stderr:
            return ""

        try:
            raw = await asyncio.wait_for(
                daemon.process.stderr.read(4096),
                timeout=1.0,
            )
            return raw.decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, Exception):
            # 버퍼에서 직접 읽기 시도
            try:
                if hasattr(daemon.process.stderr, "_buffer"):
                    buf = bytes(daemon.process.stderr._buffer)
                    return buf.decode("utf-8", errors="replace").strip()
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------------
    # 워밍업 풀
    # ------------------------------------------------------------------

    async def warmup(self, count: Optional[int] = None) -> int:
        """
        프로세스를 미리 생성하여 워밍업 풀에 적재.
        CLI 기동·핸드셰이크 지연을 첫 요청 전에 해소한다.

        Returns:
            실제로 생성된 프로세스 수
        """
        target = count if count is not None else self._config.warmup_count
        created = 0

        for i in range(target):
            try:
                process = await self.spawn_process()
                self._warm_pool.append(process)
                created += 1
                logger.info(
                    "[%s] 워밍업 프로세스 준비 완료: pid=%d (%d/%d)",
                    self._config.daemon_type, process.pid, i + 1, target,
                )
            except Exception as e:
                logger.warning(
                    "[%s] 워밍업 생성 실패: %s", self._config.daemon_type, e
                )

        return created

    def _pop_warm_process(self) -> Optional[asyncio.subprocess.Process]:
        """워밍업 풀에서 살아있는 프로세스 1개를 꺼낸다."""
        while self._warm_pool:
            candidate = self._warm_pool.pop(0)
            if candidate.returncode is None:
                return candidate
        return None

    async def cleanup_warm_pool(self) -> None:
        """워밍업 풀의 모든 프로세스를 종료하고 풀을 비운다."""
        for proc in self._warm_pool:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(
                        proc.wait(), timeout=self._config.shutdown_timeout
                    )
                except (asyncio.TimeoutError, ProcessLookupError):
                    proc.kill()
                    # 좀비 프로세스 방지: kill 후 반드시 wait 호출
                    await proc.wait()
        self._warm_pool.clear()

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_daemon_status(self, daemon: DaemonProcess) -> DaemonStatus:
        """DaemonProcess의 현재 상태를 DaemonStatus 스냅샷으로 반환한다."""
        return DaemonStatus(
            instance_id=daemon.instance_id,
            daemon_type=daemon.daemon_type,
            pid=daemon.pid,
            state=daemon.state.value,
            alive=daemon.is_alive,
            uptime=daemon.uptime,
            idle=daemon.idle_seconds,
            restart_count=daemon.restart_count,
            metadata=dict(daemon.metadata),
        )
