"""
데몬 타입별 불변 설정.

각 CLI 데몬(Claude, Codex 등)은 DaemonConfig 인스턴스 하나로 정의된다.
frozen=True 이므로 런타임에 설정값이 변경되지 않는다.

풀 관리 설정:
    PoolMode     : 풀 운영 모드 (FIXED / ELASTIC)
    PoolConfig   : 풀 전용 불변 설정 (프리셋 기반 생성 지원)
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# 풀 모드 열거형
# ---------------------------------------------------------------------------

class PoolMode(Enum):
    """풀 운영 모드.

    FIXED   : 고정 크기. 자동 확장/축소 없음.
    ELASTIC : min_pool_size ~ max_pool_size 범위 내 자동 조절.
    """

    FIXED = "fixed"
    ELASTIC = "elastic"


# ---------------------------------------------------------------------------
# 프리셋 정의
# ---------------------------------------------------------------------------

_PRESETS: dict[PoolMode, dict] = {
    PoolMode.FIXED: {
        "pool_size": 3,
        "min_pool_size": None,
        "max_pool_size": None,
        "min_spare": 0,
        "shrink_idle_timeout": None,
        "grace_timeout": 30.0,
        "clearing_timeout": 30.0,
        "max_concurrent_spawns": 2,
        "retry_delays": (1.0, 2.0, 4.0),
    },
    PoolMode.ELASTIC: {
        "pool_size": 3,
        "min_pool_size": 2,
        "max_pool_size": 8,
        "min_spare": 1,
        "shrink_idle_timeout": 300.0,
        "grace_timeout": 30.0,
        "clearing_timeout": 30.0,
        "max_concurrent_spawns": 2,
        "retry_delays": (1.0, 2.0, 4.0),
    },
}


# ---------------------------------------------------------------------------
# PoolConfig — 풀 전용 불변 설정
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoolConfig:
    """프로세스 풀 전용 설정.

    from_preset() 으로 프리셋 기반 생성을 권장한다.
    개별 파라미터 오버라이드도 가능.

    Attributes:
        mode:                  풀 운영 모드 (FIXED / ELASTIC)
        pool_size:             풀 크기 (FIXED: 고정값, ELASTIC: 초기값)
        min_pool_size:         ELASTIC 전용 — 최소 풀 크기
        max_pool_size:         ELASTIC 전용 — 최대 풀 크기
        min_spare:             ELASTIC 전용 — 최소 여유 슬롯 수
        grace_timeout:         shutdown 시 BUSY 슬롯 완료 대기(초)
        clearing_timeout:      CLEARING → DEAD 판정 타임아웃(초)
        shrink_idle_timeout:   ELASTIC 전용 — 유휴 슬롯 축소 전 대기(초)
        max_concurrent_spawns: 동시 프로세스 생성 상한
        retry_delays:          DEAD 교체 재시도 지수 백오프 딜레이(초)
    """

    # 모드
    mode: PoolMode = PoolMode.FIXED

    # 풀 크기
    pool_size: int = 3
    min_pool_size: Optional[int] = None     # ELASTIC 전용
    max_pool_size: Optional[int] = None     # ELASTIC 전용
    min_spare: int = 0                       # ELASTIC 전용

    # 타이밍
    grace_timeout: float = 30.0              # shutdown BUSY 대기
    clearing_timeout: float = 30.0           # CLEARING → DEAD 판정
    shrink_idle_timeout: Optional[float] = None  # ELASTIC 전용

    # 복구
    max_concurrent_spawns: int = 2           # 동시 spawn 상한
    retry_delays: Tuple[float, ...] = (1.0, 2.0, 4.0)

    def __post_init__(self) -> None:
        errors: list[str] = []

        if self.pool_size < 1:
            errors.append("pool_size >= 1")
        if self.max_concurrent_spawns < 1:
            errors.append("max_concurrent_spawns >= 1")
        if self.grace_timeout <= 0:
            errors.append("grace_timeout > 0")
        if self.clearing_timeout <= 0:
            errors.append("clearing_timeout > 0")

        if self.mode == PoolMode.ELASTIC:
            if self.min_pool_size is None or self.max_pool_size is None:
                errors.append("ELASTIC: min/max_pool_size 필수")
            elif self.min_pool_size > self.max_pool_size:
                errors.append("min_pool_size <= max_pool_size")
            if self.min_spare >= (self.max_pool_size or float("inf")):
                errors.append("min_spare < max_pool_size")
            if (self.shrink_idle_timeout is not None
                    and self.shrink_idle_timeout <= 0):
                errors.append("shrink_idle_timeout > 0")

        if self.mode == PoolMode.FIXED:
            if (self.min_pool_size is not None
                    or self.max_pool_size is not None):
                errors.append("FIXED: min/max_pool_size 설정 불가")

        if errors:
            raise ValueError(
                "PoolConfig 검증 실패:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    @classmethod
    def from_preset(cls, mode: PoolMode, **overrides) -> "PoolConfig":
        """프리셋 기반 생성 + 개별 오버라이드.

        Examples:
            PoolConfig.from_preset(PoolMode.FIXED)
            PoolConfig.from_preset(PoolMode.ELASTIC, pool_size=5)
        """
        preset = dict(_PRESETS[mode])
        preset["mode"] = mode
        preset.update(overrides)
        return cls(**preset)


def create_pool_config(mode: str, pool_size: int | None = None, **overrides) -> PoolConfig:
    """문자열 모드명으로 PoolConfig를 생성하는 편의 팩토리.

    pool_size가 None이면 환경변수 DAEMON_POOL_SIZE를 확인한다.
    환경변수도 없으면 프리셋 기본값(3)을 사용한다.

    Args:
        mode:       "fixed" 또는 "elastic"
        pool_size:  풀 크기. None이면 환경변수 또는 프리셋 기본값 사용.
        **overrides: PoolConfig 필드 오버라이드

    Returns:
        PoolConfig 인스턴스

    Raises:
        ValueError: 알 수 없는 모드명
    """
    if pool_size is None:
        env_pool_size = os.environ.get("DAEMON_POOL_SIZE")
        if env_pool_size is not None:
            pool_size = int(env_pool_size)
        else:
            pool_size = 3  # 프리셋 기본값
    mode_lower = mode.lower()
    if mode_lower == "fixed":
        pool_mode = PoolMode.FIXED
        overrides.setdefault("min_spare", 0)
        overrides.setdefault("max_pool_size", None)
        overrides.setdefault("min_pool_size", None)
    elif mode_lower == "elastic":
        pool_mode = PoolMode.ELASTIC
        overrides.setdefault("min_spare", 1)
        overrides.setdefault("max_pool_size", pool_size * 2)
        overrides.setdefault("min_pool_size", pool_size)
    else:
        raise ValueError(f"알 수 없는 풀 모드: '{mode}' (fixed 또는 elastic)")

    return PoolConfig.from_preset(pool_mode, pool_size=pool_size, **overrides)


# ---------------------------------------------------------------------------
# DaemonConfig — 데몬 타입별 불변 설정
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DaemonConfig:
    """
    데몬 타입 하나에 대한 실행·관리 설정.

    Attributes:
        daemon_type:             데몬 식별자 (예: "claude", "codex")
        command:                 CLI 실행 명령어 리스트
        cwd:                     작업 디렉토리 (None이면 현재 디렉토리)
        env_overrides:           OS 환경변수에 추가/덮어쓸 키-값
        env_remove:              OS 환경변수에서 제거할 키 목록
        idle_timeout:            유휴 타임아웃(초). 초과 시 프로세스 자동 종료
        request_timeout:         단일 요청 타임아웃(초). 초과 시 응답 중단
        shutdown_timeout:        SIGTERM 전송 후 SIGKILL까지 대기(초)
        stdin_enabled:           stdin 파이프 사용 여부
        stdout_limit:            stdout 버퍼 크기(바이트)
        warmup_count:            서버 시작 시 미리 생성할 프로세스 수
        max_restart_count:       자동 재시작 최대 횟수 (초과 시 DEAD 전환)
        restart_delay:           재시작 간 대기(초)
        mcp_config_path:         MCP 설정 파일 경로. None=자동감지, ""=MCP없음, "경로"=해당 파일
        pool_name:               풀 이름 (라우팅용)
        pool_size:               동시 처리 슬롯 수. 라운드로빈으로 요청 분산.
        pool_mode:               풀 운영 모드 (FIXED / ELASTIC)
        grace_timeout:           graceful shutdown 시 BUSY 대기(초)
        clearing_timeout:        CLEARING → DEAD 판정 타임아웃(초)
        min_spare:               ELASTIC 모드용 최소 여유 슬롯
        max_pool_size:           ELASTIC 모드용 최대 풀 크기 (0=pool_size와 동일)
        shrink_idle_timeout:     유휴 슬롯 축소 전 대기(초)
        max_concurrent_spawns:   동시 프로세스 생성 제한
        dead_replace_max_retries: DEAD 교체 재시도 횟수
        dead_replace_base_delay: 재시도 기본 딜레이(초)
        stdin_close_timeout:     stdin.close 후 종료 대기(초)
    """

    daemon_type: str
    command: list[str]
    cwd: Optional[str] = None
    env_overrides: dict[str, str] = field(default_factory=dict)
    env_remove: list[str] = field(default_factory=list)
    idle_timeout: int = 1800
    request_timeout: int = 1800
    shutdown_timeout: int = 5
    stdin_enabled: bool = True
    stdout_limit: int = 1024 * 1024  # 1 MB
    warmup_count: int = 0
    max_restart_count: int = 3
    restart_delay: float = 0.5
    mcp_config_path: Optional[str] = None
    # None → 루트 mcp-config.json 자동 감지 (기존 동작)
    # "" (빈 문자열) → MCP 없음 (memory 데몬)
    # "경로" → 해당 파일 사용
    pool_name: str = "default"
    pool_size: int = 1

    # -- P0-5: 풀 관리 설정 (기본값이 있으므로 하위호환 유지) --
    pool_mode: PoolMode = PoolMode.FIXED
    grace_timeout: float = 30.0
    clearing_timeout: float = 30.0
    min_spare: int = 0
    max_pool_size: int = 0  # 0이면 pool_size와 동일
    shrink_idle_timeout: float = 300.0
    max_concurrent_spawns: int = 2
    dead_replace_max_retries: int = 3
    dead_replace_base_delay: float = 0.5
    stdin_close_timeout: float = 2.0
    pool_acquire_timeout: float = 0  # 0이면 request_timeout 사용

    # -- 채팅 모드 설정 --
    clear_on_release: bool = True  # False → 채팅 모드 (release 시 /clear 안 함)
    initial_command: Optional[str] = None  # 세션 시작 시 실행할 명령 (예: "/jw-work")
    thinking_budget: Optional[str] = None  # "high", "medium" 등 thinking level
    max_tokens: Optional[int] = None  # 최대 출력 토큰 (None=CLI 기본값)

    def __post_init__(self) -> None:
        errors: list[str] = []

        if self.pool_size < 1:
            errors.append("pool_size >= 1")

        # max_pool_size == 0 이면 pool_size로 설정
        if self.max_pool_size == 0:
            object.__setattr__(self, "max_pool_size", self.pool_size)

        if self.max_pool_size < self.pool_size:
            errors.append("max_pool_size >= pool_size")

        if self.pool_mode == PoolMode.ELASTIC:
            if self.min_spare < 0:
                errors.append("ELASTIC: min_spare >= 0")

        if self.grace_timeout <= 0:
            errors.append("grace_timeout > 0")
        if self.clearing_timeout <= 0:
            errors.append("clearing_timeout > 0")

        if errors:
            raise ValueError(
                "DaemonConfig 검증 실패:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def build_env(self) -> dict[str, str]:
        """현재 OS 환경변수 기반으로 overrides 적용 + remove 제거한 환경변수 딕셔너리 반환.

        반환값은 asyncio.create_subprocess_exec()의 env 인자로 그대로 전달 가능하다.
        """
        # 1) 현재 OS 환경변수 복사
        env = dict(os.environ)

        # 2) 제거할 키 삭제
        for key in self.env_remove:
            env.pop(key, None)

        # 3) 추가/덮어쓸 키 적용
        env.update(self.env_overrides)

        return env
