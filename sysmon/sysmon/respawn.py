"""재시작 루프(respawn loop) 탐지 + stale pidfile 점검.

CPU sweep 은 「지금 CPU 를 많이 쓰는 프로세스」를 본다. 그래서 죽었다 살아나기를
반복하는 프로세스는 원리적으로 못 잡는다 — 스냅샷마다 PID 가 바뀌는 데다, 매번
막 뜬 참이라 ps 의 누적 pcpu 도 낮게 잡히기 때문이다.

  2026-09-14 실측: Privacy-i PIAgent 가 10초마다 재기동하며 CPU 를 상시 55% 태웠다.
  원인은 pidfile(ifi_piagent)에 18일 전 PID 512 가 박혀 있었고, 그 번호를 그 사이
  macOS diagnosticd 가 차지해 데몬이 "내가 이미 돌고 있다"고 오판한 것.
  sweep 은 보수·적극 어느 쪽으로도 이 프로세스를 후보에 올리지 못했다.

이 모듈은 **아무것도 kill 하지 않는다.** 탐지와 원인 보고만 한다.
보안 소프트웨어도 탐지 대상에 포함하되(루프의 주범이 보안 SW 인 경우가 실제로 있다),
kill 후보로는 절대 올리지 않는다 — 수리는 pidfile 교정 같은 비파괴적 수단으로 한다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .collectors.base import _SECURITY_PATTERNS

# 관찰 창 기본값. 루프 주기가 10초대인 사례를 2회 이상 관측하려면 최소 20초는 필요하다.
RESPAWN_SCAN_WINDOW_SEC = 20
RESPAWN_SCAN_INTERVAL_SEC = 1.0

# 이만큼 이상 서로 다른 PID 가 교대로 나타나야 루프로 본다.
RESPAWN_MIN_DISTINCT_PIDS = 2

# 원래 단명(短命)이라 교대가 정상인 프로세스. 이걸 걸러내지 않으면 결과가 노이즈로 덮여
# 정작 문제인 루프가 묻힌다 (2026-09-14 실측: 필터 없이 5건 중 4건이 오탐이었고,
# 그중 하나는 이 스캐너 자신이 매 샘플마다 띄우는 ps 였다).
# 어차피 CPU 를 태울 수 없는 것들이라 무조건 제외해도 놓치는 게 없다.
_ALWAYS_IGNORE_EXE: frozenset[str] = frozenset({
    # 셸 유틸 — 원래 떴다 죽는 게 정상이고 CPU 도 태우지 않는다.
    "sleep", "grep", "egrep", "fgrep", "awk", "sed", "cat", "head", "tail",
    "date", "echo", "which", "dirname", "basename", "uname", "wc", "tr", "cut",
    "sort", "uniq", "true", "false", "test", "expr", "env", "stat", "printf",
    "pgrep", "pkill", "killall", "id", "whoami", "tty", "hostname",
    # sysmon 자신이 메트릭 수집에 주기적으로 띄우는 것들.
    # 넣지 않으면 이 스캐너가 자기 발자국을 루프로 신고한다
    # (2026-09-14 실측: top 과 sh -c top 이 그대로 결과에 올라왔다).
    "ps", "top", "vm_stat", "sysctl", "df", "launchctl",
})

# 셸이 -c 로 감싸 실행한 경우 진짜 실행 대상은 그 뒤에 있다.
# `sh -c "top -l 2"` 를 sh 로 보면 blocklist 를 그대로 빠져나간다.
_SHELL_WRAPPERS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

# ps 가 커맨드를 괄호로 감싸면 종료 처리 중이거나 인자를 읽을 수 없는 상태다.
# 실행 주체를 특정할 수 없어 그룹 키가 엉키므로 제외한다.
_BRACKETED = re.compile(r"^\(.*\)$")

_GUARDS_PATH = Path(__file__).parent / "data" / "pidfile_guards.json"

# cmdline 을 그룹 키로 정규화할 때 버릴 토큰:
#   -Xmx512m, --no-browser 같은 플래그와 -Dkey=value 형태의 정의.
# 남는 것은 실행 파일 경로와 스크립트/메인클래스 인자라서, 재기동할 때마다
# 같은 값이 유지된다. (PID·임시경로가 인자로 들어가는 프로세스는 잡지 못한다 — 한계)
_DROPPABLE_TOKEN = re.compile(r"^-")


def _run(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


def sample_processes() -> list[dict[str, Any]]:
    """ps 스냅샷 1회. [{pid, ppid, cpu, cmd}, ...]"""
    out = _run("ps -Ao pid,ppid,pcpu,command")
    procs: list[dict[str, Any]] = []
    for line in out.split("\n")[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, ppid_s, cpu_s, cmd = parts
        if not pid_s.isdigit() or not ppid_s.isdigit():
            continue
        try:
            cpu = float(cpu_s)
        except ValueError:
            continue
        procs.append({"pid": int(pid_s), "ppid": int(ppid_s), "cpu": cpu, "cmd": cmd})
    return procs


def group_key(cmd: str) -> str:
    """
    재기동해도 변하지 않는 부분만 남긴 그룹 키.

    java 처럼 인자가 긴 경우에도 실행 경로 + 메인클래스가 남아 안정적으로 묶인다.
    """
    tokens = cmd.split()
    if not tokens:
        return cmd
    kept = [t for t in tokens if not _DROPPABLE_TOKEN.match(t)]
    return " ".join(kept) if kept else tokens[0]


def short_name(cmd: str, width: int = 70) -> str:
    """표시용 짧은 이름. .app 번들이면 번들명을 앞에 붙인다."""
    m = re.search(r"/([^/]+)\.app/", cmd)
    bundle = m.group(1) if m else ""
    first = cmd.split()[0] if cmd.split() else cmd
    tail = first.rstrip("/").split("/")[-1]
    # sh/python/java 는 그 자체론 정보가 없다 — 뒤따르는 스크립트/클래스명을 붙인다.
    extra = ""
    if tail in ("sh", "bash", "zsh", "python", "python3", "java", "node", "ruby", "perl"):
        for t in cmd.split()[1:]:
            if t.startswith("-"):
                continue
            extra = " " + t.rstrip("/").split("/")[-1]
            break
    name = f"{bundle} › {tail}{extra}" if bundle and bundle != tail else f"{tail}{extra}"
    return name[:width]


def effective_exe(cmd: str) -> str:
    """
    실효 실행 파일명. 셸 래퍼는 관통해서 진짜 대상을 집는다.

      "/bin/sh -c top -l 2"                  → "top"
      "/bin/sh /…/piagentad_darwin.sh"       → "piagentad_darwin.sh"
    """
    tokens = cmd.split()
    if not tokens:
        return ""
    exe = tokens[0].rstrip("/").split("/")[-1]
    if exe in _SHELL_WRAPPERS:
        for t in tokens[1:]:
            if t.startswith("-"):
                continue
            return t.rstrip("/").split("/")[-1]
    return exe


def is_ignorable(cmd: str) -> bool:
    """원래 교대가 정상인 단명 프로세스인가."""
    tokens = cmd.split()
    if not tokens:
        return True
    if _BRACKETED.match(tokens[0]):
        return True
    return effective_exe(cmd) in _ALWAYS_IGNORE_EXE


def is_security(cmd: str) -> bool:
    low = cmd.lower()
    return any(p.lower() in low for p in _SECURITY_PATTERNS)


def detect_respawn_loops(
    snapshots: Iterable[Iterable[dict[str, Any]]],
    min_distinct: int = RESPAWN_MIN_DISTINCT_PIDS,
) -> list[dict[str, Any]]:
    """
    스냅샷 시퀀스에서 재시작 루프를 찾아낸다. (순수 함수 — 테스트 가능)

    판정:
      - 같은 그룹 키에서 서로 다른 PID 가 min_distinct 개 이상 관측되고,
      - **어느 스냅샷에서도 그 키의 프로세스가 동시에 2개 이상 있지 않다**.

    두 번째 조건이 워커 풀과 루프를 가른다. Chrome 헬퍼나 워커 프로세스는
    여러 개가 동시에 살아 있지만, 재시작 루프는 한 번에 하나씩 교대로 뜬다.
    """
    snaps = [list(s) for s in snapshots]
    seen: dict[str, dict[str, Any]] = {}

    for idx, snap in enumerate(snaps):
        per_key: dict[str, list[dict[str, Any]]] = {}
        for p in snap:
            if is_ignorable(p["cmd"]):
                continue
            per_key.setdefault(group_key(p["cmd"]), []).append(p)

        for key, procs in per_key.items():
            entry = seen.setdefault(key, {
                "key": key,
                "pids": [],
                "max_concurrent": 0,
                "cpu_peak": 0.0,
                "cmd": procs[0]["cmd"],
                "snapshots_present": 0,
                "first_idx": idx,
                "last_idx": idx,
            })
            entry["max_concurrent"] = max(entry["max_concurrent"], len(procs))
            entry["snapshots_present"] += 1
            entry["last_idx"] = idx
            for p in procs:
                if p["pid"] not in entry["pids"]:
                    entry["pids"].append(p["pid"])
                entry["cpu_peak"] = max(entry["cpu_peak"], p["cpu"])

    loops: list[dict[str, Any]] = []
    for entry in seen.values():
        distinct = len(entry["pids"])
        if distinct < min_distinct or entry["max_concurrent"] > 1:
            continue
        loops.append({
            "key": entry["key"],
            "name": short_name(entry["cmd"]),
            "cmd": entry["cmd"],
            "distinct_pids": distinct,
            "pids": entry["pids"][:12],
            "cpu_peak": round(entry["cpu_peak"], 1),
            "security": is_security(entry["cmd"]),
        })

    loops.sort(key=lambda x: (-x["distinct_pids"], -x["cpu_peak"]))
    return loops


def scan_respawn(
    window_sec: int = RESPAWN_SCAN_WINDOW_SEC,
    interval_sec: float = RESPAWN_SCAN_INTERVAL_SEC,
    sampler: Optional[Callable[[], list[dict[str, Any]]]] = None,
    sleeper: Optional[Callable[[float], None]] = None,
) -> dict[str, Any]:
    """window_sec 동안 ps 를 반복 샘플링해 재시작 루프를 찾는다."""
    sampler = sampler or sample_processes
    sleeper = sleeper or time.sleep

    rounds = max(2, int(window_sec / interval_sec))
    snapshots: list[list[dict[str, Any]]] = []
    for i in range(rounds):
        snapshots.append(sampler())
        if i < rounds - 1:
            sleeper(interval_sec)

    loops = detect_respawn_loops(snapshots)
    for lp in loops:
        # 분당 스폰 횟수 — 관찰 창을 분으로 환산해 나눈다.
        minutes = max(window_sec / 60.0, 1e-6)
        lp["spawns_per_min"] = round(lp["distinct_pids"] / minutes, 1)
    return {
        "window_sec": window_sec,
        "samples": len(snapshots),
        "loops": loops,
    }


# ─── stale pidfile ───────────────────────────────────────────────


def load_guards(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """pidfile 점검 대상 목록을 JSON 에서 읽는다."""
    p = path or _GUARDS_PATH
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("guards", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _cmd_of(pid: int) -> str:
    return _run(f"ps -p {pid} -o command= 2>/dev/null")


def check_pidfile_guards(
    guards: Optional[list[dict[str, Any]]] = None,
    cmd_of: Optional[Callable[[int], str]] = None,
    reader: Optional[Callable[[str], str]] = None,
) -> list[dict[str, Any]]:
    """
    pidfile 에 적힌 PID 가 실제로 그 데몬인지 대조한다.

    status:
      ok      — PID 가 살아 있고 cmdline 도 일치
      stale   — PID 는 살아 있는데 **다른 프로세스**다 (PID 재사용 → 데몬이 오판)
      dead    — PID 가 존재하지 않는다 (보통 데몬이 알아서 덮어쓴다)
      missing — pidfile 자체가 없다 (정상이거나 이미 수리된 상태)
    """
    guards = guards if guards is not None else load_guards()
    cmd_of = cmd_of or _cmd_of
    reader = reader or (lambda p: Path(p).read_text(encoding="utf-8", errors="replace"))

    results: list[dict[str, Any]] = []
    for g in guards:
        pidfile = g.get("pidfile", "")
        row: dict[str, Any] = {
            "id": g.get("id", ""),
            "name": g.get("name", pidfile),
            "pidfile": pidfile,
            "needs_sudo": bool(g.get("needs_sudo")),
            "hint": g.get("hint", ""),
            "expect_cmd": g.get("expect_cmd", ""),
        }
        try:
            raw = reader(pidfile).strip()
        except OSError:
            row.update(status="missing", detail="pidfile 없음")
            results.append(row)
            continue

        if not raw.isdigit():
            row.update(status="missing", detail=f"PID 를 읽을 수 없음: {raw[:40]!r}")
            results.append(row)
            continue

        pid = int(raw)
        row["pid"] = pid
        actual = cmd_of(pid)
        if not actual:
            row.update(status="dead", detail=f"PID {pid} 프로세스 없음")
        elif row["expect_cmd"] and row["expect_cmd"].lower() not in actual.lower():
            row.update(
                status="stale",
                detail=f"PID {pid} 은(는) {short_name(actual)} — 기대값 {row['expect_cmd']!r} 불일치",
                actual_cmd=actual[:200],
            )
        else:
            row.update(status="ok", detail=f"PID {pid} 정상", actual_cmd=actual[:200])
        results.append(row)
    return results


def repair_pidfile(
    guard: dict[str, Any],
    password: str = "",
    backup_dir: str = "/tmp",
    runner: Optional[Callable[[str, str], tuple[int, str]]] = None,
) -> tuple[bool, str]:
    """
    stale pidfile 을 백업 경로로 **옮긴다**(지우지 않는다 — 롤백 가능하게).

    Returns: (성공여부, 메시지)
    """
    pidfile = guard.get("pidfile", "")
    if not pidfile:
        return False, "pidfile 경로가 비어 있습니다."

    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(backup_dir, f"{os.path.basename(pidfile)}.{stamp}.bak")

    def _default_runner(cmd: str, stdin: str) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                cmd, shell=True, input=stdin, capture_output=True, text=True, timeout=30
            )
            return proc.returncode, (proc.stderr.strip() or proc.stdout.strip())
        except subprocess.TimeoutExpired:
            return 124, "시간 초과 (30초)"

    run = runner or _default_runner

    if guard.get("needs_sudo"):
        if not password:
            return False, "이 파일은 root 소유라 sudo 비밀번호가 필요합니다."
        rc, err = run(f"sudo -S mv {pidfile!r} {dest!r}", password + "\n")
    else:
        rc, err = run(f"mv {pidfile!r} {dest!r}", "")

    if rc == 0:
        return True, f"{pidfile} → {dest} 로 이동했습니다 (롤백 가능)."
    if "incorrect password" in err.lower() or "sorry" in err.lower():
        return False, "비밀번호가 틀렸습니다."
    return False, f"이동 실패: {err}"
