"""수집기 추상 인터페이스."""
from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """각 플랫폼별 수집기가 구현해야 하는 인터페이스."""

    @abstractmethod
    def collect_system(self) -> dict[str, Any]:
        """칩셋, 코어 수, 전체 RAM 등 시스템 기본 정보."""
        ...

    @abstractmethod
    def collect_quick(self) -> dict[str, Any]:
        """경량 CPU + RAM 스냅샷 (5초 폴링용, <200ms)."""
        ...

    @abstractmethod
    def collect_cpu(self) -> dict[str, Any]:
        """CPU 사용률, 로드 평균, 프로세스/스레드 수."""
        ...

    @abstractmethod
    def collect_memory(self) -> dict[str, Any]:
        """메모리 상세 (활성, 비활성, wired, 압축, 스왑 등)."""
        ...

    @abstractmethod
    def collect_disk(self) -> dict[str, Any]:
        """루트 디스크 사용량."""
        ...

    @abstractmethod
    def collect_processes(self) -> list[dict[str, Any]]:
        """RSS 5MB 이상 프로세스 목록."""
        ...

    def collect_docker(self) -> dict[str, Any]:
        """Docker 컨테이너 메모리 요약 (docker stats 기반)."""
        return _collect_docker_common()

    def analyze_mcp(self, procs: list[dict[str, Any]]) -> dict[str, Any]:
        """MCP 서버 프로세스 분석."""
        return _analyze_mcp_common(procs)

    def analyze_claude(self, procs: list[dict[str, Any]]) -> dict[str, Any]:
        """Claude CLI 세션 분석."""
        return _analyze_claude_common(procs)

    def analyze_claude_detailed(self, procs: list[dict[str, Any]]) -> dict[str, Any]:
        """Claude 세션 상세 분석 — 트리 구조 + 좀비 감지."""
        return _analyze_claude_detailed(procs)

    def categorize_processes(
        self, procs: list[dict[str, Any]], mcp_pids: list[str]
    ) -> dict[str, Any]:
        """프로세스를 카테고리별로 분류."""
        return _categorize_common(procs, mcp_pids)

    def collect_all(self) -> dict[str, Any]:
        """전체 메트릭 수집 + 인사이트 생성."""
        import time
        from ..analyzer import Analyzer

        start = time.time()
        sys_info = self.collect_system()
        cpu = self.collect_cpu()
        mem = self.collect_memory()
        disk = self.collect_disk()
        procs = self.collect_processes()
        mcp = self.analyze_mcp(procs)
        claude = self.analyze_claude(procs)
        claude_sessions = self.analyze_claude_detailed(procs)
        docker = self.collect_docker()
        cats = self.categorize_processes(procs, mcp["pids"])

        data: dict[str, Any] = {
            "system": sys_info,
            "cpu": cpu,
            "memory": mem,
            "disk": disk,
            "mcp": mcp,
            "claude": claude,
            "claude_sessions": claude_sessions,
            "docker": docker,
            "categories": cats,
            "collect_ms": round((time.time() - start) * 1000),
            "timestamp": time.strftime("%H:%M:%S KST"),
        }
        data["insights"] = Analyzer().generate_insights(data)
        return data


# ── 공통 헬퍼 (Darwin/Linux 모두 동일한 로직) ──

import os
import re
import subprocess
import time


