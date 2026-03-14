"""server 모듈 테스트 — HTTP 엔드포인트 테스트."""
import json
from http.client import HTTPConnection
from threading import Thread
import time
import socket

import pytest


def _find_free_port() -> int:
    """사용 가능한 포트를 찾는다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 5.0) -> None:
    """서버가 준비될 때까지 대기."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/")
            conn.getresponse()
            conn.close()
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"서버가 {timeout}초 내에 시작되지 않음")


@pytest.fixture(scope="module")
def server_no_token():
    """토큰 없이 서버를 시작하는 fixture."""
    from sysmon.server import serve

    port = _find_free_port()
    host = "127.0.0.1"

    thread = Thread(
        target=serve,
        kwargs={
            "host": host,
            "port": port,
            "token": None,
            "open_browser": False,
        },
        daemon=True,
    )
    thread.start()
    _wait_for_server(host, port)
    yield host, port


@pytest.fixture(scope="module")
def server_with_token():
    """토큰 인증이 설정된 서버 fixture."""
    from sysmon.server import serve

    port = _find_free_port()
    host = "127.0.0.1"
    token = "test-secret-token-42"

    thread = Thread(
        target=serve,
        kwargs={
            "host": host,
            "port": port,
            "token": token,
            "open_browser": False,
        },
        daemon=True,
    )
    thread.start()
    _wait_for_server(host, port)
    yield host, port, token


class TestHtmlServed:
    """정적 HTML 서빙 테스트."""

    def test_html_served(self, server_no_token):
        """GET / 시 HTML을 반환해야 한다."""
        host, port = server_no_token
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()

        assert resp.status == 200
        assert "text/html" in resp.getheader("Content-Type", "")
        assert "<html" in body.lower() or "<!doctype" in body.lower()


class TestMetricsEndpoint:
    """메트릭 엔드포인트 테스트."""

    def test_metrics_endpoint(self, server_no_token):
        """GET /api/metrics 시 JSON을 반환하고 필수 키가 존재해야 한다."""
        host, port = server_no_token
        conn = HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/api/metrics")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()

        assert resp.status == 200
        data = json.loads(body)

        assert "system" in data
        assert "cpu" in data
        assert "memory" in data
        assert "mcp" in data


class TestQuickEndpoint:
    """빠른 조회 엔드포인트 테스트."""

    def test_quick_endpoint(self, server_no_token):
        """GET /api/quick 시 cpu_pct, ram_pct 키가 존재해야 한다."""
        host, port = server_no_token
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/quick")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()

        assert resp.status == 200
        data = json.loads(body)

        assert "cpu_pct" in data
        assert "ram_pct" in data


class TestTokenAuth:
    """토큰 인증 테스트."""

    def test_token_auth(self, server_with_token):
        """토큰 설정 시 인증 없는 요청은 403을 반환해야 한다."""
        host, port, token = server_with_token
        conn = HTTPConnection(host, port, timeout=5)

        # 토큰 없이 요청
        conn.request("GET", "/api/metrics")
        resp = conn.getresponse()
        resp.read()
        conn.close()

        assert resp.status == 401
