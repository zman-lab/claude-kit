"""
데몬 풀: CAS 상태머신 + IDLE-first 배정 + /clear 비동기화.

DaemonPool은 DaemonManager 위에서 동작하며, 슬롯 상태를 추적하고
IDLE 슬롯을 우선 배정한다. 요청 완료 후 /clear를 백그라운드에서 수행하여
다음 요청의 대기 시간을 최소화한다.

상태 전이 (CAS 기반):
    IDLE ---[acquire]--> BUSY ---[release]--> CLEARING ---[/clear 완료]--> IDLE
                           |                      |
                           +--- [에러] --> DEAD ---+--- [교체] --> IDLE

CAS(Compare-And-Swap): 모든 상태 전이는 현재 상태+세대(generation)가
예상값과 일치할 때만 수행된다. ABA 문제를 방지하고 concurrent 안전성을 보장.

상태 동기화:
    Pool의 SlotState와 Manager의 ProcessState는 독립적으로 관리된다.
    프로세스 crash 시 Manager의 ProcessState는 DEAD가 되지만 Pool의
    SlotState는 여전히 BUSY/IDLE일 수 있다. _sync_slot_state()가
    acquire/release 시점에 Manager의 실제 프로세스 상태를 확인하여
    불일치를 즉시 보정한다.

Lock Acquisition Order (데드락 방지):
    L1: _pool_lock (슬롯 상태 변경)
      L2: _replenish_lock (보충 로직)
        L3: drain 플래그로 대체
          L4: stats()는 lock-free

엣지케이스:
    - shutdown() 시 BUSY 슬롯의 graceful shutdown 처리
    - _replace_dead_slot 실패 시 DEAD 유지 (프로세스 없는 IDLE 방지)
    - drain 모드: 새 acquire 거부 → BUSY 대기 → 종료
    - CLEARING 타임아웃: 5초 주기 모니터로 적체 감지 → DEAD 전이
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .manager import DaemonManager
    from .claude import ClaudeDaemon

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 슬롯 상태
# ------------------------------------------------------------------

class SlotState(Enum):
    """풀 슬롯의 상태."""
    IDLE = "idle"
    BUSY = "busy"
    CLEARING = "clearing"
    DEAD = "dead"


# 허용된 전이 맵
VALID_TRANSITIONS: dict[SlotState, set[SlotState]] = {
    SlotState.IDLE: {SlotState.BUSY, SlotState.CLEARING, SlotState.DEAD},
    SlotState.BUSY: {SlotState.IDLE, SlotState.CLEARING, SlotState.DEAD},
    SlotState.CLEARING: {SlotState.IDLE, SlotState.DEAD},
    SlotState.DEAD: set(),  # DEAD는 최종 상태. 교체만 가능.
}


# ------------------------------------------------------------------
# SlotInfo (CAS 상태머신 단위)
# ------------------------------------------------------------------

@dataclass
class SlotInfo:
    """슬롯 하나의 상태 + CAS 메타데이터.

    Attributes:
        slot_id: 슬롯 식별자 (예: "pool_0")
        state: 현재 슬롯 상태
        generation: CAS용 세대 카운터. 모든 상태 전이 시 +1.
        error_info: DEAD 전이 사유 (DEAD가 아니면 None)
        last_transition_at: 마지막 상태 전이 시각 (Unix timestamp)
    """
    slot_id: str
    state: SlotState
    generation: int = 0
    error_info: str | None = None
    last_transition_at: float = 0.0

    def __post_init__(self):
        if self.last_transition_at == 0.0:
            self.last_transition_at = time.time()

    def __eq__(self, other: object) -> bool:
        """SlotState와 직접 비교 가능하도록 지원 (기존 테스트 호환).

        pool._slots[slot_id] == SlotState.BUSY 패턴을 유지하기 위함.
        """
        if isinstance(other, SlotState):
            return self.state == other
        if isinstance(other, SlotInfo):
            return self.slot_id == other.slot_id and self.generation == other.generation
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.slot_id, self.generation))


# ------------------------------------------------------------------
# PoolEventBus (P1-4)
# ------------------------------------------------------------------

class PoolEventBus:
    """풀 이벤트 발행/구독.

    이벤트:
        slot_acquired(slot_id): 슬롯 획득
        slot_released(slot_id): 슬롯 반환 (CLEARING 진입)
        slot_dead(slot_id, error): 슬롯 DEAD 전이
        slot_replaced(slot_id): DEAD 슬롯 교체 성공
        pool_drained: drain 완료
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event: str, handler: Callable) -> None:
        """이벤트 핸들러 등록."""
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable) -> None:
        """이벤트 핸들러 해제."""
        if event in self._handlers:
            self._handlers[event] = [
                h for h in self._handlers[event] if h is not handler
            ]

    async def emit(self, event: str, **kwargs: Any) -> None:
        """이벤트 발행. 동기/비동기 핸들러 모두 지원."""
        for handler in self._handlers.get(event, []):
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("EventBus handler error [%s]: %s", event, e)


# ------------------------------------------------------------------
# 라우팅 전략 (Phase 3 확장 포인트)
# ------------------------------------------------------------------

class RoutingStrategy(ABC):
    """풀에서 슬롯을 선택하는 전략 인터페이스.

    Phase 2에서는 IdleFirstStrategy만 사용하며,
    Phase 3에서 StickySessionStrategy, WeightedStrategy 등을 추가할 수 있다.
    """

    @abstractmethod
    async def select_slot(self, pool: "DaemonPool") -> str:
        """사용 가능한 슬롯 ID를 반환한다. 없으면 대기."""
        ...


class IdleFirstStrategy(RoutingStrategy):
    """IDLE 슬롯 우선 배정 전략 (Phase 2 기본)."""

    async def select_slot(self, pool: "DaemonPool") -> str:
        return await pool.acquire()


# ------------------------------------------------------------------
# DaemonPool
# ------------------------------------------------------------------

