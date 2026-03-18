"""
Android CDP MCP Server
- adb 무선 디버깅으로 Android 기기 제어
- Chrome DevTools Protocol로 WebView 내부 JS 실행 / UI 클릭
"""
import base64
import json
import os
import subprocess
from typing import Optional

import websocket
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "android-cdp",
    instructions="Android WebView 앱 자동 QA — adb + Chrome DevTools Protocol",
)

# ── 상태 ──────────────────────────────────────────────────────────────────────

_state = {
    "device": os.environ.get("ADB_DEVICE", ""),
    "ws": None,
    "ws_url": "",
    "msg_id": 0,
    "cdp_port": 9222,
}


# ── ADB 내부 헬퍼 ────────────────────────────────────────────────────────────

def _adb(*args: str, timeout: int = 30) -> tuple[str, int]:
    cmd = ["adb"]
    if _state["device"]:
        cmd += ["-s", _state["device"]]
    cmd += list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1


# ── CDP 내부 헬퍼 ────────────────────────────────────────────────────────────

def _cdp_send(method: str, params: Optional[dict] = None, timeout: int = 10):
    ws = _state["ws"]
    if not ws:
        return {"error": "CDP 미연결. cdp_connect를 먼저 호출하세요."}
    _state["msg_id"] += 1
    msg_id = _state["msg_id"]
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    ws.settimeout(timeout)
    while True:
        try:
            resp = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            return {"error": "CDP 응답 타임아웃"}
        if resp.get("id") == msg_id:
            return resp.get("result", {})


