"""
프로세스 런타임 상태 모델.

DaemonProcess  : 내부 관리용 (asyncio.subprocess.Process 참조 포함)
DaemonStatus   : 외부 노출용 직렬화 안전 스냅샷 (JSON 변환 가능)
ProcessState   : 프로세스 생명주기 상태 열거형
PoolStats      : 풀 상태 스냅샷 (P0-6)
PoolEvent      : 풀 운영 이벤트 열거형 (P1-4)
"""

import asyncio
import time
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Optional


class ProcessState(str, Enum):
    """프로세스 생명주기 상태.

    STARTING      : 프로세스 생성 직후, 아직 요청을 받을 수 없는 단계
    IDLE          : 요청 대기 중 (유휴)
    BUSY          : 요청 처리 중
    CLEARING      : /clear 진행 중 (백그라운드, 새 요청 불가)
    SHUTTING_DOWN : 종료 시퀀스 진행 중 (SIGTERM 전송됨)
    DEAD          : 프로세스 종료 완료
    """

    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    CLEARING = "clearing"
    SHUTTING_DOWN = "shutting_down"
    DEAD = "dead"


@dataclass
class DaemonProcess:
    """내부 관리용 프로세스 상태.

    asyncio.subprocess.Process 참조를 직접 갖고 있어서
    프로세스 제어(stdin/stdout, signal 등)에 사용한다.

    Attributes:
        instance_id:    인스턴스 식별자 (예: user_id, 세션 키 등)
        daemon_type:    데몬 타입 식별자 (DaemonConfig.daemon_type과 대응)
        process:        asyncio 서브프로세스 핸들
        state:          현재 프로세스 상태
        created_at:     프로세스 생성 시각 (Unix timestamp)
        last_active_at: 마지막 활동 시각 (Unix timestamp)
        restart_count:  자동 재시작 누적 횟수
        metadata:       구현체별 추가 데이터 (세션 ID 등)
        _idle_task:     유휴 타임아웃 asyncio.Task (내부 전용)
    """

    instance_id: str
    daemon_type: str
    process: asyncio.subprocess.Process
    state: ProcessState = ProcessState.STARTING
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    restart_count: int = 0
    metadata: dict = field(default_factory=dict)
    _idle_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # --- 읽기 전용 프로퍼티 ---

    @property
    def is_alive(self) -> bool:
        """프로세스가 아직 실행 중인지 여부."""
        return self.process.returncode is None

    @property
    def pid(self) -> Optional[int]:
        """프로세스 PID. 아직 시작되지 않았으면 None."""
        return self.process.pid

    @property
    def uptime(self) -> float:
        """프로세스 생성 후 경과 시간(초)."""
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        """마지막 활동 이후 경과 시간(초)."""
        return time.time() - self.last_active_at

    def to_status(self) -> "DaemonStatus":
        """외부 노출용 DaemonStatus 스냅샷 생성."""
        return DaemonStatus(
            instance_id=self.instance_id,
            daemon_type=self.daemon_type,
            pid=self.pid or -1,
            state=self.state.value,
            alive=self.is_alive,
            uptime=round(self.uptime, 1),
            idle=round(self.idle_seconds, 1),
            restart_count=self.restart_count,
            metadata=dict(self.metadata),
        )


@dataclass
class DaemonStatus:
    """외부 노출용 직렬화 안전 스냅샷.

    asyncio.subprocess.Process 같은 직렬화 불가 객체를 포함하지 않으며,
    JSON 변환이나 API 응답에 안전하게 사용할 수 있다.

    Attributes:
        instance_id:    인스턴스 식별자
        daemon_type:    데몬 타입 식별자
        pid:            프로세스 PID (-1이면 미시작)
        state:          프로세스 상태 문자열
        alive:          프로세스 생존 여부
        uptime:         가동 시간(초)
        idle:           유휴 시간(초)
        restart_count:  재시작 누적 횟수
        metadata:       구현체별 추가 데이터
    """

    instance_id: str
    daemon_type: str
    pid: int
    state: str
    alive: bool
    uptime: float
    idle: float
    restart_count: int
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# P0-6: PoolStats — 풀 상태 스냅샷
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoolStats:
    """풀 상태의 불변 스냅샷.

    pool.stats() 호출 시 현재 상태를 캡처하여 반환한다.
    frozen=True이므로 반환 후 변조 불가.

    Attributes:
        idle:               유휴 슬롯 수
        busy:               사용 중 슬롯 수
        clearing:           /clear 진행 중 슬롯 수
        dead:               DEAD 슬롯 수
        total:              전체 슬롯 수
        pool_name:          풀 이름
        uptime_seconds:     풀 가동 시간(초)
        last_activity_at:   마지막 활동 시각 (Unix timestamp)
    """

    idle: int
    busy: int
    clearing: int
    dead: int
    total: int
    pool_name: str
    uptime_seconds: float
    last_activity_at: float  # Unix timestamp

    def to_dict(self) -> dict:
        """직렬화 안전 딕셔너리로 변환."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ---------------------------------------------------------------------------
# P1-4: PoolEvent — 풀 운영 이벤트
# ---------------------------------------------------------------------------

class PoolEvent(str, Enum):
    """풀에서 발생하는 운영 이벤트.

    EventBus를 통해 외부 핸들러에 전달된다.

    Values:
        SLOT_ACQUIRED     : 슬롯 획득 (acquire 성공)
        SLOT_RELEASED     : 슬롯 반환 (release → CLEARING 진입)
        SLOT_DEAD         : 슬롯 DEAD 전환
        SLOT_REPLACED     : DEAD 슬롯 교체 완료
        POOL_DRAINED      : 풀 drain 모드 진입 (shutdown 시작)
        CLEARING_TIMEOUT  : CLEARING 타임아웃으로 DEAD 전환
        REPLENISH_START   : DEAD 교체 시작
        REPLENISH_END     : DEAD 교체 완료 (성공/실패 무관)
        POOL_SCALED_UP    : ELASTIC 모드 — 풀 확장
        POOL_SCALED_DOWN  : ELASTIC 모드 — 풀 축소
    """

    SLOT_ACQUIRED = "slot_acquired"
    SLOT_RELEASED = "slot_released"
    SLOT_DEAD = "slot_dead"
    SLOT_REPLACED = "slot_replaced"
    POOL_DRAINED = "pool_drained"
    CLEARING_TIMEOUT = "clearing_timeout"
    REPLENISH_START = "replenish_start"
    REPLENISH_END = "replenish_end"
    POOL_SCALED_UP = "pool_scaled_up"
    POOL_SCALED_DOWN = "pool_scaled_down"