class DaemonPool:
    """
    데몬 슬롯 풀.

    DaemonManager의 인스턴스를 슬롯 단위로 관리하며,
    상태 기반으로 요청을 분산하고 /clear를 비동기화한다.

    CAS 상태머신으로 모든 상태 전이의 동시성 안전성을 보장하며,
    clearing monitor, drain mode, replenish, ELASTIC 확장 등
    고급 풀 관리 기능을 제공한다.

    Args:
        manager: DaemonManager 인스턴스
        daemon_type: 관리 대상 데몬 타입 (예: "claude")
        pool_size: 슬롯 수
        clear_timeout: /clear 타임아웃(초)
        strategy: 라우팅 전략 (기본: IdleFirstStrategy)
        config: DaemonConfig 인스턴스 (새 필드 접근용, 없으면 기본값 사용)
        pool_name: 풀 이름 (로깅/stats용)
    """

    def __init__(
        self,
        manager: "DaemonManager",
        daemon_type: str,
        pool_size: int = 3,
        clear_timeout: float = 10.0,
        strategy: Optional[RoutingStrategy] = None,
        config: Any = None,
        pool_name: str | None = None,
    ):
        self._manager = manager
        self._daemon_type = daemon_type
        self._pool_size = pool_size
        self._clear_timeout = clear_timeout
        self._strategy = strategy or IdleFirstStrategy()
        self._config = config
        self._pool_name = pool_name or daemon_type

        # 타임스탬프
        self._created_at = time.time()

        # --- CAS 기반 슬롯 상태 (P0-1) ---
        now = time.time()
        self._slots: dict[str, SlotInfo] = {
            f"pool_{i}": SlotInfo(
                slot_id=f"pool_{i}",
                state=SlotState.IDLE,
                generation=0,
                last_transition_at=now,
            )
            for i in range(pool_size)
        }
        self._idle_event = asyncio.Event()
        self._idle_event.set()  # 초기에는 모든 슬롯이 IDLE

        # 백그라운드 /clear 태스크 추적 (정리용)
        self._clear_tasks: dict[str, asyncio.Task] = {}

        # shutdown/drain 플래그
        self._shutting_down = False
        self._draining: bool = False
        self._drain_event: asyncio.Event = asyncio.Event()

        # 슬롯별 마지막 에러 정보 (디버깅용)
        self._slot_errors: dict[str, dict[str, Any]] = {}

        # --- Replenish Semaphore (P0-2) ---
        max_concurrent_spawns = self._get_config_val("max_concurrent_spawns", 2)
        self._spawn_semaphore = asyncio.Semaphore(max_concurrent_spawns)
        self._replenish_lock = asyncio.Lock()

        # --- EventBus (P1-4) ---
        self._event_bus = PoolEventBus()

        # --- Clearing Monitor (P0-3) ---
        self._clearing_monitor_task: asyncio.Task | None = None
        try:
            loop = asyncio.get_running_loop()
            self._clearing_monitor_task = loop.create_task(
                self._clearing_monitor_loop()
            )
        except RuntimeError:
            # 이벤트 루프가 없는 환경 (테스트 등)
            pass

        # --- ELASTIC shrink loop (P1-1) ---
        self._shrink_task: asyncio.Task | None = None
        if self._get_config_val("pool_mode", None) is not None:
            try:
                pool_mode = self._get_config_val("pool_mode", None)
                if pool_mode is not None and getattr(pool_mode, "value", pool_mode) == "elastic":
                    loop = asyncio.get_running_loop()
                    self._shrink_task = loop.create_task(self._shrink_loop())
            except RuntimeError:
                pass

    def _get_config_val(self, name: str, default: Any) -> Any:
        """config 객체에서 안전하게 필드를 가져온다.

        다른 에이전트가 config.py에 추가할 필드를 안전하게 접근하기 위해
        getattr + 기본값 패턴을 사용한다.
        """
        if self._config is not None:
            return getattr(self._config, name, default)
        return default

    # ------------------------------------------------------------------
    # P0-1: CAS 상태 전이
    # ------------------------------------------------------------------

    def _cas_transition(
        self,
        slot_id: str,
        expected_state: SlotState,
        expected_gen: int,
        new_state: SlotState,
    ) -> bool:
        """Compare-And-Swap 상태 전이.

        현재 상태+세대가 expected와 일치할 때만 전이 성공.
        성공 시 generation +1, 실패 시 False 반환.

        DEAD 전이는 VALID_TRANSITIONS 체크를 무시한다 (force dead).
        """
        slot = self._slots.get(slot_id)
        if slot is None:
            return False

        if slot.state != expected_state or slot.generation != expected_gen:
            return False

        # DEAD 전이는 어디서든 허용 (force), 그 외에는 전이 맵 체크
        if new_state != SlotState.DEAD:
            if new_state not in VALID_TRANSITIONS.get(slot.state, set()):
                return False

        slot.state = new_state
        slot.generation += 1
        slot.last_transition_at = time.time()
        if new_state != SlotState.DEAD:
            slot.error_info = None
        return True

    def _force_dead(self, slot_id: str) -> bool:
        """슬롯을 강제로 DEAD로 전이한다 (shutdown/drain 전용).

        generation 체크 없이 무조건 DEAD로 전환.
        이미 DEAD면 아무것도 하지 않고 True 반환.
        """
        slot = self._slots.get(slot_id)
        if slot is None:
            return False
        if slot.state == SlotState.DEAD:
            return True
        slot.state = SlotState.DEAD
        slot.generation += 1
        slot.last_transition_at = time.time()
        return True

    # ------------------------------------------------------------------
    # 슬롯 접근 헬퍼 (기존 테스트 호환)
    # ------------------------------------------------------------------

    def _ensure_slot_info(self, slot_id: str) -> SlotInfo | None:
        """_slots[slot_id]가 SlotInfo가 아니면 변환한다.

        기존 테스트에서 pool._slots["pool_0"] = SlotState.IDLE 패턴으로
        직접 SlotState를 대입하는 경우를 안전하게 처리.
        """
        raw = self._slots.get(slot_id)
        if raw is None:
            return None
        if isinstance(raw, SlotInfo):
            return raw
        # SlotState가 직접 대입된 경우 → SlotInfo로 변환
        if isinstance(raw, SlotState):
            info = SlotInfo(
                slot_id=slot_id,
                state=raw,
                generation=0,
                last_transition_at=time.time(),
            )
            self._slots[slot_id] = info  # type: ignore[assignment]
            return info
        return None

    def _slot_state(self, slot_id: str) -> SlotState | None:
        """슬롯의 현재 상태를 안전하게 가져온다.

        SlotInfo든 SlotState든 상관없이 동작.
        """
        raw = self._slots.get(slot_id)
        if raw is None:
            return None
        if isinstance(raw, SlotInfo):
            return raw.state
        if isinstance(raw, SlotState):
            return raw
        return None

    def _any_state(self, state: SlotState) -> bool:
        """슬롯 중 해당 상태가 있는지 확인. SlotInfo/SlotState 혼재 안전."""
        for raw in self._slots.values():
            if isinstance(raw, SlotInfo):
                if raw.state == state:
                    return True
            elif isinstance(raw, SlotState):
                if raw == state:
                    return True
        return False

    def _all_state(self, state: SlotState) -> bool:
        """모든 슬롯이 해당 상태인지 확인. SlotInfo/SlotState 혼재 안전."""
        for raw in self._slots.values():
            if isinstance(raw, SlotInfo):
                if raw.state != state:
                    return False
            elif isinstance(raw, SlotState):
                if raw != state:
                    return False
            else:
                return False
        return True

    # ------------------------------------------------------------------
    # 상태 동기화
    # ------------------------------------------------------------------

    def _sync_slot_state(self, slot_id: str) -> bool:
        """Manager의 실제 프로세스 상태를 확인하여 SlotState와 동기화한다.

        프로세스가 crash했는데 Pool의 SlotState가 IDLE/BUSY로 남아있는
        불일치를 감지하고 DEAD로 보정한다.

        Manager에 해당 slot_id의 인스턴스가 한번도 등록된 적 없는 경우
        (풀 초기화 직후, ensure_daemon 호출 전)에는 동기화를 건너뛴다.
        불일치는 "한번 등록된 프로세스가 이후 죽은 경우"에만 발생하므로,
        Manager의 인스턴스 이력이 있는 경우에만 체크한다.

        Args:
            slot_id: 확인할 슬롯 ID

        Returns:
            True: 불일치가 감지되어 DEAD로 보정됨
            False: 정상 (동기화 불필요)
        """
        slot = self._ensure_slot_info(slot_id)
        if slot is None or slot.state == SlotState.DEAD:
            return False

        # Manager에 해당 daemon_type의 인스턴스 맵이 없거나
        # 이 slot_id가 한번도 등록된 적 없으면 → 동기화 건너뜀
        instances = self._manager._instances.get(self._daemon_type)
        if instances is None or slot_id not in instances:
            return False

        # Manager에서 실제 프로세스 상태 확인
        daemon = self._manager.get_daemon(self._daemon_type, slot_id)
        if daemon is not None:
            # 프로세스 살아있음 — 동기화 불필요
            return False

        # 프로세스가 등록되었지만 죽었는데 SlotState가 DEAD가 아님 → 불일치
        # 죽은 프로세스의 진단 정보 수집
        dead_daemon = instances.get(slot_id)
        diag = self._collect_process_diagnostics(slot_id, dead_daemon)

        logger.warning(
            "[%s] 상태 불일치 감지: slot=%s, slot_state=%s, "
            "process=dead/missing → DEAD로 보정 | "
            "exit_code=%s, pid=%s, uptime=%.1fs, last_error=%s",
            self._pool_name, slot_id, slot.state.value,
            diag.get("exit_code", "?"),
            diag.get("pid", "?"),
            diag.get("uptime", 0),
            diag.get("stderr_tail", "N/A"),
        )
        self._slot_errors[slot_id] = diag
        # CAS 대신 강제 DEAD 보정 (sync는 외부 이벤트 기반이므로)
        self._force_dead(slot_id)
        return True

    def sync_all_slots(self) -> int:
        """모든 슬롯의 상태를 Manager와 동기화한다.

        외부에서 명시적으로 전체 동기화가 필요할 때 호출한다.
        (예: 헬스체크, 디버깅)

        Returns:
            불일치가 보정된 슬롯 수
        """
        corrected = 0
        for slot_id in list(self._slots.keys()):
            if self._sync_slot_state(slot_id):
                corrected += 1

        if corrected > 0:
            # DEAD 슬롯이 생겼으므로 idle_event 상태 갱신
            if not any(s.state == SlotState.IDLE for s in self._slots.values()):
                self._idle_event.clear()

        return corrected

    # ------------------------------------------------------------------
    # 슬롯 획득 / 반환
    # ------------------------------------------------------------------

    async def acquire(self, timeout: float | None = None) -> str:
        """IDLE 슬롯을 반환한다. 없으면 IDLE이 생길 때까지 대기.

        acquire 시 각 슬롯의 실제 프로세스 상태를 확인하여,
        프로세스가 crash한 슬롯은 즉시 DEAD로 보정하고 교체를 트리거한다.

        Args:
            timeout: 최대 대기 시간(초). None이면 무한 대기.
                     **절대 시간(absolute)**: acquire 호출 시점부터의 총 대기 시간.

        Returns:
            슬롯 ID (예: "pool_0")

        Raises:
            PoolAcquireTimeoutError: timeout 내에 IDLE 슬롯을 확보하지 못함.
            RuntimeError: 풀이 shutdown/drain 중이거나 모든 슬롯이 DEAD.

        Note:
            asyncio 단일 루프 환경이므로 acquire 호출 사이에 선점은 발생하지 않는다.
            대기 중 다른 코루틴이 슬롯을 반환하면 _idle_event가 set되어 재시도한다.
            DEAD 슬롯 발견 시 백그라운드 교체를 트리거한다.
        """
        from ..ai.errors import PoolAcquireTimeoutError

        if self._draining:
            raise RuntimeError(f"Pool '{self._pool_name}' is draining, cannot acquire")
        if self._shutting_down:
            raise RuntimeError("Pool is shutting down, cannot acquire slot")

        # 절대 deadline 계산
        deadline = (time.time() + timeout) if timeout is not None else None

        while True:
            if self._draining:
                raise RuntimeError(f"Pool '{self._pool_name}' is draining, cannot acquire")
            if self._shutting_down:
                raise RuntimeError("Pool is shutting down, cannot acquire slot")

            # deadline 초과 체크
            if deadline is not None and time.time() >= deadline:
                raise PoolAcquireTimeoutError(
                    timeout_seconds=timeout,
                    pool_name=self._pool_name,
                    slot_summary=self._build_slot_summary(),
                )

            for slot_id in list(self._slots.keys()):
                # 상태 동기화: Manager의 실제 프로세스 상태 확인
                if self._sync_slot_state(slot_id):
                    pass  # DEAD로 보정됨, 아래 분기에서 처리

                # _ensure_slot_info로 SlotState 직접 대입 케이스 핸들
                slot = self._ensure_slot_info(slot_id)
                if slot is None:
                    continue

                if slot.state == SlotState.IDLE:
                    # CAS: IDLE → BUSY
                    if self._cas_transition(slot_id, SlotState.IDLE, slot.generation, SlotState.BUSY):
                        # IDLE 슬롯이 남아있는지 확인
                        if not any(
                            self._ensure_slot_info(sid) is not None
                            and self._ensure_slot_info(sid).state == SlotState.IDLE  # type: ignore
                            for sid in self._slots
                        ):
                            self._idle_event.clear()
                        # 이벤트 발행 (fire-and-forget)
                        asyncio.ensure_future(
                            self._event_bus.emit("slot_acquired", slot_id=slot_id)
                        )
                        return slot_id
                elif slot.state == SlotState.DEAD:
                    # DEAD 슬롯 발견: 백그라운드 교체 트리거
                    logger.info("[%s] DEAD 슬롯 감지, 재교체 시도: slot=%s",
                                self._pool_name, slot_id)
                    asyncio.create_task(self._replenish_slot(slot_id))

            # ELASTIC 모드: IDLE 없으면 scale-up 시도
            pool_mode = self._get_config_val("pool_mode", None)
            if pool_mode is not None and getattr(pool_mode, "value", pool_mode) == "elastic":
                new_slot = await self._maybe_scale_up()
                if new_slot:
                    slot = self._slots[new_slot]
                    if self._cas_transition(new_slot, SlotState.IDLE, slot.generation, SlotState.BUSY):
                        if not any(s.state == SlotState.IDLE for s in self._slots.values()):
                            self._idle_event.clear()
                        asyncio.ensure_future(
                            self._event_bus.emit("slot_acquired", slot_id=new_slot)
                        )
                        return new_slot

            # 모든 슬롯 DEAD면 즉시 에러 (대기해도 복구 불가)
            if all(s.state == SlotState.DEAD for s in self._slots.values()):
                error_detail = self._build_all_dead_error()
                logger.error(
                    "[%s] 모든 슬롯 DEAD — acquire 불가:\n%s",
                    self._pool_name, error_detail,
                )
                raise RuntimeError(
                    f"All pool slots are dead | {error_detail}"
                )

            # 모든 슬롯 사용 중 -> IDLE이 될 때까지 대기
            self._idle_event.clear()
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise PoolAcquireTimeoutError(
                        timeout_seconds=timeout,
                        pool_name=self._pool_name,
                        slot_summary=self._build_slot_summary(),
                    )
                wait_timeout = min(remaining, 10.0)
            else:
                wait_timeout = 10.0
            try:
                await asyncio.wait_for(self._idle_event.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                # deadline 초과 시 PoolAcquireTimeoutError
                if deadline is not None and time.time() >= deadline:
                    raise PoolAcquireTimeoutError(
                        timeout_seconds=timeout,
                        pool_name=self._pool_name,
                        slot_summary=self._build_slot_summary(),
                    )
                # 모든 슬롯 DEAD면 RuntimeError
                if all(s.state == SlotState.DEAD for s in self._slots.values()):
                    error_detail = self._build_all_dead_error()
                    logger.error(
                        "[%s] 대기 타임아웃 + 모든 슬롯 DEAD:\n%s",
                        self._pool_name, error_detail,
                    )
                    raise RuntimeError(
                        f"All pool slots are dead | {error_detail}"
                    )
                # DEAD가 아닌 슬롯이 있으면 재시도 (BUSY/CLEARING 완료 대기)

    async def release(self, slot_id: str, daemon_impl: Optional["ClaudeDaemon"] = None) -> None:
        """슬롯을 반환하고 백그라운드에서 /clear를 실행한다.

        release 시 프로세스 상태를 확인하여, 프로세스가 이미 죽었으면
        /clear를 건너뛰고 즉시 DEAD 처리 + 교체를 트리거한다.

        Args:
            slot_id: 반환할 슬롯 ID
            daemon_impl: ClaudeDaemon 인스턴스 (/clear 전송용). None이면 즉시 IDLE 복귀.
        """
        slot = self._slots.get(slot_id)
        if slot is None:
            logger.warning("[%s] 알 수 없는 슬롯 반환 시도: %s", self._pool_name, slot_id)
            return

        # 상태 동기화: 프로세스가 이미 죽었으면 /clear 없이 교체
        if self._sync_slot_state(slot_id):
            # 프로세스 crash 감지 → DEAD로 보정됨, 교체 트리거
            asyncio.create_task(self._replenish_slot(slot_id))
            return

        if daemon_impl is not None:
            # CAS: BUSY → CLEARING
            gen = slot.generation
            if self._cas_transition(slot_id, SlotState.BUSY, gen, SlotState.CLEARING):
                # 이벤트 발행
                asyncio.ensure_future(
                    self._event_bus.emit("slot_released", slot_id=slot_id)
                )
                task = asyncio.create_task(
                    self._background_clear(slot_id, daemon_impl)
                )
                self._clear_tasks[slot_id] = task
            else:
                # CAS 실패 — 이미 다른 전이가 발생. 로그만 남김.
                logger.warning(
                    "[%s] release CAS 실패: slot=%s, state=%s, gen=%d",
                    self._pool_name, slot_id, slot.state.value, slot.generation,
                )
        else:
            # daemon_impl이 없으면 /clear 생략하고 즉시 IDLE
            gen = slot.generation
            if self._cas_transition(slot_id, SlotState.BUSY, gen, SlotState.IDLE):
                self._idle_event.set()
                asyncio.ensure_future(
                    self._event_bus.emit("slot_released", slot_id=slot_id)
                )
            else:
                # CAS 실패 — 상태가 이미 변경됨
                logger.warning(
                    "[%s] release(no-clear) CAS 실패: slot=%s, state=%s, gen=%d",
                    self._pool_name, slot_id, slot.state.value, slot.generation,
                )

    # ------------------------------------------------------------------
    # Context Manager: pool.slot() (데드락 방지용 주요 API)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def slot(self, timeout: float | None = None):
        """슬롯 획득/반환을 보장하는 컨텍스트 매니저.

        Usage:
            async with pool.slot() as slot_id:
                # slot_id 사용
                ...
            # 자동 반환
        """
        slot_id = await self.acquire(timeout=timeout)
        try:
            yield slot_id
        finally:
            await self.release(slot_id)

    # ------------------------------------------------------------------
    # 백그라운드 /clear
    # ------------------------------------------------------------------

    async def _background_clear(self, slot_id: str, daemon_impl: "ClaudeDaemon") -> None:
        """백그라운드에서 /clear를 실행하고 슬롯을 IDLE로 복귀시킨다."""
        try:
            daemon = self._manager.get_daemon(self._daemon_type, slot_id)
            if daemon is None:
                # 데몬이 이미 제거된 경우
                logger.warning(
                    "[%s] /clear 시점에 데몬 없음 → DEAD: slot=%s",
                    self._pool_name, slot_id,
                )
                self._mark_slot_dead(slot_id, "clear_daemon_missing")
                asyncio.create_task(self._replenish_slot(slot_id))
                return

            # /clear 전송 (타임아웃 적용)
            await asyncio.wait_for(
                daemon_impl._send_clear(daemon, f"bg-clear-{slot_id}"),
                timeout=self._clear_timeout,
            )

            # CAS: CLEARING → IDLE
            slot = self._slots[slot_id]
            if self._cas_transition(slot_id, SlotState.CLEARING, slot.generation, SlotState.IDLE):
                self._idle_event.set()
                logger.info("[%s] /clear 완료: slot=%s", self._pool_name, slot_id)
            else:
                # CAS 실패: 이미 DEAD 등으로 전이됨 (clearing monitor 등)
                logger.info(
                    "[%s] /clear 완료 but CAS 실패 (이미 %s): slot=%s",
                    self._pool_name, slot.state.value, slot_id,
                )

        except asyncio.TimeoutError:
            logger.warning(
                "[%s] /clear 타임아웃 (%.1fs): slot=%s",
                self._pool_name, self._clear_timeout, slot_id,
            )
            daemon = self._manager.get_daemon(self._daemon_type, slot_id)
            self._mark_slot_dead(slot_id, "clear_timeout", daemon)
            asyncio.create_task(self._replenish_slot(slot_id))

        except Exception as e:
            logger.warning(
                "[%s] /clear 실패: slot=%s, error=%s",
                self._pool_name, slot_id, e,
                exc_info=True,
            )
            daemon = self._manager.get_daemon(self._daemon_type, slot_id)
            self._mark_slot_dead(slot_id, f"clear_error: {e}", daemon)
            asyncio.create_task(self._replenish_slot(slot_id))

        finally:
            self._clear_tasks.pop(slot_id, None)

    # ------------------------------------------------------------------
    # P0-2: Replenish (DEAD 슬롯 교체)
    # ------------------------------------------------------------------

    async def _replenish_slot(self, slot_id: str) -> bool:
        """DEAD 슬롯 1개 교체. Semaphore로 동시 spawn 제한, 지수 백오프 재시도.

        Returns:
            True: 교체 성공, False: 모든 재시도 실패
        """
        max_retries = self._get_config_val("dead_replace_max_retries", 3)
        base_delay = self._get_config_val("dead_replace_base_delay", 0.5)

        for attempt in range(max_retries):
            if self._draining or self._shutting_down:
                return False
            try:
                async with self._spawn_semaphore:
                    success = await self._do_replace(slot_id)
                    if success:
                        # 이벤트 발행
                        asyncio.ensure_future(
                            self._event_bus.emit("slot_replaced", slot_id=slot_id)
                        )
                        return True
            except Exception as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "[%s] replenish 실패 (attempt %d/%d): %s, %.1fs 후 재시도",
                    self._pool_name, attempt + 1, max_retries, e, delay,
                )
                await asyncio.sleep(delay)
        return False

    async def _do_replace(self, slot_id: str) -> bool:
        """실제 슬롯 교체 로직. _replenish_slot에서 호출."""
        last_error = self._slot_errors.get(slot_id, {})
        logger.info(
            "[%s] DEAD 슬롯 교체 시작: slot=%s, last_error=%s",
            self._pool_name, slot_id, last_error.get("reason", "unknown"),
        )
        try:
            # 기존 프로세스 정리
            await self._manager.shutdown_daemon(
                self._daemon_type, slot_id, "pool_dead_replacement"
            )
            # 새 프로세스 생성
            await self._manager.ensure_daemon(self._daemon_type, slot_id)

            # 교체 성공: SlotInfo를 새로 초기화 (generation 리셋하지 않고 +1)
            slot = self._slots.get(slot_id)
            if slot is not None:
                slot.state = SlotState.IDLE
                slot.generation += 1
                slot.last_transition_at = time.time()
                slot.error_info = None

            self._idle_event.set()
            # 교체 성공 시 에러 기록 정리
            self._slot_errors.pop(slot_id, None)
            logger.info("[%s] DEAD 슬롯 교체 완료: slot=%s", self._pool_name, slot_id)
            return True
        except Exception as e:
            logger.error(
                "[%s] DEAD 슬롯 교체 실패: slot=%s, error=%s",
                self._pool_name, slot_id, e, exc_info=True,
            )
            self._mark_slot_dead(slot_id, f"replace_failed: {e}")
            # 대기 중인 acquire()를 깨워서 재시도하게 함 (데드락 방지)
            self._idle_event.set()
            raise

    async def _replace_dead_slot(
        self, slot_id: str, daemon_impl: Optional["ClaudeDaemon"] = None,
    ) -> None:
        """DEAD 슬롯의 프로세스를 교체하고 IDLE로 복귀시킨다.

        기존 API 호환을 위해 유지. 내부적으로 _replenish_slot을 호출한다.
        """
        await self._replenish_slot(slot_id)

    # ------------------------------------------------------------------
    # P0-3: Clearing Monitor
    # ------------------------------------------------------------------

    async def _clearing_monitor_loop(self) -> None:
        """5초 주기로 CLEARING 슬롯 타임아웃 감지.

        generation 기반으로 안전하게 DEAD 전이.
        """
        clearing_timeout = self._get_config_val("clearing_timeout", 30.0)

        while not self._draining and not self._shutting_down:
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                return

            now = time.time()
            for slot_id, slot in list(self._slots.items()):
                if slot.state == SlotState.CLEARING:
                    elapsed = now - slot.last_transition_at
                    if elapsed > clearing_timeout:
                        logger.warning(
                            "[%s] CLEARING 타임아웃: %s (%.0fs)",
                            self._pool_name, slot_id, elapsed,
                        )
                        # CAS: CLEARING → DEAD
                        if self._cas_transition(
                            slot_id, SlotState.CLEARING, slot.generation, SlotState.DEAD
                        ):
                            slot.error_info = f"clearing_timeout ({elapsed:.0f}s)"
                            self._slot_errors[slot_id] = {
                                "slot_id": slot_id,
                                "reason": f"clearing_timeout ({elapsed:.0f}s)",
                                "timestamp": now,
                            }
                            # clear 태스크가 있으면 cancel
                            clear_task = self._clear_tasks.pop(slot_id, None)
                            if clear_task and not clear_task.done():
                                clear_task.cancel()
                            # 이벤트 발행
                            asyncio.ensure_future(
                                self._event_bus.emit(
                                    "slot_dead", slot_id=slot_id,
                                    error=f"clearing_timeout ({elapsed:.0f}s)",
                                )
                            )
                            # 교체 스케줄
                            asyncio.create_task(self._replenish_slot(slot_id))

    # ------------------------------------------------------------------
    # P0-4: Drain Mode (Graceful Shutdown)
    # ------------------------------------------------------------------

    async def drain(self) -> None:
        """Graceful shutdown: 새 acquire 거부 → BUSY 대기 → CLEARING 취소 → 종료."""
        self._draining = True

        grace_timeout = self._get_config_val("grace_timeout", 30.0)

        # 1. BUSY 슬롯 대기 (grace_timeout)
        try:
            await asyncio.wait_for(
                self._wait_all_idle_or_dead(),
                timeout=grace_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] drain grace_timeout 초과, 강제 종료", self._pool_name,
            )

        # 2. 남은 background clear 태스크 취소
        for task in list(self._clear_tasks.values()):
            if not task.done():
                task.cancel()
        if self._clear_tasks:
            await asyncio.gather(*self._clear_tasks.values(), return_exceptions=True)
        self._clear_tasks.clear()

        # 3. clearing monitor 종료
        if self._clearing_monitor_task and not self._clearing_monitor_task.done():
            self._clearing_monitor_task.cancel()
            try:
                await self._clearing_monitor_task
            except asyncio.CancelledError:
                pass

        # 4. shrink loop 종료
        if self._shrink_task and not self._shrink_task.done():
            self._shrink_task.cancel()
            try:
                await self._shrink_task
            except asyncio.CancelledError:
                pass

        # 5. 모든 슬롯 DEAD로 전이
        for slot_id in list(self._slots.keys()):
            self._force_dead(slot_id)

        self._drain_event.set()

        # 이벤트 발행
        asyncio.ensure_future(self._event_bus.emit("pool_drained"))

        # 대기 중인 acquire를 깨워서 RuntimeError를 받게 함
        self._idle_event.set()

    async def _wait_all_idle_or_dead(self) -> None:
        """모든 슬롯이 IDLE 또는 DEAD가 될 때까지 대기."""
        while any(
            s.state in (SlotState.BUSY, SlotState.CLEARING)
            for s in self._slots.values()
        ):
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        """현재 풀 상태를 슬롯 상태별 카운트로 반환한다.

        조회 전 Manager와 상태를 동기화하여 정확한 결과를 보장한다.

        Returns:
            {"idle": N, "busy": N, "clearing": N, "dead": N}
        """
        self.sync_all_slots()
        return {
            state.value: sum(1 for s in self._slots.values() if s.state == state)
            for state in SlotState
        }

    def stats(self) -> Any:
        """현재 풀 상태 스냅샷 반환 (PoolStats).

        PoolStats 타입이 아직 없으면 dict fallback.
        """
        self.sync_all_slots()
        counts: dict[str, int] = {"idle": 0, "busy": 0, "clearing": 0, "dead": 0}
        for s in self._slots.values():
            counts[s.state.value] = counts.get(s.state.value, 0) + 1

        # PoolStats import 시도 (다른 에이전트가 models.py에 추가 예정)
        try:
            from .models import PoolStats
            return PoolStats(
                idle=counts["idle"],
                busy=counts["busy"],
                clearing=counts["clearing"],
                dead=counts["dead"],
                total=len(self._slots),
                pool_name=self._pool_name,
                uptime_seconds=time.time() - self._created_at,
                last_activity_at=max(
                    (s.last_transition_at for s in self._slots.values()),
                    default=0,
                ),
            )
        except (ImportError, TypeError):
            # PoolStats 미구현 시 dict fallback
            return {
                **counts,
                "total": len(self._slots),
                "pool_name": self._pool_name,
                "uptime_seconds": round(time.time() - self._created_at, 1),
                "last_activity_at": max(
                    (s.last_transition_at for s in self._slots.values()),
                    default=0,
                ),
            }

    def get_slot_states(self) -> dict[str, str]:
        """각 슬롯의 현재 상태를 반환한다.

        조회 전 Manager와 상태를 동기화하여 정확한 결과를 보장한다.

        Returns:
            {"pool_0": "idle", "pool_1": "busy", ...}
        """
        self.sync_all_slots()
        return {sid: slot.state.value for sid, slot in self._slots.items()}

    def get_slot_details(self) -> list[dict[str, Any]]:
        """각 슬롯의 상태 + 에러 정보를 반환한다 (디버깅/API 노출용).

        Returns:
            [{"id": "pool_0", "state": "dead", "generation": 3, "last_error": {...}}, ...]
        """
        self.sync_all_slots()
        details = []
        for sid, slot in self._slots.items():
            entry: dict[str, Any] = {
                "id": sid,
                "state": slot.state.value,
                "generation": slot.generation,
                "last_transition_at": slot.last_transition_at,
            }
            if slot.state == SlotState.DEAD and sid in self._slot_errors:
                entry["last_error"] = self._slot_errors[sid]
            details.append(entry)
        return details

    # ------------------------------------------------------------------
    # 런타임 관리: resize, kill_slot, get_resource_usage
    # ------------------------------------------------------------------

    async def resize(self, new_size: int) -> dict:
        """풀 크기를 런타임에 변경한다.

        new_size > current: 새 슬롯 추가 (SlotInfo 생성 + _replenish_slot으로 프로세스 스폰)
        new_size < current: IDLE 슬롯부터 제거 (BUSY는 건드리지 않음)
        new_size == current: no-op

        Args:
            new_size: 변경할 풀 크기

        Returns:
            {"old_size": N, "new_size": N, "added": N, "removed": N}

        Raises:
            ValueError: new_size < 1
        """
        if new_size < 1:
            raise ValueError(f"new_size must be >= 1, got {new_size}")

        old_size = self._pool_size
        if new_size == old_size:
            return {"old_size": old_size, "new_size": new_size, "added": 0, "removed": 0}

        added = 0
        removed = 0

        if new_size > old_size:
            # 슬롯 추가
            for i in range(old_size, new_size):
                slot_id = f"pool_{i}"
                # 이미 있는 ID면 충돌 방지
                while slot_id in self._slots:
                    i += 1
                    slot_id = f"pool_{i}"
                self._slots[slot_id] = SlotInfo(
                    slot_id=slot_id,
                    state=SlotState.IDLE,
                    generation=0,
                    last_transition_at=time.time(),
                )
                added += 1
                logger.info("[%s] resize: 슬롯 추가 %s", self._pool_name, slot_id)
            self._idle_event.set()
        else:
            # 슬롯 제거 (IDLE 우선)
            to_remove = old_size - new_size
            removed_ids: list[str] = []

            # 1차: IDLE 슬롯 제거
            for slot_id in list(self._slots.keys()):
                if len(removed_ids) >= to_remove:
                    break
                slot = self._slots[slot_id]
                if slot.state == SlotState.IDLE:
                    removed_ids.append(slot_id)

            # 2차: DEAD 슬롯 제거 (IDLE이 부족하면)
            for slot_id in list(self._slots.keys()):
                if len(removed_ids) >= to_remove:
                    break
                slot = self._slots[slot_id]
                if slot.state == SlotState.DEAD and slot_id not in removed_ids:
                    removed_ids.append(slot_id)

            for slot_id in removed_ids:
                del self._slots[slot_id]
                self._slot_errors.pop(slot_id, None)
                removed += 1
                logger.info("[%s] resize: 슬롯 제거 %s", self._pool_name, slot_id)

            # IDLE 슬롯이 남아있는지 확인
            if not any(s.state == SlotState.IDLE for s in self._slots.values()):
                self._idle_event.clear()

        self._pool_size = new_size
        return {"old_size": old_size, "new_size": new_size, "added": added, "removed": removed}

    async def kill_slot(self, slot_id: str) -> dict:
        """특정 슬롯의 프로세스를 강제 종료하고 새 프로세스로 교체한다.

        BUSY 상태여도 강제 종료 가능 (사용자가 명시적으로 요청한 것이므로).

        Args:
            slot_id: 종료할 슬롯 ID

        Returns:
            {"slot_id": str, "old_pid": int|None, "new_pid": int|None, "success": bool}

        Raises:
            KeyError: 존재하지 않는 slot_id
        """
        if slot_id not in self._slots:
            raise KeyError(f"Unknown slot_id: {slot_id}")

        # 현재 PID 기록
        old_pid = None
        daemon = self._manager.get_daemon(self._daemon_type, slot_id)
        if daemon is not None:
            old_pid = daemon.pid

        # 강제 DEAD 전이
        self._force_dead(slot_id)

        # 프로세스 종료
        try:
            await self._manager.shutdown_daemon(
                self._daemon_type, slot_id, "manual_kill"
            )
        except Exception as e:
            logger.warning(
                "[%s] kill_slot shutdown 실패: slot=%s, error=%s",
                self._pool_name, slot_id, e,
            )

        # 새 프로세스 스폰
        success = await self._replenish_slot(slot_id)

        # 새 PID 확인
        new_pid = None
        new_daemon = self._manager.get_daemon(self._daemon_type, slot_id)
        if new_daemon is not None:
            new_pid = new_daemon.pid

        return {
            "slot_id": slot_id,
            "old_pid": old_pid,
            "new_pid": new_pid,
            "success": success,
        }

    def get_resource_usage(self) -> dict:
        """풀의 모든 프로세스 + 시스템 전체 리소스 사용량을 반환한다.

        psutil이 없으면 빈 dict를 반환한다 (graceful degradation).

        Returns:
            {
                "system": {"cpu_percent": float, "memory_total_mb": float,
                           "memory_used_mb": float, "memory_percent": float},
                "pool_processes": [{"slot_id": str, "pid": int, "cpu_percent": float,
                                    "memory_mb": float, "state": str}],
                "pool_total": {"cpu_percent": float, "memory_mb": float}
            }
        """
        try:
            import psutil
        except ImportError:
            return {}

        # 시스템 전체
        vm = psutil.virtual_memory()
        system_info = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_total_mb": round(vm.total / (1024 * 1024), 1),
            "memory_used_mb": round(vm.used / (1024 * 1024), 1),
            "memory_percent": vm.percent,
        }

        # 풀 프로세스별
        pool_processes: list[dict] = []
        total_cpu = 0.0
        total_mem = 0.0

        for slot_id, slot in self._slots.items():
            daemon = self._manager.get_daemon(self._daemon_type, slot_id)
            if daemon is None or daemon.pid is None:
                continue
            try:
                proc = psutil.Process(daemon.pid)
                cpu = proc.cpu_percent(interval=0.05)
                mem_info = proc.memory_info()
                mem_mb = round(mem_info.rss / (1024 * 1024), 1)
                pool_processes.append({
                    "slot_id": slot_id,
                    "pid": daemon.pid,
                    "cpu_percent": cpu,
                    "memory_mb": mem_mb,
                    "state": slot.state.value,
                })
                total_cpu += cpu
                total_mem += mem_mb
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pool_processes.append({
                    "slot_id": slot_id,
                    "pid": daemon.pid,
                    "cpu_percent": 0.0,
                    "memory_mb": 0.0,
                    "state": slot.state.value,
                    "error": "process_not_accessible",
                })

        return {
            "system": system_info,
            "pool_processes": pool_processes,
            "pool_total": {
                "cpu_percent": round(total_cpu, 1),
                "memory_mb": round(total_mem, 1),
            },
        }

    @property
    def pool_size(self) -> int:
        """풀 크기."""
        return self._pool_size

    @property
    def has_idle(self) -> bool:
        """IDLE 슬롯이 존재하는지 여부."""
        return any(s.state == SlotState.IDLE for s in self._slots.values())

    @property
    def events(self) -> PoolEventBus:
        """이벤트 버스."""
        return self._event_bus

    # ------------------------------------------------------------------
    # P1-1: Dynamic Pool (ELASTIC 모드)
    # ------------------------------------------------------------------

    async def _maybe_scale_up(self) -> str | None:
        """ELASTIC 모드: IDLE 슬롯이 min_spare 미만이면 새 슬롯 추가.

        Returns:
            새로 추가된 슬롯 ID, 또는 None (추가 불가)
        """
        pool_mode = self._get_config_val("pool_mode", None)
        if pool_mode is None or getattr(pool_mode, "value", pool_mode) != "elastic":
            return None

        max_pool_size = self._get_config_val("max_pool_size", 0)
        if max_pool_size > 0 and len(self._slots) >= max_pool_size:
            return None

        min_spare = self._get_config_val("min_spare", 0)
        idle_count = sum(1 for s in self._slots.values() if s.state == SlotState.IDLE)
        if idle_count >= min_spare:
            return None

        new_slot_id = f"{self._pool_name}_{len(self._slots)}"
        self._slots[new_slot_id] = SlotInfo(
            slot_id=new_slot_id,
            state=SlotState.IDLE,
            generation=0,
            last_transition_at=time.time(),
        )
        logger.info(
            "[%s] ELASTIC scale-up: %s (total=%d)",
            self._pool_name, new_slot_id, len(self._slots),
        )
        # 이벤트 발행
        asyncio.ensure_future(
            self._event_bus.emit("pool_scaled_up", slot_id=new_slot_id,
                                total=len(self._slots))
        )
        return new_slot_id

    async def _shrink_loop(self) -> None:
        """ELASTIC 모드: shrink_idle_timeout 초과 IDLE 슬롯 축소.

        pool_size 미만으로는 안 줄임.
        """
        while not self._draining and not self._shutting_down:
            try:
                await asyncio.sleep(60.0)  # 1분마다 체크
            except asyncio.CancelledError:
                return

            pool_mode = self._get_config_val("pool_mode", None)
            if pool_mode is None or getattr(pool_mode, "value", pool_mode) != "elastic":
                continue

            shrink_idle_timeout = self._get_config_val("shrink_idle_timeout", 300.0)
            now = time.time()
            removable: list[str] = []

            for slot_id, slot in list(self._slots.items()):
                if (
                    slot.state == SlotState.IDLE
                    and len(self._slots) - len(removable) > self._pool_size
                    and now - slot.last_transition_at > shrink_idle_timeout
                ):
                    removable.append(slot_id)

            for slot_id in removable:
                slot = self._slots.get(slot_id)
                if slot is None:
                    continue
                # CAS: IDLE -> DEAD (shrink)
                if self._cas_transition(
                    slot_id, SlotState.IDLE, slot.generation, SlotState.DEAD
                ):
                    del self._slots[slot_id]
                    logger.info(
                        "[%s] ELASTIC shrink: %s (total=%d)",
                        self._pool_name, slot_id, len(self._slots),
                    )
                    # 이벤트 발행
                    asyncio.ensure_future(
                        self._event_bus.emit("pool_scaled_down", slot_id=slot_id,
                                            total=len(self._slots))
                    )

    # ------------------------------------------------------------------
    # P1-5: Batch Replace
    # ------------------------------------------------------------------

    async def batch_replace(self, dead_slot_ids: list[str]) -> dict[str, bool]:
        """여러 DEAD 슬롯을 병렬 교체. Semaphore로 동시 spawn 제한.

        Args:
            dead_slot_ids: 교체할 DEAD 슬롯 ID 리스트

        Returns:
            {slot_id: 성공여부} 딕셔너리
        """
        tasks: dict[str, asyncio.Task] = {}
        for slot_id in dead_slot_ids:
            slot = self._slots.get(slot_id)
            if slot and slot.state == SlotState.DEAD:
                tasks[slot_id] = asyncio.create_task(self._replenish_slot(slot_id))

        results: dict[str, bool] = {}
        for slot_id, task in tasks.items():
            try:
                results[slot_id] = await task
            except Exception:
                results[slot_id] = False
        return results

    # ------------------------------------------------------------------
    # 정리
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """풀의 모든 백그라운드 태스크를 취소하고 BUSY 슬롯을 정리한다.

        drain()을 호출하여 graceful shutdown을 수행한다.

        1. drain 모드 진입 → 새 acquire 차단
        2. BUSY 슬롯 완료 대기 (grace_timeout)
        3. 백그라운드 /clear 태스크 취소
        4. BUSY 슬롯의 프로세스에 graceful shutdown 시도
        5. 대기 중인 acquire를 깨워서 RuntimeError를 받게 함
        """
        self._shutting_down = True

        # BUSY 슬롯의 프로세스에 graceful shutdown
        for slot_id, slot in self._slots.items():
            if slot.state == SlotState.BUSY:
                try:
                    await self._manager.shutdown_daemon(
                        self._daemon_type, slot_id, "pool_shutdown"
                    )
                    logger.info("[%s] BUSY 슬롯 shutdown 완료: slot=%s",
                                self._pool_name, slot_id)
                except Exception as e:
                    logger.warning("[%s] BUSY 슬롯 shutdown 실패: slot=%s, error=%s",
                                   self._pool_name, slot_id, e)
                self._force_dead(slot_id)

        # 백그라운드 /clear 태스크 취소
        for task in self._clear_tasks.values():
            if not task.done():
                task.cancel()

        if self._clear_tasks:
            await asyncio.gather(*self._clear_tasks.values(), return_exceptions=True)
        self._clear_tasks.clear()

        # clearing monitor 종료
        if self._clearing_monitor_task and not self._clearing_monitor_task.done():
            self._clearing_monitor_task.cancel()
            try:
                await self._clearing_monitor_task
            except asyncio.CancelledError:
                pass

        # shrink loop 종료
        if self._shrink_task and not self._shrink_task.done():
            self._shrink_task.cancel()
            try:
                await self._shrink_task
            except asyncio.CancelledError:
                pass

        # 나머지 슬롯도 DEAD로 전이
        for slot_id in list(self._slots.keys()):
            self._force_dead(slot_id)

        # 대기 중인 acquire를 깨워서 RuntimeError를 받게 함
        self._idle_event.set()

    # ------------------------------------------------------------------
    # 진단 유틸리티
    # ------------------------------------------------------------------

    def _collect_process_diagnostics(
        self, slot_id: str, daemon: Any = None,
    ) -> dict[str, Any]:
        """죽은 프로세스의 진단 정보를 수집한다.

        Args:
            slot_id: 슬롯 ID
            daemon: DaemonProcess 인스턴스 (없으면 Manager에서 조회 시도)

        Returns:
            {"slot_id", "pid", "exit_code", "uptime", "stderr_tail", "reason", "timestamp"}
        """
        diag: dict[str, Any] = {
            "slot_id": slot_id,
            "timestamp": time.time(),
        }

        if daemon is None:
            # Manager 인스턴스에서 직접 조회 (get_daemon은 alive만 반환하므로)
            instances = self._manager._instances.get(self._daemon_type, {})
            daemon = instances.get(slot_id)

        if daemon is None:
            diag["reason"] = "daemon_not_found"
            diag["pid"] = None
            diag["exit_code"] = None
            diag["uptime"] = 0
            diag["stderr_tail"] = "N/A"
            return diag

        proc = daemon.process
        diag["pid"] = proc.pid
        diag["exit_code"] = proc.returncode
        diag["uptime"] = round(time.time() - daemon.created_at, 1)

        # stderr에서 마지막 메시지 수집 (non-blocking)
        stderr_text = ""
        try:
            if proc.stderr and not proc.stderr.at_eof():
                # 이미 죽은 프로세스이므로 남은 stderr를 즉시 읽을 수 있음
                raw = proc.stderr._buffer if hasattr(proc.stderr, "_buffer") else b""
                if raw:
                    stderr_text = bytes(raw).decode("utf-8", errors="replace").strip()
        except Exception:
            pass

        # stderr가 비었으면 "정보 없음"
        diag["stderr_tail"] = stderr_text[-500:] if stderr_text else "(stderr 비어있음)"
        return diag

    def _mark_slot_dead(
        self, slot_id: str, reason: str, daemon: Any = None,
    ) -> None:
        """슬롯을 DEAD로 전환하고 에러 정보를 기록한다."""
        self._force_dead(slot_id)
        diag = self._collect_process_diagnostics(slot_id, daemon)
        diag["reason"] = reason
        self._slot_errors[slot_id] = diag

        slot = self._slots.get(slot_id)
        if slot:
            slot.error_info = reason

        logger.warning(
            "[%s] 슬롯 DEAD 전환: slot=%s, reason=%s, "
            "exit_code=%s, pid=%s, stderr=%s",
            self._pool_name, slot_id, reason,
            diag.get("exit_code", "?"),
            diag.get("pid", "?"),
            diag.get("stderr_tail", "N/A"),
        )

        # 이벤트 발행
        asyncio.ensure_future(
            self._event_bus.emit("slot_dead", slot_id=slot_id, error=reason)
        )

    def _build_all_dead_error(self) -> str:
        """모든 슬롯 DEAD일 때 상세 에러 메시지를 구성한다."""
        parts = []
        for slot_id in sorted(self._slots.keys()):
            err = self._slot_errors.get(slot_id, {})
            reason = err.get("reason", "unknown")
            exit_code = err.get("exit_code", "?")
            pid = err.get("pid", "?")
            stderr = err.get("stderr_tail", "N/A")
            parts.append(
                f"  {slot_id}: reason={reason}, exit_code={exit_code}, "
                f"pid={pid}, stderr={stderr}"
            )
        return "slot diagnostics:\n" + "\n".join(parts)

    def _build_slot_summary(self) -> str:
        """현재 슬롯 상태 요약 (acquire 타임아웃 진단용)."""
        parts = []
        now = time.time()
        for slot_id in sorted(self._slots.keys()):
            slot = self._slots[slot_id]
            elapsed = now - slot.last_transition_at
            parts.append(f"{slot_id}={slot.state.value}({elapsed:.0f}s)")
        return ", ".join(parts)


