"""
Claude CLI 전용 데몬 구현체.

BaseDaemon을 상속하여 Claude Code CLI(stream-json 모드)와의 통신을 담당한다.

주요 역할:
    - MCP 설정 자동 감지 및 명령어 확장
    - session_id 기반 대화 연속성 관리
    - Claude 프로토콜 이벤트를 통일된 스트리밍 포맷으로 변환

의존성 분리 (원본 대비 변경사항):
    - Settings → DaemonSettings Protocol
    - SessionData → 제거 (실제 미사용)
    - ClaudeResponse → claude_core.models.ClaudeResponse
    - get_daemon_manager() → 생성자 주입 (self._manager)
"""
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable

from .base import BaseDaemon
from .config import DaemonConfig
from .models import DaemonProcess, ProcessState
from ..models import ClaudeResponse

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# DaemonSettings Protocol (Settings 대체)
# ------------------------------------------------------------------

@runtime_checkable
class DaemonSettings(Protocol):
    """데몬 생성에 필요한 최소 설정 인터페이스.

    호출 프로젝트의 Settings 클래스가 이 속성들을 가지고 있으면
    별도 어댑터 없이 그대로 전달할 수 있다.
    """
    claude_cli_path: str
    claude_model: str
    claude_max_turns: int
    claude_timeout: int
    claude_daemon_idle_timeout: int
    project_base_path: str
    memory_write_gate_model: str


# ------------------------------------------------------------------
# 팩토리 함수
# ------------------------------------------------------------------

def create_claude_config(settings: DaemonSettings) -> DaemonConfig:
    """
    DaemonSettings에서 Claude 전용 DaemonConfig를 생성한다.

    Args:
        settings: DaemonSettings Protocol을 만족하는 설정 인스턴스

    Returns:
        Claude CLI 데몬용 불변 설정 객체
    """
    pool_size = getattr(settings, "claude_pool_size", 3)
    return DaemonConfig(
        daemon_type="claude",
        command=[
            settings.claude_cli_path,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", settings.claude_model,
            "--max-turns", str(settings.claude_max_turns),
            "--dangerously-skip-permissions",
        ],
        cwd=settings.project_base_path,
        env_remove=["CLAUDECODE"],
        idle_timeout=settings.claude_daemon_idle_timeout,
        request_timeout=settings.claude_timeout,
        warmup_count=pool_size,
        pool_size=pool_size,
    )


def create_memory_daemon_config(settings: DaemonSettings) -> DaemonConfig:
    """
    메모리 서비스 전용 DaemonConfig를 생성한다.

    메인 채팅과 다른 모델(haiku)을 사용하는 별도 데몬 설정.

    Args:
        settings: DaemonSettings Protocol을 만족하는 설정 인스턴스

    Returns:
        메모리 서비스용 불변 설정 객체
    """
    return DaemonConfig(
        daemon_type="claude-memory",
        command=[
            settings.claude_cli_path,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", settings.memory_write_gate_model,
            "--max-turns", str(settings.claude_max_turns),
            "--dangerously-skip-permissions",
        ],
        cwd=settings.project_base_path,
        env_remove=["CLAUDECODE"],
        idle_timeout=settings.claude_daemon_idle_timeout,
        request_timeout=settings.claude_timeout,
        warmup_count=1,
        mcp_config_path="",
        pool_name="claude-memory",
    )


def create_tool_daemon_config(settings: DaemonSettings, mcp_path: str) -> DaemonConfig:
    """
    도구 실행 전용 DaemonConfig를 생성한다.

    on-demand로 생성되는 도구 실행 전용 데몬 설정.

    Args:
        settings: DaemonSettings Protocol을 만족하는 설정 인스턴스
        mcp_path: 도구별 MCP 설정 파일 경로

    Returns:
        도구 실행용 불변 설정 객체
    """
    return DaemonConfig(
        daemon_type="claude-tool",
        command=[
            settings.claude_cli_path,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", settings.claude_model,
            "--max-turns", str(settings.claude_max_turns),
            "--dangerously-skip-permissions",
        ],
        cwd=settings.project_base_path,
        env_remove=["CLAUDECODE"],
        idle_timeout=settings.claude_daemon_idle_timeout,
        request_timeout=settings.claude_timeout,
        warmup_count=0,  # on-demand이므로 워밍업 없음
        mcp_config_path=mcp_path,
        pool_name="claude-tool",
    )


