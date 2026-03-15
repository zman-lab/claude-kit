"""
데몬 인스턴스 중앙 관리자 + 용도별 풀 라우터.

DaemonManager:
    여러 종류의 BaseDaemon 구현체를 타입별로 등록하고,
    (daemon_type, instance_id) 조합으로 인스턴스를 추적하며,
    전체 생명주기(생성·유휴 관리·종료)를 관리한다.

PoolManager (P1-2):
    여러 DaemonPool을 용도별(chat/tool/command 등)로 등록하고,
    이름 기반 라우팅으로 요청을 적합한 풀에 분배한다.
    각 풀은 독립적인 설정과 슬롯을 가지며, 상호 간섭하지 않는다.

의존성 분리 (원본 대비 변경사항):
    - get_daemon_manager() 싱글톤 제거 → 호출 프로젝트에서 직접 생성
    - get_settings() 자동 등록 제거 → 호출 프로젝트에서 명시적 register()
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from .base import BaseDaemon
from .models import DaemonProcess, DaemonStatus, PoolStats, ProcessState

if TYPE_CHECKING:
    from .pool import DaemonPool

logger = logging.getLogger(__name__)


class DaemonManager:
    """
    데몬 인스턴스 중앙 관리자.

    - 여러 BaseDaemon 구현체를 타입별로 등록
    - (daemon_type, instance_id) 조합으로 인스턴스 추적
    - 인스턴스별 asyncio.Lock으로 동시 요청 방지
    - 전체/타입별/인스턴스별 생명주기 관리
    """

    def __init__(self, max_instances: int = 10):
        self._daemon_impls: dict[str, BaseDaemon] = {}            # daemon_type -> BaseDaemon
        self._instances: dict[str, dict[str, DaemonProcess]] = {} # daemon_type -> {instance_id -> DaemonProcess}
        self._locks: dict[str, asyncio.Lock] = {}                 # "type:instance_id" -> Lock
        self._max_instances = max_instances                        # 타입별 최대 인스턴스 수

    # ------------------------------------------------------------------
    # 데몬 타입 등록
    # ------------------------------------------------------------------

    def register(self, daemon: BaseDaemon) -> None:
        """BaseDaemon 구현체를 타입 이름으로 등록한다.

        동일한 daemon_type을 중복 등록하면 기존 구현체를 덮어쓴다.
        """
        daemon_type = daemon.config.daemon_type
        self._daemon_impls[daemon_type] = daemon
        self._instances.setdefault(daemon_type, {})
        logger.info("[%s] 데몬 타입 등록 완료", daemon_type)

    def get_impl(self, daemon_type: str) -> BaseDaemon:
        """등록된 BaseDaemon 구현체를 반환한다.

        Raises:
            KeyError: 등록되지 않은 데몬 타입
        """
        try:
            return self._daemon_impls[daemon_type]
        except KeyError:
            raise KeyError(
                f"등록되지 않은 데몬 타입: '{daemon_type}' "
                f"(등록된 타입: {list(self._daemon_impls.keys())})"
            )

    # ------------------------------------------------------------------
    # 인스턴스 관리
    # ------------------------------------------------------------------

    def _get_lock(self, daemon_type: str, instance_id: str) -> asyncio.Lock:
        """(daemon_type, instance_id) 조합에 대한 Lock 반환 (없으면 생성)."""
        key = f"{daemon_type}:{instance_id}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def get_daemon(
        self, daemon_type: str, instance_id: str
    ) -> Optional[DaemonProcess]:
        """살아있는 인스턴스를 반환한다. 없거나 죽었으면 None.

        DaemonPool에서 /clear 대상 조회에 사용된다.
        ensure_daemon과 달리 새로 생성하지 않는다.
        """
        instances = self._instances.get(daemon_type, {})
        daemon = instances.get(instance_id)
        if daemon and daemon.is_alive:
            return daemon
        return None

    async def ensure_daemon(
        self, daemon_type: str, instance_id: str
    ) -> DaemonProcess:
        """살아있는 인스턴스를 반환한다. 없거나 죽었으면 새로 생성하고 유휴 타이머를 시작한다.

        Args:
            daemon_type:  등록된 데몬 타입 이름
            instance_id:  인스턴스 식별자 (예: user_id)

        Returns:
            DaemonProcess: 사용 가능한 인스턴스

        Raises:
            KeyError: 등록되지 않은 데몬 타입
        """
        impl = self.get_impl(daemon_type)
        instances = self._instances[daemon_type]

        daemon = instances.get(instance_id)
        if daemon and daemon.is_alive:
            return daemon

        # 죽은 인스턴스가 남아있으면 정리
        if daemon:
            logger.warning(
                "[%s] 프로세스 죽음 감지, 재생성: instance_id=%s",
                daemon_type, instance_id,
            )
            self._cleanup_dead(daemon_type, instance_id)

        # 인스턴스 수 제한 체크: 초과 시 가장 오래된 idle 인스턴스 종료
        alive_instances = {
            iid: d for iid, d in instances.items() if d.is_alive
        }
        if len(alive_instances) >= self._max_instances:
            idle_candidates = [
                (iid, d) for iid, d in alive_instances.items()
                if d.state == ProcessState.IDLE
            ]
            if idle_candidates:
                oldest_iid, _ = min(idle_candidates, key=lambda x: x[1].created_at)
                logger.warning(
                    "[%s] 최대 인스턴스 수(%d) 도달, 가장 오래된 idle 종료: %s",
                    daemon_type, self._max_instances, oldest_iid,
                )
                await self.shutdown_daemon(daemon_type, oldest_iid, "max_instances_eviction")
            else:
                raise RuntimeError(
                    f"[{daemon_type}] 최대 인스턴스 수({self._max_instances}) 도달, "
                    f"idle 인스턴스 없어 새 인스턴스 생성 불가"
                )

        # 새 인스턴스 생성
        daemon = await impl.create_daemon(instance_id)
        instances[instance_id] = daemon
        logger.info(
            "[%s] 인스턴스 생성: instance_id=%s, pid=%s",
            daemon_type, instance_id, daemon.pid,
        )

        # 유휴 타이머 시작
        self._start_idle_timer(daemon_type, instance_id, impl, daemon)

        return daemon

    def _start_idle_timer(
        self,
        daemon_type: str,
        instance_id: str,
        impl: BaseDaemon,
        daemon: DaemonProcess,
    ) -> None:
        """유휴 타이머를 시작(또는 리셋)한다."""

        async def _on_idle_timeout(_instance_id: str) -> None:
            logger.info(
                "[%s] 유휴 타임아웃 도달: instance_id=%s (%ds)",
                daemon_type, _instance_id, impl.config.idle_timeout,
            )
            await self.shutdown_daemon(daemon_type, _instance_id, "idle_timeout")

        impl.start_idle_timer(daemon, _on_idle_timeout)

    async def shutdown_daemon(
        self, daemon_type: str, instance_id: str, reason: str = ""
    ) -> None:
        """특정 인스턴스를 정상 종료하고 내부 추적에서 제거한다."""
        instances = self._instances.get(daemon_type)
        if not instances:
            return

        daemon = instances.pop(instance_id, None)
        if not daemon:
            return

        impl = self._daemon_impls.get(daemon_type)
        if impl:
            impl.cancel_idle_timer(daemon)
            await impl.shutdown_process(daemon, reason)

        self._locks.pop(f"{daemon_type}:{instance_id}", None)

        logger.info(
            "[%s] 인스턴스 종료: instance_id=%s, reason=%s",
            daemon_type, instance_id, reason or "manual",
        )

    def _cleanup_dead(self, daemon_type: str, instance_id: str) -> None:
        """죽은 인스턴스를 내부 추적에서 제거한다 (프로세스 종료는 하지 않음)."""
        instances = self._instances.get(daemon_type)
        if not instances:
            return

        daemon = instances.pop(instance_id, None)
        if daemon:
            impl = self._daemon_impls.get(daemon_type)
            if impl:
                impl.cancel_idle_timer(daemon)

    async def cancel_request(
        self, daemon_type: str, instance_id: str
    ) -> bool:
        """현재 진행 중인 요청만 중단 (SIGINT). 프로세스 자체는 유지된다.

        Returns:
            True: SIGINT 전송 성공, False: 대상 없음 또는 전송 실패
        """
        impl = self._daemon_impls.get(daemon_type)
        if not impl:
            return False

        instances = self._instances.get(daemon_type, {})
        daemon = instances.get(instance_id)
        if not daemon:
            return False

        result = impl.cancel_request(daemon)
        if result:
            logger.info(
                "[%s] 요청 중단 (SIGINT): instance_id=%s, pid=%s",
                daemon_type, instance_id, daemon.pid,
            )
        return result

    # ------------------------------------------------------------------
    # 전체 관리
    # ------------------------------------------------------------------

    async def warmup_all(self) -> dict[str, int]:
        """등록된 모든 데몬 타입에 대해 워밍업을 실행한다.

        Returns:
            {daemon_type: 생성된 프로세스 수} 딕셔너리
        """
        results: dict[str, int] = {}
        for daemon_type, impl in self._daemon_impls.items():
            count = await impl.warmup()
            results[daemon_type] = count
            if count > 0:
                logger.info("[%s] 워밍업 완료: %d개 프로세스", daemon_type, count)
        return results

    async def shutdown_all(self) -> None:
        """모든 타입의 모든 인스턴스를 종료하고 워밍업 풀도 정리한다."""
        for daemon_type in list(self._instances.keys()):
            await self.shutdown_type(daemon_type)

        # 워밍업 풀 정리
        for daemon_type, impl in self._daemon_impls.items():
            await impl.cleanup_warm_pool()

        self._locks.clear()
        logger.info("모든 데몬 인스턴스 종료 완료")

    async def shutdown_type(self, daemon_type: str) -> None:
        """특정 타입의 모든 인스턴스를 종료한다."""
        instances = self._instances.get(daemon_type)
        if not instances:
            return

        instance_ids = list(instances.keys())
        for instance_id in instance_ids:
            await self.shutdown_daemon(daemon_type, instance_id, reason="type_shutdown")

        logger.info("[%s] 타입 전체 종료 완료 (%d개)", daemon_type, len(instance_ids))

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_status(self, daemon_type: Optional[str] = None) -> dict:
        """디버그용: 현재 데몬 상태 조회.

        Args:
            daemon_type: 특정 타입만 조회. None이면 전체 조회.

        Returns:
            {daemon_type: {instance_id: DaemonStatus.to_dict()}} 형태의 딕셔너리
        """
        target_types = (
            [daemon_type] if daemon_type else list(self._instances.keys())
        )

        result: dict[str, dict[str, dict]] = {}
        for dt in target_types:
            instances = self._instances.get(dt, {})
            impl = self._daemon_impls.get(dt)
            if not impl:
                continue

            type_status: dict[str, dict] = {}
            for iid, daemon in instances.items():
                status = impl.get_daemon_status(daemon)
                type_status[iid] = {
                    "instance_id": status.instance_id,
                    "daemon_type": status.daemon_type,
                    "pid": status.pid,
                    "state": status.state,
                    "alive": status.alive,
                    "uptime": status.uptime,
                    "idle": status.idle,
                    "restart_count": status.restart_count,
                    "metadata": status.metadata,
                }
            result[dt] = type_status

        return result

    @property
    def registered_types(self) -> list[str]:
        """등록된 데몬 타입 이름 목록."""
        return list(self._daemon_impls.keys())


# ======================================================================
# P1-2: PoolManager (용도별 풀 분리)
# ======================================================================

class PoolManager:
    """용도별 DaemonPool 중앙 관리.

    chat/tool/command 등 용도별로 독립 DaemonPool을 등록하고,
    이름 기반 라우팅으로 요청을 적합한 풀에 분배한다.

    DaemonManager와의 관계:
        - DaemonManager: 개별 프로세스의 생명주기 관리
        - PoolManager: 여러 풀의 라우팅 + 일괄 관리

    Usage::

        pm = PoolManager()
        pm.register_pool("chat", chat_pool)
        pm.register_pool("tool", tool_pool)
        pm.set_default("chat")

        pool = pm.get_pool("tool")  # tool 전용 풀
        pool = pm.get_pool()        # 기본(chat) 풀
    """

    def __init__(self) -> None:
        self._pools: dict[str, "DaemonPool"] = {}
        self._default_pool: str | None = None

    def register_pool(self, name: str, pool: "DaemonPool") -> None:
        """풀을 이름으로 등록한다.

        첫 번째 등록된 풀이 자동으로 기본 풀이 된다.
        동일 이름 중복 등록 시 ValueError를 발생시킨다.

        Args:
            name: 풀 이름 (예: "chat", "tool", "command")
            pool: DaemonPool 인스턴스

        Raises:
            ValueError: 이미 같은 이름의 풀이 등록된 경우
        """
        if name in self._pools:
            raise ValueError(f"Pool '{name}' already exists")
        self._pools[name] = pool
        if self._default_pool is None:
            self._default_pool = name
        logger.info("PoolManager: '%s' 풀 등록 완료 (total=%d)", name, len(self._pools))

    def get_pool(self, name: str | None = None) -> "DaemonPool":
        """이름으로 풀을 반환한다. None이면 기본 풀.

        Args:
            name: 풀 이름. None이면 기본 풀 반환.

        Returns:
            DaemonPool 인스턴스

        Raises:
            KeyError: 해당 이름의 풀이 없거나, 기본 풀이 설정되지 않은 경우
        """
        target = name or self._default_pool
        if target is None or target not in self._pools:
            raise KeyError(
                f"Pool '{target}' not found. "
                f"Available: {list(self._pools.keys())}"
            )
        return self._pools[target]

    def set_default(self, name: str) -> None:
        """기본 풀을 변경한다.

        Args:
            name: 기본 풀로 설정할 풀 이름

        Raises:
            KeyError: 등록되지 않은 풀 이름
        """
        if name not in self._pools:
            raise KeyError(
                f"Pool '{name}' not registered. "
                f"Available: {list(self._pools.keys())}"
            )
        self._default_pool = name

    def unregister_pool(self, name: str) -> "DaemonPool | None":
        """풀을 등록 해제한다.

        해제된 풀이 기본 풀이었으면, 남은 풀 중 첫 번째를 기본으로 승격한다.

        Args:
            name: 해제할 풀 이름

        Returns:
            해제된 DaemonPool 또는 None (해당 이름 없음)
        """
        pool = self._pools.pop(name, None)
        if name == self._default_pool:
            self._default_pool = next(iter(self._pools), None)
        return pool

    def list_pools(self) -> dict[str, dict]:
        """모든 풀의 상태 요약을 반환한다.

        Returns:
            {풀이름: {"is_default": bool, ...stats}} 형태의 딕셔너리
        """
        result: dict[str, dict] = {}
        for name, pool in self._pools.items():
            stats = pool.get_stats()
            result[name] = {
                "is_default": name == self._default_pool,
                **stats,
            }
        return result

    def stats_all(self) -> dict[str, PoolStats]:
        """모든 풀의 PoolStats를 반환한다.

        Returns:
            {풀이름: PoolStats} 딕셔너리
        """
        return {name: pool.stats() for name, pool in self._pools.items()}

    @property
    def pool_names(self) -> list[str]:
        """등록된 풀 이름 목록."""
        return list(self._pools.keys())

    @property
    def default_pool_name(self) -> str | None:
        """현재 기본 풀 이름. 등록된 풀이 없으면 None."""
        return self._default_pool

    async def shutdown_all(self) -> None:
        """모든 풀을 종료한다.

        각 풀의 shutdown()을 병렬 호출하고, 내부 상태를 초기화한다.
        """
        if not self._pools:
            return
        await asyncio.gather(
            *(pool.shutdown() for pool in self._pools.values()),
            return_exceptions=True,
        )
        logger.info("PoolManager: 모든 풀 종료 완료 (%d개)", len(self._pools))
        self._pools.clear()
        self._default_pool = None

    async def drain_all(self) -> None:
        """모든 풀을 drain 모드로 전환한다.

        각 풀의 drain()을 병렬 호출한다.
        """
        if not self._pools:
            return
        await asyncio.gather(
            *(pool.drain() for pool in self._pools.values()),
            return_exceptions=True,
        )
        logger.info("PoolManager: 모든 풀 drain 완료 (%d개)", len(self._pools))
