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
    """Docker: summary + per-container details."""
    # Step 1: container list (fast, ~100ms)
    ps_out = _run(
        'docker ps -a --format "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}|{{.State}}|{{.CreatedAt}}" 2>/dev/null'
    )
    # Step 2: stats for running containers (already called, ~1-2s)
    stats_out = _run(
        'docker stats --no-stream --format "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}|{{.MemPerc}}" 2>/dev/null'
    )
    stats_map: dict[str, dict[str, Any]] = {}
    total_mb = 0.0
    for line in stats_out.split("\n"):
        if not line.strip() or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            name = parts[0].strip()
            mem_str = parts[1].split("/")[0].strip()
            mb = 0.0
            if "GiB" in mem_str:
                mb = float(re.sub(r"[A-Za-z ]", "", mem_str)) * 1024
            elif "MiB" in mem_str:
                mb = float(re.sub(r"[A-Za-z ]", "", mem_str))
            total_mb += mb
            stats_map[name] = {
                "mem_usage": parts[1].strip(),
                "cpu_pct": parts[2].strip().rstrip("%"),
                "mem_mb": round(mb),
            }

    containers: list[dict[str, Any]] = []
    for line in ps_out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        cid, name, image, status, ports, state, created = (
            parts[0], parts[1], parts[2], parts[3],
            parts[4], parts[5], parts[6],
        )
        health = ""
        if "(healthy)" in status:
            health = "healthy"
        elif "(unhealthy)" in status:
            health = "unhealthy"
        elif "(health: starting)" in status:
            health = "starting"

        s = stats_map.get(name, {})
        containers.append({
            "id": cid[:12],
            "name": name,
            "image": image.split("/")[-1] if "/" in image else image,
            "status": status,
            "state": state,
            "created": created,
            "ports": ports,
            "health": health,
            "mem_usage": s.get("mem_usage", "-"),
            "cpu_pct": s.get("cpu_pct", "0"),
            "mem_mb": s.get("mem_mb", 0),
        })

    running = sum(1 for c in containers if c["state"] == "running")
    return {
        "count": len(containers),
        "running": running,
        "total_mb": round(total_mb),
        "containers": sorted(
            containers,
            key=lambda c: (0 if c["state"] == "running" else 1, c["name"]),
        ),
    }


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


def _get_docker_logs(
    name: str, tail: int = 200, level: str | None = None, search: str | None = None
) -> dict[str, Any]:
    """Docker 컨테이너 로그 조회."""
    raw = _run(f"docker logs --tail {tail} --timestamps {name} 2>&1", timeout=15)
    logs: list[dict[str, Any]] = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        ts = ""
        msg = line
        if len(line) > 30 and line[4:5] == "-" and line[10:11] == "T":
            ts = line[:23].replace("T", " ")
            msg = line[31:].lstrip() if len(line) > 31 else ""
        lvl = "INFO"
        upper = msg[:100].upper()
        if "ERROR" in upper or "CRITICAL" in upper or "FATAL" in upper:
            lvl = "ERROR"
        elif "WARN" in upper:
            lvl = "WARNING"
        elif "DEBUG" in upper or "TRACE" in upper:
            lvl = "DEBUG"
        if level and level.upper() not in ("ALL", "") and lvl != level.upper():
            continue
        if search and search.lower() not in msg.lower():
            continue
        logs.append({"ts": ts, "level": lvl, "message": msg})
    return {"logs": logs, "total": len(logs), "container": name}


