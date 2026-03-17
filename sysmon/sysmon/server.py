"""내장 HTTP 서버 — 외부 의존성 없이 동작."""
import http.server
import json
import os
import threading
import time
import webbrowser
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .actions import ActionRunner
from .collectors import get_collector

# HTML 파일 경로 (패키지 내 static/)
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_HTML_PATH = os.path.join(_STATIC_DIR, "index.html")


def _load_html() -> str:
    """HTML 파일을 읽어서 반환."""
    with open(_HTML_PATH, encoding="utf-8") as f:
        return f.read()


def _make_handler(
    token: Optional[str],
) -> type:
    """토큰 인증이 적용된 요청 핸들러 클래스를 생성한다."""

    collector = get_collector()
    runner = ActionRunner()
    html_content = _load_html()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass  # 로그 비활성화

        def _check_auth(self) -> bool:
            """토큰 인증 검사. 토큰 미설정 시 항상 통과."""
            if not token:
                return True
            # ?token=xxx 쿼리 파라미터
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if qs.get("token", [None])[0] == token:
                return True
            # Authorization: Bearer xxx 헤더
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {token}":
                return True
            self.send_error(401, "Unauthorized")
            return False

        def _json_response(self, data: dict[str, Any]) -> None:
            """JSON 응답 전송."""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

        def do_GET(self) -> None:
            if not self._check_auth():
                return
            path = urlparse(self.path).path
            if path in ("/", ""):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_content.encode())
            elif path == "/api/metrics":
                self._json_response(collector.collect_all())
            elif path == "/api/quick":
                self._json_response(collector.collect_quick())
            elif path.startswith("/api/docker-logs/"):
                container = path.split("/api/docker-logs/")[1]
                qs = parse_qs(urlparse(self.path).query)
                tail = int(qs.get("tail", ["200"])[0])
                level = qs.get("level", [None])[0]
                search = qs.get("search", [None])[0]
                from .collectors.base import _get_docker_logs
                self._json_response(_get_docker_logs(container, tail, level, search))
            elif path == "/api/claude-config":
                from .collectors.base import _scan_claude_config
                self._json_response(_scan_claude_config())
            elif path == "/api/claude-file":
                qs = parse_qs(urlparse(self.path).query)
                fpath = qs.get("path", [""])[0]
                if fpath:
                    from .collectors.base import _read_claude_file
                    self._json_response(_read_claude_file(fpath))
                else:
                    self.send_error(400)
            elif path == "/api/claude-deps":
                qs = parse_qs(urlparse(self.path).query)
                fpath = qs.get("path", [""])[0]
                if fpath:
                    from .collectors.base import _analyze_dependencies
                    self._json_response(_analyze_dependencies(fpath))
                else:
                    self.send_error(400)
            elif path == "/docker-log":
                qs = parse_qs(urlparse(self.path).query)
                name = qs.get("name", [""])[0]
                if name:
                    from .collectors.base import _docker_log_html
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(_docker_log_html(name).encode())
                else:
                    self.send_error(400)
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if not self._check_auth():
                return
            path = urlparse(self.path).path
            if path.startswith("/api/action/"):
                action_id = path.split("/api/action/")[1]
                # JSON body 파싱
                kwargs: dict[str, Any] = {}
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    try:
                        kwargs = json.loads(self.rfile.read(content_length))
                    except (json.JSONDecodeError, ValueError):
                        pass
                result = runner.run(action_id, **kwargs)
                result["metrics"] = collector.collect_all()
                self._json_response(result)
            else:
                self.send_error(404)

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 19090,
    token: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    """HTTP 서버 시작."""
    handler_class = _make_handler(token)
    server = http.server.HTTPServer((host, port), handler_class)

    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
    if token:
        url += f"?token={token}"

    print(f"\n  System Monitor — {url}")
    print(f"  Ctrl+C to stop\n")

    if open_browser:
        threading.Thread(
            target=lambda: (time.sleep(0.5), webbrowser.open(url)),
            daemon=True,
        ).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()
