"""
ElkHound QA MCP Server (MVP — Phase 1)
- Docker 빌드/배포 제어
- pytest 실행 + 결과 파싱
- curl TC 실행
- API 헬스체크
- 컨테이너 로그 조회
- DaemonPool 상태 조회
- 통합 QA 파이프라인
"""
import json
import os
import re
import subprocess
import time

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "elkhound-qa",
    instructions="ElkHound 웹서비스 QA 자동화 — Docker + pytest + curl TC + 헬스체크",
)

# ── 상태 ──────────────────────────────────────────────────────────────────────

_state = {
    "target": os.environ.get("EH_TARGET", "local"),
    "local_api": "http://localhost:17778",
    "local_admin": "http://localhost:17776",
    "alpha7_api": "http://elkhound.hangame.com:7778",
    "alpha7_admin": "http://elkhound.hangame.com:7777",
    "project_path": os.environ.get(
        "EH_PROJECT_PATH",
        "/Users/nhn/work/ideaworks/product/elkhound",
    ),
    "docker_compose": os.environ.get("EH_DOCKER_COMPOSE", ""),
}


def _api_url() -> str:
    return _state[f"{_state['target']}_api"]


def _admin_url() -> str:
    return _state[f"{_state['target']}_admin"]


def _compose_file() -> str:
    if _state["docker_compose"]:
        return _state["docker_compose"]
    if _state["target"] == "alpha7":
        return "docker-compose.alpha7.yml"
    return "docker-compose.yml"


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 120, cwd: str | None = None) -> tuple[str, int]:
    """셸 명령 실행 후 (stdout+stderr, returncode) 반환."""
    work_dir = cwd or _state["project_path"]
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return f"TIMEOUT ({timeout}s)", 1


def _http_get(path: str, timeout: int = 10) -> tuple[dict | str, int]:
    """API GET 요청. (응답, status_code) 반환."""
    url = f"{_api_url()}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            try:
                return resp.json(), resp.status_code
            except Exception:
                return resp.text, resp.status_code
    except httpx.ConnectError:
        return {"error": f"연결 실패: {url}"}, 0
    except httpx.TimeoutException:
        return {"error": f"타임아웃: {url}"}, 0


def _parse_pytest_output(output: str) -> dict:
    """pytest 출력에서 passed/failed/error 수 추출."""
    result = {"passed": 0, "failed": 0, "error": 0, "warnings": 0, "total": 0}

    # "X passed, Y failed, Z error" 패턴
    summary_match = re.search(
        r"=+\s*(.*?)\s*=+\s*$", output, re.MULTILINE
    )
    if summary_match:
        summary = summary_match.group(1)
        for key in ("passed", "failed", "error", "warnings"):
            m = re.search(rf"(\d+)\s+{key}", summary)
            if m:
                result[key] = int(m.group(1))

    result["total"] = result["passed"] + result["failed"] + result["error"]

    # 실패 상세 추출
    fail_sections = re.findall(
        r"FAILED\s+(.*?)(?:\n|$)", output
    )
    if fail_sections:
        result["failed_tests"] = fail_sections

    return result


# ── 환경 제어 도구 ────────────────────────────────────────────────────────────

@mcp.tool()
def set_target(target: str) -> str:
    """대상 환경 전환 (local / alpha7).

    Args:
        target: "local" 또는 "alpha7"
    """
    if target not in ("local", "alpha7"):
        return f"ERROR: target은 'local' 또는 'alpha7'만 가능 (입력: {target})"
    _state["target"] = target
    return (
        f"target: {target}\n"
        f"api_url: {_api_url()}\n"
        f"admin_url: {_admin_url()}\n"
        f"compose: {_compose_file()}"
    )


@mcp.tool()
def get_target() -> str:
    """현재 대상 환경 조회."""
    return (
        f"target: {_state['target']}\n"
        f"api_url: {_api_url()}\n"
        f"admin_url: {_admin_url()}\n"
        f"compose: {_compose_file()}\n"
        f"project_path: {_state['project_path']}"
    )