def _docker_log_html(container_name: str) -> str:
    """Docker 로그 뷰어 팝업 HTML."""
    return f'''<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><title>Docker Log — {container_name}</title>
<style>
:root{{--bg:#0c0e14;--card:#151821;--border:#1e2231;--text:#e8e8ec;--dim:#6b7084;
--red:#f04e53;--orange:#f0923e;--yellow:#e8c840;--green:#3dd68c;--blue:#4d9cf0}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'SF Mono',Menlo,Consolas,monospace;background:var(--bg);color:var(--text);font-size:12px;height:100vh;display:flex;flex-direction:column}}
.toolbar{{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--card);border-bottom:1px solid var(--border);flex-wrap:wrap}}
.toolbar h2{{font-size:14px;color:var(--blue);margin-right:12px;white-space:nowrap}}
.badge{{background:#1e2231;color:var(--dim);padding:2px 8px;border-radius:10px;font-size:11px}}
.btn{{padding:4px 10px;border:1px solid var(--border);border-radius:4px;background:var(--card);color:var(--text);cursor:pointer;font-size:11px;font-family:inherit}}
.btn:hover{{background:#1e2231;border-color:var(--blue)}}
.btn.active{{background:var(--blue);color:#fff;border-color:var(--blue)}}
.btn-group{{display:flex;gap:0}}
.btn-group .btn{{border-radius:0;margin-left:-1px}}
.btn-group .btn:first-child{{border-radius:4px 0 0 4px;margin-left:0}}
.btn-group .btn:last-child{{border-radius:0 4px 4px 0}}
.search-input{{padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);font-size:11px;font-family:inherit;width:180px}}
.search-input:focus{{outline:none;border-color:var(--blue)}}
.spacer{{flex:1}}
.toggle-label{{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--dim);cursor:pointer;white-space:nowrap}}
.log-container{{flex:1;overflow-y:auto;padding:2px 0}}
.log-line{{padding:1px 12px;display:flex;gap:0;white-space:pre-wrap;word-break:break-all;line-height:1.5;border-bottom:1px solid rgba(255,255,255,0.03)}}
.log-line:hover{{background:rgba(255,255,255,0.04)}}
.log-line .ts{{color:var(--dim);min-width:180px;flex-shrink:0}}
.log-line .lvl{{min-width:64px;flex-shrink:0;font-weight:bold}}
.log-line .msg{{flex:1}}
.lvl-DEBUG{{color:var(--dim)}}.lvl-INFO{{color:var(--green)}}.lvl-WARNING{{color:var(--yellow)}}.lvl-ERROR{{color:var(--red)}}
.log-line.hl-ERROR{{background:rgba(240,78,83,.08)}}.log-line.hl-WARNING{{background:rgba(232,200,64,.05)}}
.status-bar{{display:flex;justify-content:space-between;padding:4px 12px;background:var(--card);border-top:1px solid var(--border);font-size:10px;color:var(--dim)}}
.search-highlight{{background:rgba(77,156,240,.3);border-radius:2px}}
</style></head><body>
<div class="toolbar">
  <h2>{container_name}</h2>
  <span class="badge" id="log-count">0 lines</span>
  <div class="btn-group">
    <button class="btn active" data-level="ALL" onclick="setLvl(this)">ALL</button>
    <button class="btn" data-level="ERROR" onclick="setLvl(this)" style="color:var(--red)">ERR</button>
    <button class="btn" data-level="WARNING" onclick="setLvl(this)" style="color:var(--yellow)">WARN</button>
    <button class="btn" data-level="INFO" onclick="setLvl(this)" style="color:var(--green)">INFO</button>
    <button class="btn" data-level="DEBUG" onclick="setLvl(this)" style="color:var(--dim)">DBG</button>
  </div>
  <input class="search-input" id="search" placeholder="Search..." oninput="doSearch()"/>
  <span class="spacer"></span>
  <label class="toggle-label"><input type="checkbox" id="auto-scroll" checked/> Auto-scroll</label>
  <label class="toggle-label"><input type="checkbox" id="auto-refresh" checked onchange="toggleAR()"/> Auto-refresh</label>
  <button class="btn" onclick="fetchLogs()">Refresh</button>
</div>
<div class="log-container" id="lc"></div>
<div class="status-bar"><span id="st-l">Ready</span><span id="st-r"></span></div>
<script>
const CN='{container_name}';
let curLvl='ALL',curSearch='',rt=null;
function setLvl(b){{document.querySelectorAll('.btn-group .btn').forEach(x=>x.classList.remove('active'));b.classList.add('active');curLvl=b.dataset.level;fetchLogs()}}
function doSearch(){{curSearch=document.getElementById('search').value;fetchLogs()}}
function esc(s){{const d=document.createElement('div');d.textContent=s;return d.innerHTML}}
function hl(t,s){{if(!s)return esc(t);const e=esc(t),r=new RegExp('('+s.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi');return e.replace(r,'<span class="search-highlight">$1</span>')}}
async function fetchLogs(){{
  try{{
    const p=new URLSearchParams({{tail:'500'}});
    if(curLvl!=='ALL')p.set('level',curLvl);
    if(curSearch)p.set('search',curSearch);
    const r=await fetch('/api/docker-logs/'+CN+'?'+p);
    const d=await r.json();
    renderLogs(d.logs);
    document.getElementById('log-count').textContent=d.total+' lines';
    document.getElementById('st-l').textContent='Updated: '+new Date().toLocaleTimeString();
  }}catch(e){{document.getElementById('st-l').textContent='Error: '+e.message}}
}}
function renderLogs(logs){{
  const c=document.getElementById('lc');
  const atBot=c.scrollHeight-c.scrollTop-c.clientHeight<50;
  c.innerHTML='';
  for(const l of logs){{
    const div=document.createElement('div');
    div.className='log-line';
    if(l.level==='ERROR'||l.level==='WARNING')div.classList.add('hl-'+l.level);
    div.innerHTML='<span class="ts">'+esc(l.ts)+'</span><span class="lvl lvl-'+l.level+'">'+esc(l.level)+'</span><span class="msg">'+hl(l.message,curSearch)+'</span>';
    c.appendChild(div);
  }}
  if(document.getElementById('auto-scroll').checked||atBot)c.scrollTop=c.scrollHeight;
}}
function toggleAR(){{if(document.getElementById('auto-refresh').checked)startAR();else stopAR()}}
function startAR(){{stopAR();rt=setInterval(fetchLogs,3000);document.getElementById('st-r').textContent='Auto: 3s'}}
function stopAR(){{if(rt)clearInterval(rt);rt=null;document.getElementById('st-r').textContent='Auto: off'}}
fetchLogs();if(document.getElementById('auto-refresh').checked)startAR();
</script></body></html>'''


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
