"""FastAPI 라우터 — optional import (FastAPI 없어도 패키지 동작)."""
from typing import Any, Optional


def create_router(prefix: str = "/sysmon", token: Optional[str] = None) -> Any:
    """
    FastAPI APIRouter를 생성하여 반환한다.

    FastAPI가 설치되지 않으면 ImportError를 발생시킨다.
    호출 예:
        app = FastAPI()
        app.include_router(create_router())
    """
    try:
        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI 라우터를 사용하려면 fastapi를 설치하세요: pip install fastapi"
        )

    import json
    import os

    from .actions import ActionRunner
    from .collectors import get_collector

    router = APIRouter(prefix=prefix)
    collector = get_collector()
    runner = ActionRunner()

    # HTML 파일 경로
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    html_path = os.path.join(static_dir, "index.html")

    def _load_html() -> str:
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        # FastAPI 라우터 모드에서는 API 경로에 prefix 추가
        # /api/metrics → /sysmon/api/metrics
        content = content.replace("'/api/", f"'{prefix}/api/")
        content = content.replace('"/api/', f'"{prefix}/api/')
        return content

    def _check_token(request: Request) -> bool:
        """토큰 인증 검사."""
        if not token:
            return True
        # ?token=xxx
        if request.query_params.get("token") == token:
            return True
        # Authorization: Bearer xxx
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {token}":
            return True
        return False

    @router.get("/")
    async def dashboard(request: Request) -> HTMLResponse:
        if not _check_token(request):
            return HTMLResponse("Unauthorized", status_code=401)
        return HTMLResponse(_load_html())

    @router.get("/api/metrics")
    async def metrics(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return JSONResponse(collector.collect_all())

    @router.get("/api/quick")
    async def quick(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return JSONResponse(collector.collect_quick())

    @router.post("/api/action/{action_id}")
    async def action(action_id: str, request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        kwargs: dict[str, Any] = {}
        try:
            body = await request.body()
            if body:
                kwargs = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            pass
        result = runner.run(action_id, **kwargs)
        result["metrics"] = collector.collect_all()
        return JSONResponse(result)

    @router.get("/api/process-desc")
    async def get_process_desc(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from .collectors.base import _load_process_desc
        return JSONResponse(_load_process_desc())

    @router.post("/api/process-desc")
    async def save_process_desc(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        from .collectors.base import _save_process_desc
        try:
            _save_process_desc(data)
        except OSError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse({"ok": True})

    @router.get("/api/claude-config")
    async def claude_config(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from .collectors.base import _scan_claude_config
        return JSONResponse(_scan_claude_config())

    @router.get("/api/claude-file")
    async def claude_file(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        fpath = request.query_params.get("path", "")
        if not fpath:
            return JSONResponse({"error": "path required"}, status_code=400)
        from .collectors.base import _read_claude_file
        return JSONResponse(_read_claude_file(fpath))

    @router.get("/api/claude-deps")
    async def claude_deps(request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        fpath = request.query_params.get("path", "")
        if not fpath:
            return JSONResponse({"error": "path required"}, status_code=400)
        from .collectors.base import _analyze_dependencies
        return JSONResponse(_analyze_dependencies(fpath))

    @router.get("/api/docker-logs/{container}")
    async def docker_logs(container: str, request: Request) -> JSONResponse:
        if not _check_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        from .collectors.base import _get_docker_logs
        qs = request.query_params
        tail = int(qs.get("tail", "200"))
        level = qs.get("level")
        search = qs.get("search")
        return JSONResponse(_get_docker_logs(container, tail, level, search))

    @router.get("/docker-log")
    async def docker_log_page(request: Request) -> HTMLResponse:
        if not _check_token(request):
            return HTMLResponse("Unauthorized", status_code=401)
        name = request.query_params.get("name", "")
        if not name:
            return HTMLResponse("name parameter required", status_code=400)
        from .collectors.base import _docker_log_html
        return HTMLResponse(_docker_log_html(name))

    return router