# ── 헬스체크 도구 ─────────────────────────────────────────────────────────────

@mcp.tool()
def health_check() -> str:
    """ElkHound API 헬스체크. 현재 target 환경의 API 상태 확인.

    Returns:
        status, response_time_ms, indices_count 등
    """
    result = {"target": _state["target"], "api_url": _api_url()}

    # /api/config/indices 호출
    start = time.time()
    resp, status = _http_get("/api/config/indices")
    elapsed_ms = int((time.time() - start) * 1000)

    result["response_time_ms"] = elapsed_ms

    if status == 0:
        result["status"] = "UNREACHABLE"
        result["error"] = resp.get("error", "연결 실패") if isinstance(resp, dict) else str(resp)
        return json.dumps(result, ensure_ascii=False, indent=2)

    result["status_code"] = status
    if status == 200:
        result["status"] = "OK"
        if isinstance(resp, dict):
            indices = resp.get("indices", resp.get("data", []))
            if isinstance(indices, list):
                result["indices_count"] = len(indices)
        elif isinstance(resp, list):
            result["indices_count"] = len(resp)
    else:
        result["status"] = "ERROR"
        result["response"] = str(resp)[:500]

    return json.dumps(result, ensure_ascii=False, indent=2)


# ── 테스트 도구 ───────────────────────────────────────────────────────────────

@mcp.tool()
def run_pytest(filter: str = "", verbose: bool = True) -> str:
    """pytest 유닛테스트 실행.

    Args:
        filter: pytest -k 필터 (예: "test_database", "test_elk"). 비어있으면 전체.
        verbose: -v 플래그 (기본 True)

    Returns:
        passed/failed/error 수 요약 + 실패 시 traceback
    """
    cmd = "python -m pytest tests/"
    if filter:
        cmd += f" -k '{filter}'"
    if verbose:
        cmd += " -v"
    cmd += " --tb=short"

    output, rc = _run(cmd, timeout=180)

    parsed = _parse_pytest_output(output)
    summary = f"{parsed['passed']} passed, {parsed['failed']} failed, {parsed['error']} error"

    result_lines = [f"pytest: {summary}"]

    if parsed.get("failed_tests"):
        result_lines.append("\n실패 목록:")
        for ft in parsed["failed_tests"][:10]:
            result_lines.append(f"  - {ft}")

    if rc != 0 and parsed["failed"] == 0 and parsed["error"] == 0:
        # 파싱 실패 시 원본 마지막 50줄
        tail = "\n".join(output.split("\n")[-50:])
        result_lines.append(f"\n원본 출력 (마지막 50줄):\n{tail}")

    return "\n".join(result_lines)


@mcp.tool()
def run_curl_tc(
    method: str = "GET",
    path: str = "/api/config/indices",
    body: str = "",
    expect_status: int = 200,
    expect_contains: str = "",
) -> str:
    """curl TC 1건 실행.

    Args:
        method: HTTP 메서드 (GET, POST, PUT, DELETE)
        path: API 경로 (예: "/api/config/indices")
        body: POST/PUT body (JSON 문자열). GET이면 무시.
        expect_status: 기대 HTTP 상태코드 (기본 200)
        expect_contains: 응답에 포함되어야 할 문자열. 비어있으면 상태코드만 체크.

    Returns:
        PASS/FAIL + 상세
    """
    url = f"{_api_url()}{path}"
    try:
        with httpx.Client(timeout=30) as client:
            if method.upper() in ("POST", "PUT", "PATCH"):
                headers = {"Content-Type": "application/json"}
                resp = client.request(
                    method.upper(), url, content=body, headers=headers
                )
            else:
                resp = client.request(method.upper(), url)

            status_ok = resp.status_code == expect_status
            content_ok = True
            if expect_contains:
                content_ok = expect_contains in resp.text

            verdict = "PASS" if (status_ok and content_ok) else "FAIL"

            result_lines = [
                f"{verdict}: {method} {path}",
                f"  status: {resp.status_code} (expected: {expect_status})",
            ]

            if not status_ok:
                result_lines.append(f"  status MISMATCH")

            if expect_contains and not content_ok:
                result_lines.append(
                    f"  expected '{expect_contains}' not found in response"
                )

            # 응답 요약 (최대 500자)
            resp_preview = resp.text[:500]
            result_lines.append(f"  response: {resp_preview}")

            return "\n".join(result_lines)

    except httpx.ConnectError:
        return f"FAIL: {method} {path}\n  연결 실패: {url}"
    except httpx.TimeoutException:
        return f"FAIL: {method} {path}\n  타임아웃: {url}"


