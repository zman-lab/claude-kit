"""액션 실행기 — MCP 종료, 캐시 퍼지 등."""
import os
import re
import subprocess
import time
from typing import Any

from .collectors.base import _SECURITY_PATTERNS

# launchd 레이블 허용 패턴: 영문자, 숫자, 점, 밑줄, 하이픈만 허용
_LABEL_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')

# launchd 보호 대상 레이블 (비활성화 거부)
_PROTECTED_LAUNCHD_LABELS: frozenset[str] = frozenset({
    "com.claude-sysmon",
})


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
        elif action_id.startswith("docker_stop_"):
            name = action_id[len("docker_stop_"):]
            self._docker_action(name, "stop", logs)
        elif action_id.startswith("docker_start_"):
            name = action_id[len("docker_start_"):]
            self._docker_action(name, "start", logs)
        elif action_id.startswith("docker_restart_"):
            name = action_id[len("docker_restart_"):]
            self._docker_action(name, "restart", logs)
        elif action_id == "purge_cache":
            self._purge_cache(logs, password=kwargs.get("password", ""))
        elif action_id.startswith("kill_claude_tree_"):
            pid = action_id[len("kill_claude_tree_"):]
            self._kill_claude_tree(pid, logs)
        elif action_id.startswith("kill_claude_"):
            pid = action_id[len("kill_claude_"):]
            self._kill_claude_single(pid, logs)
        elif action_id == "kill_all_zombies":
            self._kill_all_zombies(logs)
        elif action_id.startswith("kill_process_"):
            pid = action_id[len("kill_process_"):]
            self._kill_process(pid, logs)
        elif action_id.startswith("launchd_disable_"):
            label = action_id[len("launchd_disable_"):]
            self._launchd_toggle(label, "disable", logs)
        elif action_id.startswith("launchd_enable_"):
            label = action_id[len("launchd_enable_"):]
            self._launchd_toggle(label, "enable", logs)
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
    def _docker_action(name: str, action: str, logs: list[str]) -> None:
        """Docker 컨테이너 stop/start/restart."""
        result = _run(f"docker {action} {name} 2>&1", timeout=30)
        if result:
            logs.append(f"{name}: docker {action} → {result}")
        else:
            logs.append(f"{name}: docker {action} 완료.")

    @staticmethod
    def _kill_claude_single(pid: str, logs: list[str]) -> None:
        """단일 Claude 프로세스 종료."""
        cmd = _run(f"ps -p {pid} -o command= 2>/dev/null")
        if "claude" not in cmd.lower():
            logs.append(f"PID {pid}은(는) Claude 프로세스가 아닙니다.")
            return
        _run(f"kill -TERM {pid} 2>/dev/null")
        time.sleep(0.5)
        alive = _run(f"ps -p {pid} -o pid= 2>/dev/null").strip()
        if alive:
            _run(f"kill -KILL {pid} 2>/dev/null")
            logs.append(f"PID {pid} 강제 종료 (SIGKILL).")
        else:
            logs.append(f"PID {pid} 정상 종료 (SIGTERM).")

    @staticmethod
    def _kill_claude_tree(pid: str, logs: list[str]) -> None:
        """메인 세션 + 모든 자식 Claude 프로세스 종료."""
        cmd = _run(f"ps -p {pid} -o command= 2>/dev/null")
        if "claude" not in cmd.lower():
            logs.append(f"PID {pid}은(는) Claude 프로세스가 아닙니다.")
            return
        children = _run(f"pgrep -P {pid} 2>/dev/null").split()
        claude_children = []
        for cpid in children:
            ccmd = _run(f"ps -p {cpid} -o command= 2>/dev/null")
            if "claude" in ccmd.lower():
                claude_children.append(cpid)
        for cpid in claude_children:
            _run(f"kill -TERM {cpid} 2>/dev/null")
        _run(f"kill -TERM {pid} 2>/dev/null")
        time.sleep(0.5)
        alive = _run(f"ps -p {pid} -o pid= 2>/dev/null").strip()
        if alive:
            _run(f"kill -KILL {pid} 2>/dev/null")
        logs.append(
            f"메인 PID {pid} + 서브에이전트 {len(claude_children)}개 종료 완료."
        )

    @staticmethod
    def _kill_all_zombies(logs: list[str]) -> None:
        """부모 없는 좀비 Claude 서브에이전트 종료."""
        out = _run("ps -eo pid,ppid,command")
        main_pids: set[str] = set()
        sub_entries: list[tuple[str, str]] = []
        for line in out.split("\n")[1:]:
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid, ppid, cmd = parts[0], parts[1], parts[2]
            if "claude" not in cmd.lower():
                continue
            if any(x in cmd for x in ["grep", "sysmon", "python"]):
                continue
            is_sub = "stream-json" in cmd and "dangerously-skip" in cmd
            is_main = not is_sub and (
                "claude" in cmd.split()[0] or ".local/bin/claude" in cmd
            )
            if is_main:
                main_pids.add(pid)
            elif is_sub:
                sub_entries.append((pid, ppid))
        killed = 0
        for pid, ppid in sub_entries:
            if ppid not in main_pids:
                _run(f"kill -TERM {pid} 2>/dev/null")
                killed += 1
        if killed:
            time.sleep(0.5)
            logs.append(f"좀비 서브에이전트 {killed}개 종료 완료.")
        else:
            logs.append("종료할 좀비 없음.")

    @staticmethod
    def _kill_process(pid: str, logs: list[str]) -> None:
        """일반 프로세스 종료 (보호 대상 거부, SIGTERM → SIGKILL 순서)."""
        # 진입 로그
        logs.append(f"[kill_process] PID={pid} 종료 요청 진입.")

        # 1. PID 숫자 검증
        if not pid.isdigit():
            logs.append(f"PID '{pid}'은(는) 유효하지 않은 형식입니다.")
            return

        pid_int = int(pid)

        # 2. PID 범위 검증 (PID ≤ 1은 시스템 프로세스)
        if pid_int <= 1:
            logs.append(f"PID {pid}은(는) 시스템 보호 대상입니다.")
            return

        # 3. sysmon 자기 자신 및 부모 프로세스 거부
        if pid_int == os.getpid() or pid_int == os.getppid():
            logs.append(f"PID {pid}은(는) 보호 대상 프로세스입니다. (sysmon 자신)")
            return

        # 4. 프로세스 존재 확인 + 커맨드 추출
        cmd = _run(f"ps -p {pid} -o command= 2>/dev/null")
        if not cmd:
            logs.append(f"PID {pid} 프로세스를 찾을 수 없습니다.")
            return

        logs.append(f"[kill_process] PID={pid} cmd={cmd[:80]!r}")

        # 5. security 패턴 포함 시 거부
        cmd_lower = cmd.lower()
        if any(pat.lower() in cmd_lower for pat in _SECURITY_PATTERNS):
            logs.append(f"PID {pid}은(는) 보호 대상 프로세스입니다. (security)")
            return

        # 6. SIGTERM 시도
        _run(f"kill -TERM {pid} 2>/dev/null")
        time.sleep(0.5)
        alive = _run(f"ps -p {pid} -o pid= 2>/dev/null").strip()

        if not alive:
            logs.append(f"PID {pid} 정상 종료 (SIGTERM).")
            return

        # 7. SIGKILL 강제 종료
        logs.append(f"[kill_process] PID={pid} SIGTERM 후 생존 — SIGKILL 시도.")
        _run(f"kill -KILL {pid} 2>/dev/null")
        logs.append(f"PID {pid} 강제 종료 (SIGKILL).")

    @staticmethod
    def _launchd_toggle(label: str, action: str, logs: list[str]) -> None:
        """
        LaunchAgent 활성화/비활성화.

        Args:
            label: LaunchAgent 레이블 (예: com.example.myapp)
            action: "enable" 또는 "disable"
            logs: 로그 리스트 (in-place 추가)

        주의: 변경 사항은 재부팅 후 적용됩니다.
        """
        logs.append(f"[launchd_toggle] label={label!r} action={action!r} 진입.")

        # 1. 레이블 유효성 검사
        if not label:
            logs.append("레이블이 비어있습니다.")
            return

        # 1-1. 정규식 검증 (쉘 메타문자 인젝션 방지)
        if not _LABEL_PATTERN.match(label):
            logs.append(f"유효하지 않은 레이블 형식: {label!r}")
            return

        # 2. 보호 대상 레이블 거부
        if label in _PROTECTED_LAUNCHD_LABELS:
            logs.append(f"{label}은(는) 보호 대상 서비스입니다. 변경 불가.")
            return

        # 3. security 패턴 포함 여부 확인
        label_lower = label.lower()
        if any(pat.lower() in label_lower for pat in _SECURITY_PATTERNS):
            logs.append(f"{label}은(는) 보안 서비스입니다. 변경 불가.")
            return

        # 4. action 유효성 검사
        if action not in ("enable", "disable"):
            logs.append(f"유효하지 않은 액션: {action!r}. 'enable' 또는 'disable'이어야 합니다.")
            return

        # 5. uid 조회
        uid = str(os.getuid())
        cmd = f"launchctl {action} gui/{uid}/{label}"
        logs.append(f"[launchd_toggle] 실행: {cmd}")

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                action_label = "비활성화" if action == "disable" else "활성화"
                logs.append(f"{label} {action_label} 완료.")
                logs.append("변경 사항은 재부팅 후 적용됩니다.")
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                logs.append(f"launchctl {action} 실패: {err}")
        except subprocess.TimeoutExpired:
            logs.append(f"launchctl {action} 시간 초과 (10초).")

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
