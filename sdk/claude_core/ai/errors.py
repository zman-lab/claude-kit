"""claude-core SDK 표준 예외 계층.

모든 AI 프로바이더가 일관된 예외를 발생시키도록 표준화.
프로젝트별 RuntimeError 대신 SDK 예외를 사용하면
호출부에서 에러 유형별 분기 처리가 가능해짐.
"""


class ClaudeCoreError(Exception):
    """claude-core SDK 최상위 예외"""

    def __init__(self, message: str = "", *, provider: str = ""):
        self.provider = provider
        super().__init__(message)


# ── AI Provider 에러 ──


class AIProviderError(ClaudeCoreError):
    """AI 프로바이더 관련 에러 기반 클래스"""


class AITimeoutError(AIProviderError):
    """AI 요청 타임아웃"""

    def __init__(self, timeout_seconds: float = 0, *, provider: str = ""):
        self.timeout_seconds = timeout_seconds
        msg = f"AI 요청 타임아웃 ({timeout_seconds}초)"
        if provider:
            msg = f"[{provider}] {msg}"
        super().__init__(msg, provider=provider)


class AIConnectionError(AIProviderError):
    """AI 서비스 연결 실패"""


class AIRateLimitError(AIProviderError):
    """API 요청 한도 초과 (429)"""

    def __init__(self, retry_after: float | None = None, *, provider: str = ""):
        self.retry_after = retry_after
        msg = "API 요청 한도 초과"
        if retry_after:
            msg += f" (재시도: {retry_after}초 후)"
        super().__init__(msg, provider=provider)


class AIAuthenticationError(AIProviderError):
    """API 키 인증 실패 (401/403)"""


class AIInvalidRequestError(AIProviderError):
    """잘못된 요청 (400) — 프롬프트 너무 큼, 모델 미지원 등"""


class AIMaxTokensExceeded(AIProviderError):
    """max_tokens 도달로 응답이 잘림 (stop_reason=max_tokens)

    partial_response에 잘린 응답을 담아 반환하므로
    호출부에서 JSON 복구 등 후처리 가능.
    """

    def __init__(self, partial_response: str = "", *, provider: str = ""):
        self.partial_response = partial_response
        super().__init__("max_tokens 도달로 응답 잘림", provider=provider)


# ── Daemon 에러 ──


class DaemonError(ClaudeCoreError):
    """Daemon 관련 에러 기반 클래스"""


class DaemonNotRunningError(DaemonError):
    """Daemon 프로세스가 실행 중이 아님"""


class DaemonBusyError(DaemonError):
    """Daemon이 다른 요청을 처리 중"""


class PoolAcquireTimeoutError(DaemonError):
    """Pool acquire 타임아웃 — 대기 시간 내에 IDLE 슬롯을 획득하지 못함.

    모든 슬롯이 BUSY/CLEARING 상태일 때 timeout 내에 IDLE 슬롯이
    확보되지 않으면 발생한다. slot_summary에 각 슬롯의 상태가 담긴다.
    """

    def __init__(
        self,
        timeout_seconds: float = 0,
        *,
        pool_name: str = "",
        slot_summary: str = "",
    ):
        self.timeout_seconds = timeout_seconds
        self.pool_name = pool_name
        self.slot_summary = slot_summary
        msg = f"Pool '{pool_name}' acquire 타임아웃 ({timeout_seconds:.1f}초)"
        if slot_summary:
            msg += f" | {slot_summary}"
        super().__init__(msg)


# ── Provider 설정 에러 ──


class ProviderNotConfiguredError(ClaudeCoreError):
    """요청한 프로바이더가 설정되지 않음 (daemon, internal 등)"""

    def __init__(self, provider_name: str, hint: str = ""):
        msg = f"'{provider_name}' 프로바이더가 설정되지 않았습니다"
        if hint:
            msg += f" ({hint})"
        super().__init__(msg, provider=provider_name)