# ── Docker 도구 ───────────────────────────────────────────────────────────────

@mcp.tool()
def docker_build(no_cache: bool = True) -> str:
    """ElkHound Docker 이미지 빌드.

    Args:
        no_cache: True면 --no-cache 빌드 (기본 True)

    Returns:
        빌드 결과 (성공/실패, 소요시간)
    """
    compose = _compose_file()
    cmd = f"docker compose -f {compose} build"
    if no_cache:
        cmd += " --no-cache"

    start = time.time()
    output, rc = _run(cmd, timeout=600)
    elapsed = int(time.time() - start)

    if rc == 0:
        return f"빌드 성공 ({elapsed}s)\ncompose: {compose}"
    else:
        # 마지막 30줄만
        tail = "\n".join(output.split("\n")[-30:])
        return f"빌드 실패 ({elapsed}s)\ncompose: {compose}\n\n{tail}"


@mcp.tool()
def docker_up(wait_health: bool = True) -> str:
    """Docker 컨테이너 시작.

    Args:
        wait_health: True면 API 응답 대기 (최대 30초, 3초 간격 폴링)

    Returns:
        컨테이너 상태 + 헬스체크 결과
    """
    compose = _compose_file()
    output, rc = _run(f"docker compose -f {compose} up -d", timeout=60)

    if rc != 0:
        return f"docker up 실패:\n{output}"

    result_lines = [f"docker up OK (compose: {compose})"]

    if wait_health:
        # 헬스체크 폴링
        for attempt in range(10):
            time.sleep(3)
            resp, status = _http_get("/api/config/indices", timeout=5)
            if status == 200:
                result_lines.append(
                    f"헬스체크 OK ({(attempt + 1) * 3}s)"
                )
                break
        else:
            result_lines.append("헬스체크 실패: 30초 내 API 응답 없음")

    return "\n".join(result_lines)


@mcp.tool()
def docker_down() -> str:
    """Docker 컨테이너 중지 + 제거.

    Returns:
        중지 결과
    """
    compose = _compose_file()
    output, rc = _run(f"docker compose -f {compose} down", timeout=60)

    if rc == 0:
        return f"docker down OK (compose: {compose})"
    else:
        return f"docker down 실패:\n{output}"


# ── 로그 도구 ─────────────────────────────────────────────────────────────────

@mcp.tool()
def check_logs(
    container: str = "elkhound",
    lines: int = 100,
    filter: str = "",
) -> str:
    """Docker 컨테이너 로그 조회.

    Args:
        container: 컨테이너명 ("elkhound" | "eh-admin")
        lines: 최근 N줄 (기본 100)
        filter: grep 필터 (예: "ERROR", "WARNING"). 비어있으면 전체.

    Returns:
        로그 텍스트
    """
    cmd = f"docker logs --tail {lines} {container} 2>&1"
    if filter:
        cmd += f" | grep -i '{filter}'"

    output, rc = _run(cmd, timeout=30)

    if not output:
        if filter:
            return f"'{filter}' 패턴 없음 (최근 {lines}줄)"
        return f"로그 비어있음 (컨테이너: {container})"

    return output


# ── DaemonPool 상태 도구 ──────────────────────────────────────────────────────