def create_chat_daemon_config(
    cli_path: str,
    model: str = "claude-opus-4-20250514",
    project_path: str = ".",
    initial_command: Optional[str] = None,
    max_turns: int = 0,
    thinking_budget: Optional[str] = "high",
    max_tokens: Optional[int] = None,
    idle_timeout: int = 3600,
    request_timeout: int = 1800,
    mcp_config_path: Optional[str] = None,
) -> DaemonConfig:
    """채팅 모드용 DaemonConfig 생성.

    Pool 대신 ChatBinder와 함께 사용.
    clear_on_release=False로 대화 컨텍스트를 유지한다.

    Args:
        cli_path: Claude CLI 실행 경로
        model: 사용할 모델 ID
        project_path: 작업 디렉토리
        initial_command: 세션 시작 시 실행할 명령 (예: "/jw-work")
        max_turns: 최대 턴 수 (0=무제한)
        thinking_budget: thinking level ("high", "medium" 등)
        max_tokens: 최대 출력 토큰 (None=기본값)
        idle_timeout: 유휴 타임아웃(초)
        request_timeout: 요청 타임아웃(초)
        mcp_config_path: MCP 설정 파일 경로

    Returns:
        채팅 모드용 DaemonConfig
    """
    command = [
        cli_path,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--dangerously-skip-permissions",
    ]
    if max_turns:
        command.extend(["--max-turns", str(max_turns)])
    if thinking_budget:
        command.extend(["--thinking-budget", thinking_budget])
    if max_tokens:
        command.extend(["--max-tokens", str(max_tokens)])

    return DaemonConfig(
        daemon_type="chat",
        command=command,
        cwd=project_path,
        env_remove=["CLAUDECODE"],
        idle_timeout=idle_timeout,
        request_timeout=request_timeout,
        warmup_count=1,
        pool_size=1,
        clear_on_release=False,
        initial_command=initial_command,
        thinking_budget=thinking_budget,
        max_tokens=max_tokens,
        mcp_config_path=mcp_config_path,
    )


# ------------------------------------------------------------------
# ClaudeDaemon
# ------------------------------------------------------------------

