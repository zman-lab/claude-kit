"""DaemonPool 상태 관리 FastAPI 라우터 팩토리.

DaemonPool의 상태 조회, 리소스 모니터링, 런타임 관리를 위한
FastAPI 라우터를 생성한다.

사용법::

    from claude_core.daemon.status_router import create_status_router

    router = create_status_router(get_pool=lambda: app_state["daemon_pool"])
    app.include_router(router, prefix="/api/system")

Endpoints:
    GET  /pool-status   — 풀 상태 + 슬롯 상세
    GET  /resources      — 시스템 + 풀 리소스
    POST /pool/resize    — 런타임 풀 리사이즈
    POST /pool/kill-slot — 슬롯 강제 종료 + 교체
    GET  /health         — 헬스체크
"""
from typing import Callable, Optional

try:
    from fastapi import APIRouter, HTTPException, Query
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


def create_status_router(
    get_pool: Callable,
    get_manager: Optional[Callable] = None,
) -> "APIRouter":
    """DaemonPool 상태/관리 API 라우터를 생성한다.

    Args:
        get_pool: DaemonPool 인스턴스를 반환하는 callable.
                  풀이 초기화되지 않았으면 None을 반환해야 한다.
        get_manager: (optional) DaemonManager 인스턴스를 반환하는 callable.
                     향후 확장용.

    Returns:
        FastAPI APIRouter 인스턴스

    Raises:
        ImportError: fastapi가 설치되지 않은 환경
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "fastapi is required for create_status_router. "
            "Install it with: pip install fastapi"
        )

    router = APIRouter(tags=["system"])

    @router.get("/pool-status")
    async def pool_status():
        """풀 상태 + 슬롯 상세."""
        pool = get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="DaemonPool not initialized")
        return {
            "stats": pool.get_stats(),
            "slots": pool.get_slot_details(),
            "pool_size": pool.pool_size,
            "pool_name": pool._pool_name if hasattr(pool, "_pool_name") else None,
        }

    @router.get("/resources")
    async def resources():
        """시스템 + 풀 리소스 사용량."""
        pool = get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="DaemonPool not initialized")
        return pool.get_resource_usage()

    @router.post("/pool/resize")
    async def resize_pool(new_size: int = Query(..., ge=1, description="새 풀 크기")):
        """런타임 풀 리사이즈."""
        pool = get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="DaemonPool not initialized")
        try:
            return await pool.resize(new_size)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/pool/kill-slot")
    async def kill_slot(slot_id: str = Query(..., description="종료할 슬롯 ID")):
        """슬롯 강제 종료 + 교체."""
        pool = get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="DaemonPool not initialized")
        try:
            return await pool.kill_slot(slot_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.get("/health")
    async def health():
        """헬스체크."""
        pool = get_pool()
        stats = pool.get_stats() if pool else {}
        return {
            "status": "ok" if pool else "degraded",
            "pool_available": pool is not None,
            "stats": stats,
        }

    return router