def _cdp_eval(expression: str, timeout: int = 10):
    result = _cdp_send("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    }, timeout=timeout)
    if "error" in result:
        return result
    inner = result.get("result", {})
    return inner.get("value", inner.get("description", str(inner)))


# ── ADB 도구 ─────────────────────────────────────────────────────────────────

@mcp.tool()
def adb_devices() -> str:
    """연결된 Android 기기 목록 반환"""
    out, _ = _adb("devices")
    return out


@mcp.tool()
def adb_connect(ip_port: str, pair_port: Optional[str] = None, pair_code: Optional[str] = None) -> str:
    """무선 디버깅 연결. pair_port/pair_code가 있으면 페어링도 수행.

    Args:
        ip_port: 연결용 IP:포트 (예: "10.77.76.239:39363")
        pair_port: 페어링 IP:포트 (예: "10.77.76.239:34761"). 선택.
        pair_code: 페어링 코드 (예: "719732"). pair_port와 함께 사용.
    """
    results = []
    if pair_port and pair_code:
        out, rc = _adb("pair", pair_port, pair_code)
        results.append(f"pair: {'OK' if rc == 0 else out}")

    out, rc = _adb("connect", ip_port)
    results.append(f"connect: {out}")

    if "connected" in out:
        _state["device"] = ip_port

    return "\n".join(results)


@mcp.tool()
def adb_install(apk_path: str, clean: bool = False) -> str:
    """APK를 기기에 설치.

    Args:
        apk_path: APK 파일 절대경로
        clean: True면 기존 앱 제거 후 설치
    """
    results = []
    if clean:
        # 패키지명 추출은 aapt가 필요하므로 간단히 시도
        _adb("uninstall", os.environ.get("APP_PACKAGE", "com.zmanlab.lawear"))
        results.append("기존 앱 제거 시도")

    out, rc = _adb("install", "-r", apk_path, timeout=60)
    results.append(f"install: {'Success' if rc == 0 else out}")
    return "\n".join(results)


@mcp.tool()
def adb_uninstall(package: str = "") -> str:
    """앱 제거.

    Args:
        package: 패키지명. 비어있으면 APP_PACKAGE 환경변수 사용.
    """
    pkg = package or os.environ.get("APP_PACKAGE", "com.zmanlab.lawear")
    out, _ = _adb("uninstall", pkg)
    return out


@mcp.tool()
def adb_start_app(package: str = "", activity: str = "") -> str:
    """앱 시작.

    Args:
        package: 패키지명. 비어있으면 환경변수 사용.
        activity: 액티비티명. 비어있으면 환경변수 사용.
    """
    pkg = package or os.environ.get("APP_PACKAGE", "com.zmanlab.lawear")
    act = activity or os.environ.get("APP_ACTIVITY", f"{pkg}/.MainActivity")
    out, _ = _adb("shell", "am", "start", "-n", act)
    return out


@mcp.tool()
def adb_stop_app(package: str = "") -> str:
    """앱 강제 종료.

    Args:
        package: 패키지명. 비어있으면 환경변수 사용.
    """
    pkg = package or os.environ.get("APP_PACKAGE", "com.zmanlab.lawear")
    out, _ = _adb("shell", "am", "force-stop", pkg)
    return f"force-stop {pkg}: {out or 'OK'}"


@mcp.tool()
def adb_logcat_crash(lines: int = 200) -> str:
    """logcat에서 FATAL EXCEPTION 수집.

    Args:
        lines: 검색할 최근 라인 수
    """
    out, _ = _adb("logcat", "-d", "-t", str(lines))
    crash_lines = []
    capture = False
    for line in out.split("\n"):
        if "FATAL EXCEPTION" in line:
            capture = True
        if capture:
            crash_lines.append(line)
            if len(crash_lines) > 30:
                break
        if capture and line.strip() == "":
            capture = False
    return "\n".join(crash_lines) if crash_lines else "크래시 없음"


@mcp.tool()
def adb_clear_logcat() -> str:
    """logcat 클리어"""
    _adb("logcat", "-c")
    return "logcat cleared"


@mcp.tool()
def adb_screenshot() -> str:
    """기기 전체 화면 스크린샷. base64 PNG로 반환."""
    out, rc = _adb("exec-out", "screencap", "-p")
    if rc != 0:
        return f"스크린샷 실패: {out}"
    path = "/tmp/android_cdp_screen.png"
    # exec-out은 바이너리 → subprocess로 직접
    cmd = ["adb"]
    if _state["device"]:
        cmd += ["-s", _state["device"]]
    cmd += ["exec-out", "screencap", "-p"]
    result = subprocess.run(cmd, capture_output=True, timeout=10)
    with open(path, "wb") as f:
        f.write(result.stdout)
    return f"스크린샷 저장: {path} ({len(result.stdout)} bytes)"


# ── CDP 도구 ─────────────────────────────────────────────────────────────────

@mcp.tool()
def cdp_connect(port: int = 9222) -> str:
    """WebView Chrome DevTools Protocol 연결.
    자동으로 WebView 소켓을 찾고 포트 포워딩 후 연결.

    Args:
        port: 로컬 포워딩 포트 (기본 9222)
    """
    _state["cdp_port"] = port

    # 기존 연결 정리
    if _state["ws"]:
        try:
            _state["ws"].close()
        except Exception:
            pass
        _state["ws"] = None

    # WebView DevTools 소켓 찾기
    out, _ = _adb("shell", "cat", "/proc/net/unix")
    socket_name = None
    for line in out.split("\n"):
        if "webview_devtools_remote_" in line:
            for part in line.strip().split():
                if part.startswith("@webview_devtools_remote_"):
                    socket_name = part[1:]
                    break
            if socket_name:
                break

    if not socket_name:
        return "ERROR: WebView DevTools 소켓 없음. 앱이 실행 중인지 확인."

    # 포트 포워딩
    _adb("forward", f"tcp:{port}", f"localabstract:{socket_name}")

    # 페이지 URL 가져오기
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/json", timeout=5)
        pages = json.loads(resp.read())
    except Exception as e:
        return f"ERROR: CDP /json 실패 — {e}"

    if not pages:
        return "ERROR: WebView 페이지 없음"

    ws_url = pages[0].get("webSocketDebuggerUrl", "")
    if not ws_url:
        return "ERROR: webSocketDebuggerUrl 없음"

    # WebSocket 연결 (suppress_origin 필수!)
    try:
        _state["ws"] = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        _state["ws_url"] = ws_url
    except Exception as e:
        return f"ERROR: WebSocket 연결 실패 — {e}"

    return f"CDP 연결 OK: {ws_url[:60]}..."


@mcp.tool()
def cdp_click(text: str) -> str:
    """텍스트를 포함하는 요소를 찾아 클릭.

    Args:
        text: 클릭할 요소의 텍스트 (예: "민사소송법", "Case 01", "재생")
    """
    return _cdp_eval(f"""
    (function() {{
        const els = document.querySelectorAll('button, div, a, span, p');
        for (const el of els) {{
            if (el.textContent.includes('{text}') && el.offsetParent !== null) {{
                el.click();
                return 'clicked: ' + el.tagName + ' > ' + el.textContent.trim().substring(0, 50);
            }}
        }}
        return 'NOT FOUND: {text}';
    }})()
    """)


@mcp.tool()
def cdp_eval(js: str) -> str:
    """WebView에서 JavaScript 실행 후 결과 반환.

    Args:
        js: 실행할 JavaScript 코드
    """
    result = _cdp_eval(js)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


@mcp.tool()
def cdp_screenshot() -> str:
    """WebView 내부 스크린샷. /tmp에 저장 후 경로 반환."""
    result = _cdp_send("Page.captureScreenshot", {"format": "png"})
    if "error" in result:
        return f"ERROR: {result['error']}"
    data = result.get("data", "")
    if not data:
        return "ERROR: 스크린샷 데이터 없음"
    path = "/tmp/android_cdp_webview.png"
    with open(path, "wb") as f:
        f.write(base64.b64decode(data))
    return path


@mcp.tool()
def cdp_get_text(max_items: int = 20) -> str:
    """현재 WebView 화면의 텍스트 요약.

    Args:
        max_items: 반환할 최대 텍스트 요소 수
    """
    return _cdp_eval(f"""
    (function() {{
        const texts = [];
        document.querySelectorAll('h1,h2,h3,p,button,span').forEach(el => {{
            const t = el.textContent.trim();
            if (t && t.length < 100 && el.offsetParent !== null) texts.push(t);
        }});
        return texts.slice(0, {max_items}).join(' | ');
    }})()
    """)


# ── 통합 도구 ────────────────────────────────────────────────────────────────

@mcp.tool()
def full_deploy(apk_path: str, package: str = "", activity: str = "") -> str:
    """앱 제거 → 설치 → 시작 → CDP 연결까지 한 번에.

    Args:
        apk_path: APK 파일 절대경로
        package: 패키지명. 비어있으면 환경변수 사용.
        activity: 액티비티명. 비어있으면 환경변수 사용.
    """
    import time
    results = []

    pkg = package or os.environ.get("APP_PACKAGE", "com.zmanlab.lawear")

    # 1. 기존 앱 종료 + 제거
    adb_stop_app(pkg)
    _adb("uninstall", pkg)
    results.append("1/4 기존 앱 제거")

    # 2. 설치
    out, rc = _adb("install", apk_path, timeout=60)
    results.append(f"2/4 설치: {'OK' if rc == 0 else out}")
    if rc != 0:
        return "\n".join(results)

    # 3. 앱 시작
    act = activity or os.environ.get("APP_ACTIVITY", f"{pkg}/.MainActivity")
    _adb("shell", "am", "start", "-n", act)
    results.append("3/4 앱 시작")
    time.sleep(3)

    # 4. CDP 연결
    cdp_result = cdp_connect(_state["cdp_port"])
    results.append(f"4/4 CDP: {cdp_result}")

    return "\n".join(results)


@mcp.tool()
def check_crash() -> str:
    """크래시 감지 (logcat + CDP 연결 상태)"""
    results = []

    # logcat 크래시
    crash = adb_logcat_crash(100)
    if "크래시 없음" not in crash:
        results.append(f"CRASH DETECTED:\n{crash}")

    # CDP 연결 상태
    if _state["ws"]:
        try:
            _state["ws"].ping()
            results.append("CDP: 연결 유지")
        except Exception:
            results.append("CDP: 연결 끊김 (앱 크래시 가능)")
    else:
        results.append("CDP: 미연결")

    return "\n".join(results) if results else "정상"


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
