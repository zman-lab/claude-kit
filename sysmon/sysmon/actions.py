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
# CPU 해악 프로세스 정리 임계값
# conservative: 고아(PPID=1)·AppTranslocation·좀비만. 정상 부모가 있는 프로세스는 손대지 않는다.
# aggressive:   위 + 부모가 있어도 CPU 폭주 중인 것까지.
CPU_SWEEP_ORPHAN_THRESHOLD = 50.0
CPU_SWEEP_RUNAWAY_THRESHOLD = 100.0

# 폭주해도 죽이면 사용자 작업이 날아가는 것들 (aggressive 에서도 제외)
# 터미널·IDE·브라우저·에디터는 사용자가 그 안에서 작업 중일 수 있다.
_SWEEP_NEVER_KILL: tuple[str, ...] = (
    "/sbin/launchd", "loginwindow", "WindowServer", "kernel_task",
    "Finder.app", "Dock.app", "SystemUIServer",
    "iTerm", "Terminal.app", "Warp.app", "cmux",
    "IntelliJ", "idea", "PyCharm", "DataGrip", "Xcode",
    "Google Chrome.app", "Safari.app", "Firefox",
    "KakaoTalk", "Slack.app", "zoom",
    "ssh-agent", "sshd",
)

# AppTranslocation = Gatekeeper 격리 앱이 임시 경로에서 도는 상태.
# 캐시가 매 실행 무효화돼 재인덱싱을 반복하며 CPU 를 태운다 (2026-09-11 VS Code 실측).
_TRANSLOCATION_MARKER = "/AppTranslocation/"


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
        elif action_id == "cpu_sweep_preview_conservative":
            self._cpu_sweep(logs, mode="conservative", dry_run=True)
        elif action_id == "cpu_sweep_preview_aggressive":
            self._cpu_sweep(logs, mode="aggressive", dry_run=True)
        elif action_id == "cpu_sweep_conservative":
            self._cpu_sweep(logs, mode="conservative", dry_run=False)
        elif action_id == "cpu_sweep_aggressive":
            self._cpu_sweep(logs, mode="aggressive", dry_run=False)
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

    @classmethod
    def _sweep_candidates(cls, mode: str) -> list[dict[str, Any]]:
        """
        CPU 에 해악을 끼치는 프로세스 후보를 수집한다.

        판정 사유(reason)는 셋 중 하나:
          - orphan:        PPID=1 인데 CPU 를 태우는 중 (부모가 죽어 정리 신호를 받을 대상이 없다)
          - translocation: Gatekeeper 격리로 임시 경로에서 도는 앱 (캐시 무효화 → 재인덱싱 반복)
          - zombie:        Z 상태 (부모가 수거하지 않은 종료 잔재)
          - runaway:       부모가 있어도 CPU 폭주 (aggressive 전용)

        self/부모/보호대상은 여기서 전부 걸러낸다.
        """
        out = _run("ps -Ao pid,ppid,stat,pcpu,rss,command")
        me, my_parent = os.getpid(), os.getppid()
        cands: list[dict[str, Any]] = []

        for line in out.split("\n")[1:]:
            parts = line.strip().split(None, 5)
            if len(parts) < 6:
                continue
            pid_s, ppid_s, stat, cpu_s, rss_s, cmd = parts
            if not pid_s.isdigit() or not ppid_s.isdigit():
                continue
            pid, ppid = int(pid_s), int(ppid_s)
            try:
                cpu = float(cpu_s)
                rss_mb = round(int(rss_s) / 1024)
            except ValueError:
                continue

            # 1. 시스템/자기 자신/부모 제외
            if pid <= 1 or pid in (me, my_parent):
                continue
            # 2. 보안 프로세스 제외 (기존 _kill_process 와 동일 기준)
            low = cmd.lower()
            if any(p.lower() in low for p in _SECURITY_PATTERNS):
                continue
            # 3. sysmon 자신 제외
            if any(p in low for p in ("sysmon", "uvicorn", "gunicorn")):
                continue
            # 4. 죽이면 사용자 작업이 날아가는 것 제외
            if any(n.lower() in low for n in _SWEEP_NEVER_KILL):
                continue

            is_zombie = stat.startswith("Z")
            is_transloc = _TRANSLOCATION_MARKER in cmd
            is_orphan = ppid == 1

            reason = ""
            if is_zombie:
                reason = "zombie"
            elif is_transloc and cpu >= 1.0:
                reason = "translocation"
            elif is_orphan and cpu >= CPU_SWEEP_ORPHAN_THRESHOLD:
                reason = "orphan"
            elif mode == "aggressive" and cpu >= CPU_SWEEP_RUNAWAY_THRESHOLD:
                reason = "runaway"

            if reason:
                cands.append({
                    "pid": pid, "cpu": cpu, "rss_mb": rss_mb,
                    "reason": reason, "cmd": cmd,
                })

        cands.sort(key=lambda c: c["cpu"], reverse=True)
        return cands

    @staticmethod
    def _short_cmd(cmd: str, width: int = 60) -> str:
        """
        로그 표시용 이름. `.app` 번들이면 앱 이름을 앞에 붙인다.

        경로에 공백이 있어 split() 으로 실행 파일을 못 끊는 경우가 많다
        ("Visual Studio Code.app/..." → "Visual"). 그래서 .app 번들명을 따로 집는다.
        """
        m = re.search(r"/([^/]+)\.app/", cmd)
        bundle = m.group(1) if m else ""
        tail = cmd.rstrip("/").split("/")[-1].split()[0] if cmd.strip() else cmd
        name = f"{bundle} › {tail}" if bundle and bundle != tail else (bundle or tail)
        return name[:width]

    @classmethod
    def _cpu_sweep(cls, logs: list[str], mode: str, dry_run: bool) -> None:
        """
        CPU 해악 프로세스 일괄 정리.

        dry_run=True 면 무엇을 죽일지만 보고하고 실제로 죽이지 않는다.
        UI 는 미리보기 → 확인 → 실행 순으로 호출한다.

        ⚠️ SIGKILL 을 버티는 경우가 실제로 있다 — 커널이 종료 처리 중인 UE(uninterruptible+exiting)
        상태에서는 시그널이 무시된다(2026-09-11 VS Code 고아 프로세스 실측). 그래서 3라운드 반복한다.
        """
        label = "보수적" if mode == "conservative" else "적극적"
        cands = cls._sweep_candidates(mode)

        if not cands:
            logs.append(f"[{label}] 정리할 프로세스가 없습니다.")
            return

        total_cpu = sum(c["cpu"] for c in cands)
        total_mem = sum(c["rss_mb"] for c in cands)

        if dry_run:
            logs.append(f"[{label} 미리보기] 대상 {len(cands)}개 · CPU 합계 {total_cpu:.0f}% · 메모리 {total_mem}MB")
            for c in cands:
                logs.append(
                    f"  PID {c['pid']:>6} · CPU {c['cpu']:>6.1f}% · "
                    f"{c['rss_mb']:>5}MB · [{c['reason']}] {cls._short_cmd(c['cmd'])}"
                )
            logs.append("\n※ 미리보기입니다. 실제로 종료하지 않았습니다.")
            return

        pids = [str(c["pid"]) for c in cands]
        logs.append(f"[{label}] 대상 {len(cands)}개 종료 시작 (CPU 합계 {total_cpu:.0f}%)")

        # SIGTERM → SIGKILL, 최대 3라운드 (UE 상태 대응)
        for pid in pids:
            _run(f"kill -TERM {pid} 2>/dev/null")
        time.sleep(1)

        remaining = pids
        for rnd in range(1, 4):
            remaining = [p for p in remaining if _run(f"ps -p {p} -o pid= 2>/dev/null").strip()]
            if not remaining:
                break
            for pid in remaining:
                _run(f"kill -KILL {pid} 2>/dev/null")
            time.sleep(1.5)
            logs.append(f"  round {rnd}: SIGKILL 후 잔존 {len(remaining)}개")

        alive = [p for p in pids if _run(f"ps -p {p} -o pid= 2>/dev/null").strip()]
        killed = len(pids) - len(alive)
        logs.append(f"\n{killed}/{len(pids)}개 종료 완료 · CPU {total_cpu:.0f}% · 메모리 {total_mem}MB 회수 예상")

        if alive:
            logs.append(
                f"⚠️ {len(alive)}개가 종료되지 않았습니다 (PID {', '.join(alive)}).\n"
                "커널 종료 처리 중(UE)일 수 있습니다 — 잠시 후 다시 실행해 보세요."
            )

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
