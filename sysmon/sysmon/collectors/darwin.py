"""macOS (Darwin) 전용 시스템 메트릭 수집기."""
import re
import time
from typing import Any

from .base import BaseCollector, _run


class DarwinCollector(BaseCollector):
    """macOS sysctl / vm_stat / top / ps 기반 수집."""

    def collect_system(self) -> dict[str, Any]:
        cores = int(_run("sysctl -n hw.ncpu") or "0")
        mem = int(_run("sysctl -n hw.memsize") or "0")
        chip = _run("sysctl -n machdep.cpu.brand_string") or "Unknown"
        return {
            "chip": chip,
            "cores": cores,
            "total_ram_gb": round(mem / 1024**3, 1),
        }

    def collect_quick(self) -> dict[str, Any]:
        """경량 CPU+RAM 스냅샷 (<200ms)."""
        cores = int(_run("sysctl -n hw.ncpu") or "1")
        cpu_raw = _run("ps -A -o %cpu | awk 'NR>1{s+=$1}END{printf \"%.1f\",s}'")
        cpu_total = float(cpu_raw) if cpu_raw else 0.0
        cpu_pct = round(min(cpu_total / cores, 100), 1)

        pages = self._parse_vm_stat()
        ps = 16384  # macOS 페이지 크기
        total = int(_run("sysctl -n hw.memsize") or "0") / 1024**3
        free = pages.get("free", 0) * ps / 1024**3
        compressed = pages.get("occupied by compressor", 0) * ps / 1024**3
        used = total - free
        ram_pct = round((used / total) * 100) if total > 0 else 0

        return {
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
            "ram_used_gb": round(used, 1),
            "ram_total_gb": round(total, 1),
            "compressed_gb": round(compressed, 1),
            "ts": time.strftime("%H:%M:%S"),
        }

    def collect_cpu(self) -> dict[str, Any]:
        out = _run("top -l 1 -s 0 | head -12")
        c: dict[str, Any] = {
            "user": 0.0, "sys": 0.0, "idle": 0.0,
            "load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0,
            "processes": 0, "threads": 0,
        }
        for line in out.split("\n"):
            if "CPU usage" in line:
                for val, key in re.findall(r"([\d.]+)%\s+(user|sys|idle)", line):
                    c[key] = float(val)
            if "Load Avg" in line:
                m = re.findall(r"[\d.]+", line)
                if len(m) >= 3:
                    c["load_1m"] = float(m[0])
                    c["load_5m"] = float(m[1])
                    c["load_15m"] = float(m[2])
            if "Processes:" in line:
                m = re.search(r"(\d+)\s+total.*?(\d+)\s+threads", line)
                if m:
                    c["processes"] = int(m.group(1))
                    c["threads"] = int(m.group(2))
        return c

    def collect_memory(self) -> dict[str, Any]:
        pages = self._parse_vm_stat()
        ps = 16384
        total = int(_run("sysctl -n hw.memsize") or "0") / 1024**3
        free = pages.get("free", 0) * ps / 1024**3
        active = pages.get("active", 0) * ps / 1024**3
        inactive = pages.get("inactive", 0) * ps / 1024**3
        wired = pages.get("wired down", 0) * ps / 1024**3
        compressed = pages.get("occupied by compressor", 0) * ps / 1024**3
        used = total - free

        swap_out = _run("vm_stat | grep 'Swapouts'")
        swap_in = _run("vm_stat | grep 'Swapins'")
        so = self._extract_int(swap_out)
        si = self._extract_int(swap_in)

        return {
            "total_gb": round(total, 1),
            "used_gb": round(used, 1),
            "free_gb": round(free, 2),
            "active_gb": round(active, 1),
            "inactive_gb": round(inactive, 1),
            "wired_gb": round(wired, 1),
            "compressed_gb": round(compressed, 1),
            "pressure_pct": round((used / total) * 100) if total > 0 else 0,
            "swap_ins": si,
            "swap_outs": so,
        }

    def collect_disk(self) -> dict[str, Any]:
        out = _run("df -h /System/Volumes/Data 2>/dev/null || df -h /")
        for line in out.split("\n"):
            if "/dev/" not in line:
                continue
            parts = line.split()
            return {
                "total_gb": round(self._parse_size(parts[1])),
                "used_gb": round(self._parse_size(parts[2])),
                "free_gb": round(self._parse_size(parts[3])),
                "pct": int(parts[4].replace("%", "")) if "%" in parts[4] else 0,
            }
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "pct": 0}

    def collect_processes(self) -> list[dict[str, Any]]:
        out = _run("ps -eo rss,pid,ppid,command")
        procs: list[dict[str, Any]] = []
        for line in out.split("\n")[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            rss_mb = int(parts[0]) / 1024
            if rss_mb < 5:
                continue
            procs.append({
                "rss_mb": round(rss_mb),
                "pid": parts[1],
                "ppid": parts[2],
                "cmd": parts[3],
            })
        return procs

    # ── 내부 헬퍼 ──

    @staticmethod
    def _parse_vm_stat() -> dict[str, int]:
        """vm_stat 출력을 파싱하여 {이름: 페이지수} 딕셔너리 반환."""
        out = _run("vm_stat")
        pages: dict[str, int] = {}
        for line in out.split("\n"):
            m = re.match(r"Pages\s+(.+?):\s+([\d.]+)", line)
            if m:
                pages[m.group(1).strip().rstrip(".")] = int(m.group(2).rstrip("."))
        return pages

    @staticmethod
    def _extract_int(text: str) -> int:
        """문자열에서 첫 번째 정수를 추출. 없으면 0."""
        if not text:
            return 0
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _parse_size(s: str) -> float:
        """df 출력의 크기 문자열 → float (단위 제거)."""
        return float(re.sub(r"[A-Za-z]", "", s) or 0)