@mcp.tool()
def pool_status() -> str:
    """DaemonPool 상태 조회 (활성 데몬 수, 큐 크기 등).

    Returns:
        DaemonPool 상태 JSON
    """
    resp, status = _http_get("/api/status")

    if status == 0:
        return f"API 응답 없음: {resp}"

    if status == 200:
        if isinstance(resp, dict):
            return json.dumps(resp, ensure_ascii=False, indent=2)
        return str(resp)

    return f"status {status}: {resp}"


# ── 통합 QA 도구 ──────────────────────────────────────────────────────────────

@mcp.tool()
def full_qa(skip_build: bool = False) -> str:
    """전체 QA 파이프라인: build -> up -> health_check -> pytest -> check_logs.

    Args:
        skip_build: True면 빌드 스킵 (이미 빌드된 상태)

    Returns:
        단계별 PASS/FAIL 종합 리포트
    """
    steps = []
    total_steps = 5 if not skip_build else 4
    step_num = 0
    failed_at = None

    # 1. 빌드
    if not skip_build:
        step_num += 1
        start = time.time()
        compose = _compose_file()
        cmd = f"docker compose -f {compose} build --no-cache"
        _, rc = _run(cmd, timeout=600)
        elapsed = int(time.time() - start)
        if rc == 0:
            steps.append(f"{step_num}/{total_steps} 빌드: OK ({elapsed}s)")
        else:
            steps.append(f"{step_num}/{total_steps} 빌드: FAIL ({elapsed}s)")
            failed_at = "빌드"

    # 2. 배포
    if not failed_at:
        step_num += 1
        compose = _compose_file()
        _, rc = _run(f"docker compose -f {compose} up -d", timeout=60)
        if rc == 0:
            steps.append(f"{step_num}/{total_steps} 배포: OK")
        else:
            steps.append(f"{step_num}/{total_steps} 배포: FAIL")
            failed_at = "배포"

    # 3. 헬스체크
    if not failed_at:
        step_num += 1
        health_ok = False
        for attempt in range(10):
            time.sleep(3)
            _, status = _http_get("/api/config/indices", timeout=5)
            if status == 200:
                health_ok = True
                elapsed = (attempt + 1) * 3
                steps.append(
                    f"{step_num}/{total_steps} 헬스: OK ({elapsed}s)"
                )
                break
        if not health_ok:
            steps.append(f"{step_num}/{total_steps} 헬스: FAIL (30s 타임아웃)")
            failed_at = "헬스체크"

    # 4. pytest
    if not failed_at:
        step_num += 1
        cmd = "python -m pytest tests/ -v --tb=short"
        output, rc = _run(cmd, timeout=180)
        parsed = _parse_pytest_output(output)
        summary = f"{parsed['passed']} passed, {parsed['failed']} failed"
        if rc == 0 and parsed["failed"] == 0:
            steps.append(f"{step_num}/{total_steps} pytest: {summary}")
        else:
            steps.append(f"{step_num}/{total_steps} pytest: FAIL ({summary})")
            if parsed.get("failed_tests"):
                for ft in parsed["failed_tests"][:5]:
                    steps.append(f"  - {ft}")
            failed_at = "pytest"

    # 5. 로그 에러 체크
    if not failed_at:
        step_num += 1
        log_output, _ = _run(
            "docker logs --tail 200 elkhound 2>&1 | grep -i 'ERROR\\|EXCEPTION\\|Traceback'",
            timeout=15,
        )
        error_count = len(log_output.strip().split("\n")) if log_output.strip() else 0
        if error_count == 0:
            steps.append(f"{step_num}/{total_steps} 로그: OK (에러 없음)")
        else:
            steps.append(
                f"{step_num}/{total_steps} 로그: WARNING ({error_count}건 에러 감지)"
            )

    # 종합
    steps.append("")
    if failed_at:
        steps.append(f"── 종합: FAIL ({failed_at}에서 중단) ──")
    else:
        steps.append("── 종합: ALL PASS ──")

    return "\n".join(steps)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