class ClaudeDaemon(BaseDaemon):
    """
    Claude Code CLI 데몬.

    BaseDaemon의 프로세스 생명주기·통신 인프라를 활용하고,
    Claude 프로토콜(stream-json)에 특화된 이벤트 변환과
    세션 관리를 추가한다.

    pool_size > 1이면 라운드로빈으로 요청을 분산하여 동시 처리를 지원한다.
    """

    _slot_counter: int = 0  # 클래스 레벨 라운드로빈 카운터 (asyncio 단일 루프이므로 thread-safe)

    def __init__(
        self,
        config: DaemonConfig,
        settings: DaemonSettings,
        manager: "DaemonManager",
        pool: "Optional[DaemonPool]" = None,
    ):
        """
        Args:
            config: DaemonConfig 설정
            settings: DaemonSettings Protocol을 만족하는 설정 인스턴스
            manager: DaemonManager 인스턴스 (순환 의존 제거)
            pool: DaemonPool 인스턴스 (Phase 2). None이면 Phase 1 라운드로빈 모드.
        """
        super().__init__(config)
        self._settings = settings
        self._manager = manager
        self._pool = pool

    # ------------------------------------------------------------------
    # BaseDaemon 추상 메서드 구현
    # ------------------------------------------------------------------

    def _build_command(self) -> list[str]:
        """Claude CLI 명령어 + MCP 설정 추가.

        mcp_config_path 값에 따라 분기:
          None  → mcp-config.json 자동 감지 불가 (SDK는 프로젝트 루트를 알 수 없음)
          ""    → MCP 없음 (memory 데몬)
          "경로" → 해당 파일 사용
        """
        cmd = list(self._config.command)
        mcp_path = self._config.mcp_config_path

        if mcp_path is None:
            # SDK에서는 프로젝트 루트를 알 수 없으므로 자동 감지하지 않음
            # cwd에 mcp-config.json이 있으면 사용
            if self._config.cwd:
                default_mcp = Path(self._config.cwd) / "mcp-config.json"
                if default_mcp.exists():
                    cmd.extend(["--mcp-config", str(default_mcp)])
        elif mcp_path == "":
            # 빈 문자열: MCP 없음 (memory 데몬)
            pass
        elif Path(mcp_path).exists():
            # 명시적 경로
            cmd.extend(["--mcp-config", mcp_path])
        else:
            logger.warning("MCP 설정 파일을 찾을 수 없음: %s", mcp_path)

        return cmd

    async def _on_process_started(self, daemon: DaemonProcess) -> None:
        """session_id 메타데이터 초기화."""
        daemon.metadata["session_id"] = None

    # ------------------------------------------------------------------
    # 내부: 대화 초기화
    # ------------------------------------------------------------------

    async def _send_clear(self, daemon: DaemonProcess, request_id: str) -> Optional[DaemonProcess]:
        """매 요청 전 /clear 전송으로 데몬 내부 대화 초기화.
        실패 시 최대 2회 재시도 후, 그래도 실패하면 프로세스를 재생성한다.

        Returns:
            프로세스 재생성 시 새 DaemonProcess, 그렇지 않으면 None
        """
        max_retries = 2

        for attempt in range(1, max_retries + 1):
            clear_message = {
                "type": "user",
                "message": {"role": "user", "content": "/clear"},
                "session_id": daemon.metadata.get("session_id") or "default",
            }

            try:
                await self.write_stdin(daemon, clear_message)
            except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError) as e:
                logger.warning(
                    "[%s] /clear stdin 쓰기 실패 (시도 %d/%d): %s",
                    request_id, attempt, max_retries, e,
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.5)
                    continue
                # 최종 실패 → 프로세스 재생성
                logger.warning("[%s] /clear %d회 시도 모두 실패, 프로세스 재생성", request_id, max_retries)
                try:
                    await self._manager.shutdown_daemon(
                        self._config.daemon_type, daemon.instance_id, "clear_failed"
                    )
                    new_daemon = await self._manager.ensure_daemon(
                        self._config.daemon_type, daemon.instance_id
                    )
                    return new_daemon
                except Exception as re_e:
                    logger.error("[%s] /clear 실패 후 재생성도 실패 (계속 진행): %s", request_id, re_e)
                return None

            # /clear 응답 소비 (result 이벤트까지 읽고 버림)
            try:
                async for data in self.read_stdout_lines(daemon, timeout=10):
                    if data.get("type") == "keepalive":
                        continue
                    msg_type = data.get("type", "")
                    if msg_type == "system" and data.get("subtype") == "init":
                        new_sid = data.get("session_id")
                        if new_sid:
                            daemon.metadata["session_id"] = new_sid
                    elif msg_type == "result":
                        new_sid = data.get("session_id")
                        if new_sid:
                            daemon.metadata["session_id"] = new_sid
                        logger.info("[%s] /clear 완료, 대화 초기화됨 (시도 %d)", request_id, attempt)
                        return None
                # result 이벤트 없이 스트림 종료 → 재시도
                logger.warning("[%s] /clear 응답에 result 없음 (시도 %d/%d)", request_id, attempt, max_retries)
            except Exception as e:
                logger.warning(
                    "[%s] /clear 응답 소비 중 오류 (시도 %d/%d): %s",
                    request_id, attempt, max_retries, e,
                )

            if attempt < max_retries:
                await asyncio.sleep(0.5)

        # 모든 재시도 실패 → 프로세스 재생성
        logger.warning("[%s] /clear %d회 시도 모두 실패, 프로세스 재생성", request_id, max_retries)
        try:
            await self._manager.shutdown_daemon(
                self._config.daemon_type, daemon.instance_id, "clear_failed"
            )
            new_daemon = await self._manager.ensure_daemon(
                self._config.daemon_type, daemon.instance_id
            )
            return new_daemon
        except Exception as re_e:
            logger.error("[%s] /clear 실패 후 재생성도 실패 (계속 진행): %s", request_id, re_e)
        return None

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    async def ask_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Claude에게 질문하고 스트리밍 응답을 yield.

        Pool 모드 (self._pool이 있을 때):
          - Pool.acquire()로 IDLE 슬롯 획득
          - /clear 생략 (release 시 비동기로 처리)
          - Pool.release()로 슬롯 반환 + 백그라운드 /clear

        레거시 모드 (self._pool이 없을 때):
          - 라운드로빈 slot_id + Lock 기반 직렬화
          - 매 요청 전 동기 /clear

        yield 포맷:
          {"type": "text", "content": "..."}          -- 텍스트 청크
          {"type": "tool_status", "tool": "...", "status": "..."}  -- 도구 상태
          {"type": "done", "session_id": "...", "duration": ..., "full_text": "..."}  -- 완료
          {"type": "error", "message": "..."}         -- 오류
          {"type": "keepalive"}                       -- 연결 유지
        """
        if self._pool is not None:
            async for chunk in self._ask_stream_pool(prompt, system_prompt, user_id, image_paths):
                yield chunk
        else:
            async for chunk in self._ask_stream_legacy(prompt, system_prompt, user_id, image_paths):
                yield chunk

    async def _ask_stream_pool(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """Pool 모드: IDLE-first 슬롯 획득 + /clear 비동기화."""
        manager = self._manager
        pool = self._pool

        # acquire 타임아웃: pool_acquire_timeout > 0이면 사용, 아니면 request_timeout
        acquire_timeout = getattr(self._config, "pool_acquire_timeout", 0)
        if not acquire_timeout:
            acquire_timeout = self._config.request_timeout

        # 큐 대기 시작 알림
        yield json.dumps({"type": "queue", "status": "waiting"}, ensure_ascii=False)

        # Pool에서 IDLE 슬롯 획득 (타임아웃 적용)
        queue_start = time.time()
        slot_id = await pool.acquire(timeout=acquire_timeout)
        queue_wait = time.time() - queue_start

        # 슬롯 획득 알림
        yield json.dumps({
            "type": "queue",
            "status": "acquired",
            "slot_id": slot_id,
            "wait_seconds": round(queue_wait, 2),
        }, ensure_ascii=False)

        try:
            start_time = time.time()
            request_id = uuid.uuid4().hex[:8]

            # -- 1) 프로세스 확보 --
            try:
                daemon = await manager.ensure_daemon(self._config.daemon_type, slot_id)
            except FileNotFoundError:
                logger.error("[%s] Claude CLI를 찾을 수 없음: %s",
                             request_id, self._settings.claude_cli_path)
                yield json.dumps({
                    "type": "error",
                    "message": f"Claude CLI를 찾을 수 없습니다: {self._settings.claude_cli_path}",
                }, ensure_ascii=False)
                return
            except Exception as e:
                logger.error("[%s] 데몬 프로세스 생성 실패: %s", request_id, e, exc_info=True)
                yield json.dumps({
                    "type": "error",
                    "message": f"데몬 프로세스 생성 실패: {str(e)}",
                }, ensure_ascii=False)
                return

            # Pool 모드에서는 /clear가 이전 release에서 이미 비동기로 완료되었음
            # (첫 요청이거나 /clear가 성공했으면 대화 상태가 깨끗함)

            # -- 2) 프롬프트 구성 --
            full_prompt = prompt
            if image_paths:
                paths_str = " ".join(image_paths)
                full_prompt = f"[첨부 이미지: {paths_str}]\n{full_prompt}"
            if system_prompt:
                full_prompt = f"{system_prompt}\n---\n{full_prompt}"

            # -- 3) stdin 메시지 구성 --
            session_id = daemon.metadata.get("session_id")
            message = {
                "type": "user",
                "message": {"role": "user", "content": full_prompt},
                "session_id": session_id or "default",
            }

            logger.info("[%s][Pool] 요청 시작: slot=%s, prompt_len=%d",
                        request_id, slot_id, len(full_prompt))

            # -- 4) stdin 전송 --
            try:
                await self.write_stdin(daemon, message)
            except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError) as e:
                logger.warning("[%s] stdin 쓰기 실패, 프로세스 재생성 시도: %s", request_id, e)
                try:
                    await manager.shutdown_daemon(self._config.daemon_type, slot_id, "stdin_write_failed")
                    daemon = await manager.ensure_daemon(self._config.daemon_type, slot_id)
                    session_id = daemon.metadata.get("session_id")
                    message["session_id"] = session_id or "default"
                    await self.write_stdin(daemon, message)
                except Exception as retry_e:
                    logger.error("[%s] 데몬 재시작 후에도 실패: %s", request_id, retry_e)
                    yield json.dumps({
                        "type": "error",
                        "message": f"데몬 재시작 실패: {str(retry_e)}",
                    }, ensure_ascii=False)
                    return

            # -- 5) stdout에서 응답 읽기 + 이벤트 변환 --
            got_terminal_event = False

            try:
                async for chunk_json in self._read_response(daemon, start_time, request_id):
                    data = json.loads(chunk_json)
                    msg_type = data.get("type", "")
                    yield chunk_json

                    if msg_type in ("done", "error", "cancelled"):
                        got_terminal_event = True
                        self._reset_idle(daemon, manager)
                        return

            except Exception as e:
                logger.error("[%s] 데몬 응답 처리 오류: %s", request_id, e, exc_info=True)
                yield json.dumps({
                    "type": "error",
                    "message": f"응답 처리 오류: {str(e)}",
                }, ensure_ascii=False)
                got_terminal_event = True

            finally:
                if not got_terminal_event:
                    logger.warning("[%s] 터미널 이벤트 없이 스트림 종료, 안전망 done 발송", request_id)
                    duration = time.time() - start_time
                    yield json.dumps({
                        "type": "done",
                        "session_id": daemon.metadata.get("session_id"),
                        "duration": round(duration, 2),
                        "full_text": "(스트림이 예기치 않게 종료되었습니다)",
                    }, ensure_ascii=False)
                self._reset_idle(daemon, manager)

        finally:
            # Pool에 슬롯 반환 + 백그라운드 /clear
            await pool.release(slot_id, daemon_impl=self)

    async def _ask_stream_legacy(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """레거시 모드: 라운드로빈 + Lock + 동기 /clear."""
        manager = self._manager
        pool_size = self._config.pool_size

        # 라운드로빈 슬롯 배정: pool_size > 1이면 요청을 분산
        if pool_size > 1:
            slot_id = f"pool_{ClaudeDaemon._slot_counter % pool_size}"
            ClaudeDaemon._slot_counter += 1
        else:
            # pool_size 1이면 기존 동작 유지 (user_id 기반)
            slot_id = user_id or "anonymous"

        lock = manager._get_lock(self._config.daemon_type, slot_id)

        async with lock:
            start_time = time.time()
            request_id = uuid.uuid4().hex[:8]

            # -- 1) 프로세스 확보 --
            try:
                daemon = await manager.ensure_daemon(self._config.daemon_type, slot_id)
            except FileNotFoundError:
                logger.error("[%s] Claude CLI를 찾을 수 없음: %s",
                             request_id, self._settings.claude_cli_path)
                yield json.dumps({
                    "type": "error",
                    "message": f"Claude CLI를 찾을 수 없습니다: {self._settings.claude_cli_path}",
                }, ensure_ascii=False)
                return
            except Exception as e:
                logger.error("[%s] 데몬 프로세스 생성 실패: %s", request_id, e, exc_info=True)
                yield json.dumps({
                    "type": "error",
                    "message": f"데몬 프로세스 생성 실패: {str(e)}",
                }, ensure_ascii=False)
                return

            # -- 2) 대화 초기화 (/clear) --
            new_daemon = await self._send_clear(daemon, request_id)
            if new_daemon is not None:
                daemon = new_daemon

            # -- 3) 프롬프트 구성 --
            full_prompt = prompt
            if image_paths:
                paths_str = " ".join(image_paths)
                full_prompt = f"[첨부 이미지: {paths_str}]\n{full_prompt}"
            if system_prompt:
                full_prompt = f"{system_prompt}\n---\n{full_prompt}"

            # -- 4) stdin 메시지 구성 --
            session_id = daemon.metadata.get("session_id")
            message = {
                "type": "user",
                "message": {"role": "user", "content": full_prompt},
                "session_id": session_id or "default",
            }

            logger.info("[%s] 요청 시작: user_id=%s, prompt_len=%d",
                        request_id, slot_id, len(full_prompt))

            # -- 5) stdin 전송 (실패 시 프로세스 재생성 + 1회 재시도) --
            try:
                await self.write_stdin(daemon, message)
            except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError) as e:
                logger.warning("[%s] stdin 쓰기 실패, 프로세스 재생성 시도: %s", request_id, e)
                try:
                    await manager.shutdown_daemon(self._config.daemon_type, slot_id, "stdin_write_failed")
                    daemon = await manager.ensure_daemon(self._config.daemon_type, slot_id)
                    session_id = daemon.metadata.get("session_id")
                    message["session_id"] = session_id or "default"
                    await self.write_stdin(daemon, message)
                except Exception as retry_e:
                    logger.error("[%s] 데몬 재시작 후에도 실패: %s", request_id, retry_e)
                    yield json.dumps({
                        "type": "error",
                        "message": f"데몬 재시작 실패: {str(retry_e)}",
                    }, ensure_ascii=False)
                    return

            # -- 6) stdout에서 응답 읽기 + 이벤트 변환 --
            got_terminal_event = False

            try:
                async for chunk_json in self._read_response(
                    daemon, start_time, request_id
                ):
                    data = json.loads(chunk_json)
                    msg_type = data.get("type", "")

                    # 그대로 전달
                    yield chunk_json

                    # done/error/cancelled 수신 시 유휴 타이머 리셋 후 종료
                    if msg_type in ("done", "error", "cancelled"):
                        got_terminal_event = True
                        self._reset_idle(daemon, manager)
                        return

            except Exception as e:
                logger.error("[%s] 데몬 응답 처리 오류: %s", request_id, e, exc_info=True)
                yield json.dumps({
                    "type": "error",
                    "message": f"응답 처리 오류: {str(e)}",
                }, ensure_ascii=False)
                got_terminal_event = True

            finally:
                # 터미널 이벤트 없이 스트림이 종료된 경우 안전망
                if not got_terminal_event:
                    logger.warning("[%s] 터미널 이벤트 없이 스트림 종료, 안전망 done 발송", request_id)
                    duration = time.time() - start_time
                    yield json.dumps({
                        "type": "done",
                        "session_id": daemon.metadata.get("session_id"),
                        "duration": round(duration, 2),
                        "full_text": "(스트림이 예기치 않게 종료되었습니다)",
                    }, ensure_ascii=False)
                self._reset_idle(daemon, manager)

    async def ask(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> ClaudeResponse:
        """
        ask_stream()을 내부 소비하여 ClaudeResponse로 반환하는 래퍼.

        text/done/error 이벤트만 처리하고, keepalive/tool_status는 무시한다.
        스트리밍이 필요 없는 내부 서비스(메모리 분석 등)에서 사용.
        """
        full_text = ""
        session_id = None
        duration = 0.0
        is_error = False

        async for chunk_json in self.ask_stream(
            prompt, system_prompt=system_prompt, user_id=user_id,
            image_paths=image_paths,
        ):
            data = json.loads(chunk_json)
            msg_type = data.get("type", "")

            if msg_type == "done":
                full_text = data.get("full_text", "")
                session_id = data.get("session_id")
                duration = data.get("duration", 0.0)
            elif msg_type == "error":
                full_text = data.get("message", "데몬 오류")
                is_error = True

        return ClaudeResponse(
            text=full_text or "(빈 응답)",
            session_id=session_id,
            is_error=is_error,
            duration=duration,
        )

    # ------------------------------------------------------------------
    # 채팅 모드 API
    # ------------------------------------------------------------------

    async def ask_stream_chat(
        self,
        daemon: DaemonProcess,
        prompt: str,
        system_prompt: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """채팅 모드 스트리밍. /clear 없이 대화를 이어간다.

        Pool/레거시 모드와 달리:
          - /clear를 호출하지 않음 (대화 컨텍스트 유지)
          - 프로세스를 직접 전달받음 (ChatBinder가 관리)
          - 중간 이벤트를 그대로 yield

        Args:
            daemon: ChatBinder.get()으로 얻은 프로세스
            prompt: 사용자 메시지
            system_prompt: 시스템 프롬프트 (선택)
            image_paths: 첨부 이미지 경로 (선택)

        Yields:
            JSON 문자열 이벤트 (text, tool_status, done, error, keepalive)
        """
        start_time = time.time()
        request_id = uuid.uuid4().hex[:8]

        # 프롬프트 구성
        full_prompt = prompt
        if image_paths:
            paths_str = " ".join(image_paths)
            full_prompt = f"[첨부 이미지: {paths_str}]\n{full_prompt}"
        if system_prompt:
            full_prompt = f"{system_prompt}\n---\n{full_prompt}"

        # stdin 메시지 구성
        session_id = daemon.metadata.get("session_id")
        message = {
            "type": "user",
            "message": {"role": "user", "content": full_prompt},
            "session_id": session_id or "default",
        }

        logger.info("[%s][Chat] 요청 시작: prompt_len=%d", request_id, len(full_prompt))

        # stdin 전송
        try:
            await self.write_stdin(daemon, message)
        except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError) as e:
            logger.error("[%s][Chat] stdin 쓰기 실패: %s", request_id, e)
            yield json.dumps({
                "type": "error",
                "message": f"CLI 프로세스 통신 실패: {str(e)}",
            }, ensure_ascii=False)
            return

        # 응답 읽기
        got_terminal_event = False
        try:
            async for chunk_json in self._read_response(daemon, start_time, request_id):
                data = json.loads(chunk_json)
                msg_type = data.get("type", "")
                yield chunk_json

                if msg_type in ("done", "error", "cancelled"):
                    got_terminal_event = True
                    self._reset_idle(daemon, self._manager)
                    return
        except Exception as e:
            logger.error("[%s][Chat] 응답 처리 오류: %s", request_id, e, exc_info=True)
            yield json.dumps({
                "type": "error",
                "message": f"응답 처리 오류: {str(e)}",
            }, ensure_ascii=False)
            got_terminal_event = True
        finally:
            if not got_terminal_event:
                duration = time.time() - start_time
                yield json.dumps({
                    "type": "done",
                    "session_id": daemon.metadata.get("session_id"),
                    "duration": round(duration, 2),
                    "full_text": "(스트림이 예기치 않게 종료되었습니다)",
                }, ensure_ascii=False)
            self._reset_idle(daemon, self._manager)

    async def send_compact(self, daemon: DaemonProcess) -> bool:
        """명시적 /compact 전송. 대화 요약을 트리거한다.

        Args:
            daemon: 대상 프로세스

        Returns:
            성공 여부
        """
        request_id = uuid.uuid4().hex[:8]
        message = {
            "type": "user",
            "message": {"role": "user", "content": "/compact"},
            "session_id": daemon.metadata.get("session_id") or "default",
        }

        try:
            await self.write_stdin(daemon, message)
        except Exception as e:
            logger.error("[%s] /compact 전송 실패: %s", request_id, e)
            return False

        # compact 응답 소비 (result까지)
        try:
            async for data in self.read_stdout_lines(daemon, timeout=60):
                if data.get("type") == "keepalive":
                    continue
                msg_type = data.get("type", "")
                if msg_type == "system" and data.get("subtype") == "init":
                    new_sid = data.get("session_id")
                    if new_sid:
                        daemon.metadata["session_id"] = new_sid
                elif msg_type == "result":
                    new_sid = data.get("session_id")
                    if new_sid:
                        daemon.metadata["session_id"] = new_sid
                    logger.info("[%s] /compact 완료", request_id)
                    return not data.get("is_error", False)
        except Exception as e:
            logger.error("[%s] /compact 응답 처리 실패: %s", request_id, e)
            return False

        return False

    async def send_clear_explicit(self, daemon: DaemonProcess) -> bool:
        """명시적 /clear 전송. 채팅 UI의 '대화 삭제' 버튼용.

        _send_clear()와 달리 재시도/프로세스 재생성 없이 단순 전송.

        Args:
            daemon: 대상 프로세스

        Returns:
            성공 여부
        """
        request_id = uuid.uuid4().hex[:8]
        result = await self._send_clear(daemon, request_id)
        return result is None  # None이면 성공 (재생성 불필요)

    async def run_initial_command(self, daemon: DaemonProcess, command: str) -> Optional[str]:
        """초기 명령 실행 (예: /jw-work). 응답 텍스트를 반환.

        Args:
            daemon: 대상 프로세스
            command: 실행할 명령어

        Returns:
            응답 텍스트. 실패 시 None.
        """
        request_id = uuid.uuid4().hex[:8]
        logger.info("[%s] 초기 명령 실행: %s", request_id, command)

        full_text = ""
        async for chunk_json in self.ask_stream_chat(daemon, command):
            data = json.loads(chunk_json)
            if data.get("type") == "done":
                full_text = data.get("full_text", "")
            elif data.get("type") == "error":
                logger.error("[%s] 초기 명령 실패: %s", request_id, data.get("message"))
                return None

        return full_text

    # ------------------------------------------------------------------
    # 내부: 이벤트 변환
    # ------------------------------------------------------------------

    def _reset_idle(self, daemon: DaemonProcess, manager: Any) -> None:
        """유휴 타이머를 리셋한다. 타임아웃 시 manager.shutdown_daemon 호출."""

        async def _on_idle(instance_id: str) -> None:
            await manager.shutdown_daemon(self._config.daemon_type, instance_id, "idle_timeout")

        self.start_idle_timer(daemon, _on_idle)

    async def _read_response(
        self,
        daemon: DaemonProcess,
        start_time: float,
        request_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        BaseDaemon.read_stdout_lines()의 원시 이벤트를 Claude 프로토콜에 맞게 변환.

        yield 값은 JSON 문자열이며, ask_stream()에서 그대로 중계된다.
        """
        last_assistant_text = ""
        session_id = daemon.metadata.get("session_id")
        timeout = self._config.request_timeout
        consecutive_errors = 0
        max_consecutive_errors = 10

        try:
            async for data in self.read_stdout_lines(daemon, timeout=timeout):
                # keepalive 이벤트 (BaseDaemon이 3초마다 생성)
                if data.get("type") == "keepalive":
                    yield json.dumps({"type": "keepalive"}, ensure_ascii=False)
                    continue

                msg_type = data.get("type", "")
                logger.info("[%s][CLI->] type=%s, keys=%s",
                            request_id, msg_type, list(data.keys()))

                try:
                    # -- system/init: 세션 ID 저장 --
                    if msg_type == "system":
                        if data.get("subtype") == "init":
                            new_sid = data.get("session_id")
                            if new_sid:
                                daemon.metadata["session_id"] = new_sid
                                session_id = new_sid
                                logger.info("[%s] 세션 ID 획득: %s", request_id, new_sid)
                        continue

                    # -- assistant 메시지 --
                    if msg_type == "assistant" and "message" in data:
                        message = data["message"]
                        blocks = message.get("content", []) if isinstance(message, dict) else []
                        if not isinstance(blocks, list):
                            blocks = []
                        block_types = [
                            b.get("type", "?") if isinstance(b, dict) else "?"
                            for b in blocks
                        ]
                        logger.info("[%s][CLI->assistant] blocks=%s", request_id, block_types)

                        for block in blocks:
                            if not isinstance(block, dict):
                                continue
                            block_type = block.get("type")

                            if block_type == "text":
                                text = block.get("text", "")
                                if text:
                                    last_assistant_text = text
                                    logger.info(
                                        "[%s][CLI->text] len=%d, preview=%s",
                                        request_id, len(text), text[:80],
                                    )
                                    yield json.dumps(
                                        {"type": "text", "content": text},
                                        ensure_ascii=False,
                                    )

                            elif block_type == "tool_use":
                                tool_name = block.get("name", "unknown")
                                logger.info("[%s][CLI->tool_use] tool=%s", request_id, tool_name)
                                yield json.dumps(
                                    {"type": "tool_status", "tool": tool_name, "status": "running"},
                                    ensure_ascii=False,
                                )

                    # -- user tool_result --
                    elif msg_type == "user" and "message" in data:
                        message = data["message"]
                        blocks = message.get("content", []) if isinstance(message, dict) else []
                        if not isinstance(blocks, list):
                            blocks = []
                        for block in blocks:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_result":
                                tool_name = block.get("tool_use_id", "unknown")
                                is_error = block.get("is_error", False)
                                status = "error" if is_error else "done"
                                logger.info("[%s][CLI->tool_result] status=%s", request_id, status)
                                yield json.dumps(
                                    {"type": "tool_status", "tool": tool_name, "status": status},
                                    ensure_ascii=False,
                                )

                    # -- result: 턴 완료 --
                    elif msg_type == "result":
                        result_text = data.get("result", "")
                        result_sid = data.get("session_id")
                        is_error = data.get("is_error", False)
                        stop_reason = data.get("stop_reason", "")
                        num_turns = data.get("num_turns", 0)
                        errors = data.get("errors", [])

                        logger.info(
                            "[%s][CLI->result] is_error=%s, stop_reason=%s, num_turns=%s, "
                            "result_len=%d, errors=%s, last_assistant_len=%d",
                            request_id, is_error, stop_reason, num_turns,
                            len(result_text), errors, len(last_assistant_text),
                        )

                        if result_sid:
                            daemon.metadata["session_id"] = result_sid
                            session_id = result_sid

                        # Single Source of Truth: result.result 우선, fallback으로 last_assistant_text
                        final_text = result_text or last_assistant_text
                        if not final_text:
                            if is_error and errors:
                                final_text = f"오류가 발생했습니다: {'; '.join(str(e) for e in errors)}"
                            else:
                                final_text = "(응답을 생성하지 못했습니다)"
                            logger.warning(
                                "[%s] 빈 응답 감지, 대체 메시지 사용: %s",
                                request_id, final_text,
                            )

                        # 최종 텍스트가 마지막 assistant 텍스트와 다르면 text 이벤트 추가 전송
                        if final_text != last_assistant_text:
                            logger.info(
                                "[%s] 최종 텍스트 교체: last_assistant=%d->final=%d chars",
                                request_id, len(last_assistant_text), len(final_text),
                            )
                            yield json.dumps(
                                {"type": "text", "content": final_text},
                                ensure_ascii=False,
                            )

                        duration = time.time() - start_time
                        yield json.dumps({
                            "type": "done",
                            "session_id": session_id,
                            "duration": round(duration, 2),
                            "full_text": final_text,
                        }, ensure_ascii=False)
                        return

                    # -- 기타 이벤트: 연결 유지 --
                    else:
                        logger.info("[%s][CLI->keepalive] type=%s", request_id, msg_type)
                        yield json.dumps({"type": "keepalive"}, ensure_ascii=False)

                    # 정상 처리된 경우 연속 에러 카운터 리셋
                    consecutive_errors = 0

                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        "[%s] 이벤트 처리 중 오류 (%d/%d): type=%s, error=%s, raw_keys=%s",
                        request_id, consecutive_errors, max_consecutive_errors,
                        msg_type, e, list(data.keys()),
                        exc_info=True,
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            "[%s] 연속 에러 %d회 도달, 스트림 중단",
                            request_id, max_consecutive_errors,
                        )
                        yield json.dumps({
                            "type": "error",
                            "message": f"이벤트 파싱 연속 {max_consecutive_errors}회 실패로 중단",
                        }, ensure_ascii=False)
                        return
                    yield json.dumps({"type": "keepalive"}, ensure_ascii=False)
                    continue

        except TimeoutError:
            logger.error(
                "[%s] 데몬 응답 타임아웃 (%ds 초과): user_id=%s",
                request_id, timeout, daemon.instance_id,
            )
            yield json.dumps({
                "type": "error",
                "message": f"Claude CLI 타임아웃: {timeout}초 초과",
            }, ensure_ascii=False)
            return

        # read_stdout_lines가 EOF로 정상 종료된 경우 (프로세스 사망)
        logger.warning("[%s] 데몬 stdout EOF: user_id=%s", request_id, daemon.instance_id)
        if last_assistant_text:
            duration = time.time() - start_time
            yield json.dumps({
                "type": "done",
                "session_id": session_id,
                "duration": round(duration, 2),
                "full_text": last_assistant_text,
            }, ensure_ascii=False)
        else:
            yield json.dumps({
                "type": "error",
                "message": "데몬 프로세스가 예기치 않게 종료됨",
            }, ensure_ascii=False)


# TYPE_CHECKING을 피하기 위한 지연 타입 참조
if False:
    from .manager import DaemonManager
    from .pool import DaemonPool
