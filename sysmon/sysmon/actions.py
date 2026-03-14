"""액션 실행기 — MCP 종료, 캐시 퍼지 등."""
import subprocess
import time
from typing import Any


# MCP 이름별 kill 패턴 (pkill -f에 전달)
MCP_KILL_PATTERNS: dict[str, list[str]] = {
    "mysql-mcp": ["mysql_mcp_server"],
    "context7": ["context7-mcp", "npm exec.*context7"],
    "seq-thinking": ["sequential-thinking", "npm exec.*sequential"],
    "ssh-manager": ["ssh-manager/dist/index.js"],
    "dooray-mcp": ["dooray-mcp/main.py"],
    "elasticsearch": ["elasticsearch-mcp-server"],
    "pptx-mcp": ["ppt_mcp_server", "uvx.*office-powerpoint"],
    "uv-launcher": ["uvx.*ppt_mcp"],
    "npm-launcher": ["npm exec.*context7", "npm exec.*sequential"],
}


def _run(cmd: str, timeout: int = 10) -> str:
    """셸 명령 실행 후 stdout 반환."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


class ActionRunner:
    """인사이트에서 제안된 액션을 실행한다."""

    def run(self, action_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        액션 실행.

        Returns: {success: bool, logs: list[str], duration_ms: int}
        """
        start = time.time()
        logs: list[str] = []

        if action_id == "kill_all_mcp":
            self._kill_all_mcp(logs)
        elif action_id.startswith("kill_mcp_"):
            name = action_id[len("kill_mcp_"):]
            self._kill_mcp_by_name(name, logs)
        elif action_id == "purge_cache":
            self._purge_cache(logs, password=kwargs.get("password", ""))
        else:
            logs.append(f"알 수 없는 액션: {action_id}")

        return {
            "success": True,
            "logs": logs,
            "duration_ms": round((time.time() - start) * 1000),
        }

    def _kill_all_mcp(self, logs: list[str]) -> None:
        """모든 MCP 서버 프로세스 종료."""
        total = 0
        for name, patterns in MCP_KILL_PATTERNS.items():
            for pat in patterns:
                killed = self._kill_pattern(pat)
                total += killed
                if killed:
                    logs.append(f"  {name}: {killed}개 종료")

        if total:
            logs.insert(0, f"총 {total}개 MCP 프로세스 종료 완료.")
            logs.append("\n활성 세션의 MCP는 자동 재시작됩니다.")
        else:
            logs.append("종료할 MCP 없음.")

    def _kill_mcp_by_name(self, name: str, logs: list[str]) -> None:
        """특정 MCP 서버만 종료."""
        patterns = MCP_KILL_PATTERNS.get(name, [])
        total = 0
        for pat in patterns:
            total += self._kill_pattern(pat)

        if total:
            logs.append(f"{name}: {total}개 종료 완료.")
        else:
            logs.append(f"{name}: 종료할 프로세스 없음.")

    @staticmethod
    def _kill_pattern(pattern: str) -> int:
        """패턴 매칭으로 프로세스 종료, 종료된 수 반환."""
        before = int(_run(f"pgrep -f '{pattern}' 2>/dev/null | wc -l").strip() or 0)
        _run(f"pkill -f '{pattern}' 2>/dev/null")
        time.sleep(0.2)
        after = int(_run(f"pgrep -f '{pattern}' 2>/dev/null | wc -l").strip() or 0)
        return max(0, before - after)

    @staticmethod
    def _purge_cache(logs: list[str], password: str) -> None:
        """macOS 파일 캐시 퍼지 (sudo purge)."""
        if not password:
            logs.append("비밀번호가 입력되지 않았습니다.")
            return

        try:
            proc = subprocess.run(
                "sudo -S purge",
                shell=True,
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                logs.append("메모리 캐시 퍼지 완료!")
                logs.append("macOS 파일 캐시가 해제되었습니다.")
            else:
                err = proc.stderr.strip()
                if "incorrect password" in err.lower() or "sorry" in err.lower():
                    logs.append("비밀번호가 틀렸습니다. 다시 시도해주세요.")
                else:
                    logs.append(f"실행 실패: {err}")
        except subprocess.TimeoutExpired:
            logs.append("시간 초과 (30초)")