# ======================================================================
# P1-3: BatchProcessor (배치 작업 어댑터)
# ======================================================================

class BatchProcessor:
    """풀 기반 배치 처리 어댑터.

    여러 요청 항목을 풀의 슬롯을 통해 병렬 처리한다.
    Semaphore로 동시 처리 수를 제한하고, 각 항목의 성공/실패를 개별 추적한다.

    NOTE: 100건 이상의 대규모 배치는 별도 큐 시스템(Redis, RabbitMQ)을 권장.
    이 어댑터는 풀 위에 간단한 세마포어를 올려 소규모 배치를 처리한다.

    Usage::

        processor = BatchProcessor(pool, max_concurrent=3)
        results = await processor.process(
            items=["prompt1", "prompt2", "prompt3"],
            handler=my_handler,
            on_progress=lambda done, total: print(f"{done}/{total}"),
        )

    Args:
        pool: DaemonPool 인스턴스
        max_concurrent: 동시 처리 상한. None이면 풀 크기만큼.
    """

    def __init__(
        self,
        pool: "DaemonPool",
        max_concurrent: int | None = None,
    ) -> None:
        self._pool = pool
        self._max_concurrent = max_concurrent or pool.pool_size

    async def process(
        self,
        items: list,
        handler: Callable,
        on_progress: Callable[[int, int], None] | None = None,
        on_error: Callable | None = None,
    ) -> list[dict]:
        """items를 병렬 배치 처리한다.

        각 item에 대해 슬롯을 획득하고 handler를 실행한 뒤 반환한다.
        결과 순서는 입력 items 순서와 동일하다.

        Args:
            items:       처리할 항목 리스트
            handler:     (slot_id, item) -> result 형태의 async callable
            on_progress: (completed_count, total_count) 진행 콜백 (선택)
            on_error:    (item, exception) 에러 콜백 (선택)

        Returns:
            [{"item": item, "result": result, "error": error_str | None}, ...]
        """
        semaphore = asyncio.Semaphore(self._max_concurrent)
        results: list[dict | None] = [None] * len(items)
        completed = 0

        async def _process_one(idx: int, item: object) -> None:
            nonlocal completed
            async with semaphore:
                async with self._pool.slot() as slot_id:
                    try:
                        result = await handler(slot_id, item)
                        results[idx] = {
                            "item": item,
                            "result": result,
                            "error": None,
                        }
                    except Exception as e:
                        results[idx] = {
                            "item": item,
                            "result": None,
                            "error": str(e),
                        }
                        if on_error:
                            try:
                                coro = on_error(item, e)
                                if asyncio.iscoroutine(coro):
                                    await coro
                            except Exception:
                                pass
                    finally:
                        completed += 1
                        if on_progress:
                            on_progress(completed, len(items))

        tasks = [
            asyncio.create_task(_process_one(i, item))
            for i, item in enumerate(items)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results  # type: ignore[return-value]