def _run(cmd: str, timeout: int = 10) -> str:
    """셸 명령 실행 후 stdout 반환. 실패 시 빈 문자열."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


# MCP 서버 패턴 (이름 → 프로세스 커맨드 정규식)
MCP_PATTERNS: dict[str, str] = {
    "mysql-mcp": "mysql_mcp_server",
    "context7": "context7-mcp",
    "seq-thinking": "sequential-thinking",
    "ssh-manager": "ssh-manager/dist/index.js",
    "dooray-mcp": "dooray-mcp/main.py",
    "elasticsearch": "elasticsearch-mcp-server",
    "pptx-mcp": "ppt_mcp_server",
    "uv-launcher": r"uvx.*ppt_mcp_server|uvx.*office-powerpoint",
    "npm-launcher": r"npm exec.*context7|npm exec.*sequential",
}

# 프로세스 카테고리 분류 규칙
_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("security", ["broadcom", "com.broadcom"]),
    ("chrome", ["Google Chrome", "chrome"]),
    ("docker", ["Virtualization.VirtualMachine", "com.docker"]),
    ("warp", ["Warp.app"]),
    ("ide", ["JetBrains", "cursor", "Cursor"]),
    ("system", ["mds_stores", "WindowServer", "Spotlight", "Finder"]),
    ("kakaotalk", ["KakaoTalk"]),
]


def _collect_docker_common() -> dict[str, Any]:
    """docker stats로 컨테이너 메모리 합산."""
    out = _run(
        'docker stats --no-stream --format "{{.Name}}|{{.MemUsage}}" 2>/dev/null'
    )
    total_mb = 0.0
    count = 0
    for line in out.split("\n"):
        if not line.strip() or "|" not in line:
            continue
        count += 1
        mem_str = line.split("|")[1].split("/")[0].strip()
        if "GiB" in mem_str:
            total_mb += float(re.sub(r"[A-Za-z ]", "", mem_str)) * 1024
        elif "MiB" in mem_str:
            total_mb += float(re.sub(r"[A-Za-z ]", "", mem_str))
    return {"count": count, "total_mb": round(total_mb)}


def _analyze_mcp_common(procs: list[dict[str, Any]]) -> dict[str, Any]:
    """MCP 패턴 매칭으로 MCP 서버별 프로세스 집계."""
    breakdown: dict[str, dict[str, Any]] = {}
    pids: list[str] = []
    for name, pat in MCP_PATTERNS.items():
        matched = [p for p in procs if re.search(pat, p["cmd"])]
        breakdown[name] = {
            "count": len(matched),
            "total_mb": round(sum(p["rss_mb"] for p in matched)),
        }
        pids.extend(p["pid"] for p in matched)
    return {
        "total_count": sum(v["count"] for v in breakdown.values()),
        "total_mb": sum(v["total_mb"] for v in breakdown.values()),
        "breakdown": breakdown,
        "pids": pids,
    }


def _analyze_claude_common(procs: list[dict[str, Any]]) -> dict[str, Any]:
    """Claude CLI 메인/서브에이전트 세션 분류."""
    sessions: list[dict[str, Any]] = []
    for p in procs:
        if "claude" not in p["cmd"].lower():
            continue
        if any(x in p["cmd"] for x in ["grep", "sysmon", "python"]):
            continue
        is_sub = "stream-json" in p["cmd"] and "dangerously-skip" in p["cmd"]
        is_main = not is_sub and (
            "claude" in p["cmd"].split()[0]
            or ".local/bin/claude" in p["cmd"]
        )
        if not (is_sub or is_main):
            continue
        args = ""
        if "--effort" in p["cmd"]:
            args += "--effort max "
        if "--resume" in p["cmd"]:
            args += "--resume "
        if is_sub:
            args = "subagent"
        sessions.append({
            "pid": p["pid"],
            "type": "sub" if is_sub else "main",
            "args": args.strip(),
            "rss_mb": p["rss_mb"],
        })
    return {
        "main_count": sum(1 for s in sessions if s["type"] == "main"),
        "sub_count": sum(1 for s in sessions if s["type"] == "sub"),
        "total_count": len(sessions),
        "total_mb": sum(s["rss_mb"] for s in sessions),
        "sessions": sorted(sessions, key=lambda x: -x["rss_mb"]),
    }


# 팀/프로젝트 매핑 패턴
_TEAM_PATTERNS: list[tuple[str, list[str]]] = [
    ("board", ["zman-lab/board"]),
    ("airlock", ["dev-airlock"]),
    ("elkhound", ["elkhound"]),
    ("law", ["my-law"]),
    ("lawear", ["lawear"]),
    ("claude-kit", ["claude-kit"]),
    ("sdk", ["zman-lab/sdk"]),
]


def _detect_team(cwd: str) -> str:
    """작업 디렉토리 → 팀/프로젝트명."""
    if not cwd:
        return "unknown"
    for team, patterns in _TEAM_PATTERNS:
        if any(p in cwd for p in patterns):
            return team
    return os.path.basename(cwd) or "unknown"


def _analyze_claude_detailed(procs: list[dict[str, Any]]) -> dict[str, Any]:
    """Claude 세션 상세 분석 — 메인/서브 트리, 좀비 감지, 팀·모델·시작시간."""
    claude_procs = []
    for p in procs:
        if "claude" not in p["cmd"].lower():
            continue
        if any(x in p["cmd"] for x in ["grep", "sysmon", "python"]):
            continue
        is_sub = "stream-json" in p["cmd"] and "dangerously-skip" in p["cmd"]
        is_main = not is_sub and (
            "claude" in p["cmd"].split()[0]
            or ".local/bin/claude" in p["cmd"]
        )
        if not (is_sub or is_main):
            continue
        claude_procs.append({**p, "_is_sub": is_sub})

    if not claude_procs:
        return {
            "trees": [], "zombies": [],
            "main_count": 0, "sub_count": 0, "zombie_count": 0,
            "total_count": 0, "total_mb": 0,
        }

    pids = [p["pid"] for p in claude_procs]
    pid_csv = ",".join(pids)

    # Batch: lstart + %cpu
    ps_extra: dict[str, dict[str, Any]] = {}
    for line in _run(f"ps -p {pid_csv} -o pid=,lstart=,%cpu=").split("\n"):
        parts = line.split()
        if len(parts) >= 7:
            ps_extra[parts[0]] = {
                "start_time": " ".join(parts[1:6]),
                "cpu_pct": float(parts[6]),
            }

    # Batch: cwd via lsof
    cwd_map: dict[str, str] = {}
    cur_pid = None
    for line in _run(
        f"lsof -p {pid_csv} -a -d cwd -F pn 2>/dev/null"
    ).split("\n"):
        if line.startswith("p"):
            cur_pid = line[1:]
        elif line.startswith("n") and cur_pid:
            cwd_map[cur_pid] = line[1:]

    # Build session list
    sessions: list[dict[str, Any]] = []
    for p in claude_procs:
        pid = p["pid"]
        extra = ps_extra.get(pid, {})
        cwd = cwd_map.get(pid, "")

        model = ""
        m = re.search(r"--model\s+(\S+)", p["cmd"])
        if m:
            model = re.sub(r"claude-(\w+)-(\d+)-\d+", r"\1-\2", m.group(1))

        max_turns = 0
        m = re.search(r"--max-turns\s+(\d+)", p["cmd"])
        if m:
            max_turns = int(m.group(1))

        cpu_pct = extra.get("cpu_pct", 0.0)
        sessions.append({
            "pid": pid,
            "ppid": p["ppid"],
            "type": "sub" if p["_is_sub"] else "main",
            "model": model,
            "max_turns": max_turns,
            "cwd": cwd,
            "team": _detect_team(cwd),
            "start_time": extra.get("start_time", ""),
            "cpu_pct": round(cpu_pct, 1),
            "rss_mb": p["rss_mb"],
            "status": "active" if cpu_pct > 1.0 else "idle",
        })

    # Tree: main → sub-agents (via ppid)
    main_pids = {s["pid"] for s in sessions if s["type"] == "main"}
    trees: list[dict[str, Any]] = []
    assigned: set[str] = set()

    for s in sessions:
        if s["type"] != "main":
            continue
        subs = [
            sub for sub in sessions
            if sub["type"] == "sub" and sub["ppid"] == s["pid"]
        ]
        assigned.update(sub["pid"] for sub in subs)
        sub_mb = sum(sub["rss_mb"] for sub in subs)
        trees.append({
            **s,
            "sub_agents": sorted(subs, key=lambda x: -x["rss_mb"]),
            "sub_count": len(subs),
            "total_mb": s["rss_mb"] + sub_mb,
        })

    zombies = [
        s for s in sessions
        if s["type"] == "sub" and s["pid"] not in assigned
    ]

    return {
        "trees": sorted(trees, key=lambda x: -x["total_mb"]),
        "zombies": sorted(zombies, key=lambda x: -x["rss_mb"]),
        "main_count": len(trees),
        "sub_count": sum(1 for s in sessions if s["type"] == "sub"),
        "zombie_count": len(zombies),
        "total_count": len(sessions),
        "total_mb": sum(s["rss_mb"] for s in sessions),
    }


def _categorize_common(
    procs: list[dict[str, Any]], mcp_pids: list[str]
) -> dict[str, dict[str, Any]]:
    """프로세스를 카테고리별로 분류 (50MB 이상만)."""
    cats: dict[str, dict[str, int]] = {}
    mcp_set = set(mcp_pids)
    for p in procs:
        if p["pid"] in mcp_set or "claude" in p["cmd"].lower():
            continue
        cat = "other"
        for name, patterns in _CATEGORY_RULES:
            if any(pt.lower() in p["cmd"].lower() for pt in patterns):
                cat = name
                break
        entry = cats.setdefault(cat, {"total_mb": 0, "count": 0})
        entry["total_mb"] += p["rss_mb"]
        entry["count"] += 1
    return {
        k: {"total_mb": round(v["total_mb"]), "count": v["count"]}
        for k, v in cats.items()
        if v["total_mb"] > 50
    }
