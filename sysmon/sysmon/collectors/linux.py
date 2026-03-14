"""Linux 전용 시스템 메트릭 수집기."""
import os
import re
import time
from typing import Any

from .base import BaseCollector, _run


class LinuxCollector(BaseCollector):
    """/proc 파일시스템 기반 수집."""

    def collect_system(self) -> dict[str, Any]:
        cores = os.cpu_count() or 0
        mem = self._read_meminfo()
        # CPU 모델명
        chip = "Unknown"
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        chip = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
        return {
            "chip": chip,
            "cores": cores,
            "total_ram_gb": round(mem["MemTotal"] / 1024**2, 1),
        }

    def collect_quick(self) -> dict[str, Any]:
        """경량 CPU+RAM 스냅샷."""
        cores = os.cpu_count() or 1
        cpu_raw = _run("ps -A -o %cpu | awk 'NR>1{s+=$1}END{printf \"%.1f\",s}'")
        cpu_total = float(cpu_raw) if cpu_raw else 0.0
        cpu_pct = round(min(cpu_total / cores, 100), 1)

        mem = self._read_meminfo()
        total_gb = mem["MemTotal"] / 1024**2
        available_gb = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024**2
        used_gb = total_gb - available_gb
        ram_pct = round((used_gb / total_gb) * 100) if total_gb > 0 else 0

        return {
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
            "ram_used_gb": round(used_gb, 1),
            "ram_total_gb": round(total_gb, 1),
            "compressed_gb": 0.0,  # Linux에서는 zswap/zram 별도
            "ts": time.strftime("%H:%M:%S"),
        }

    def collect_cpu(self) -> dict[str, Any]:
        c: dict[str, Any] = {
            "user": 0.0, "sys": 0.0, "idle": 0.0,
            "load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0,
            "processes": 0, "threads": 0,
        }
        # /proc/stat에서 CPU 사용률
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()
            # user nice system idle iowait irq softirq
            user = int(parts[1]) + int(parts[2])
            system = int(parts[3])
            idle = int(parts[4])
            total = user + system + idle + int(parts[5]) + int(parts[6]) + int(parts[7])
            if total > 0:
                c["user"] = round(user / total * 100, 1)
                c["sys"] = round(system / total * 100, 1)
                c["idle"] = round(idle / total * 100, 1)
        except (OSError, IndexError, ValueError):
            pass

        # /proc/loadavg
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
            c["load_1m"] = float(parts[0])
            c["load_5m"] = float(parts[1])
            c["load_15m"] = float(parts[2])
            # 프로세스 수 (running/total)
            if "/" in parts[3]:
                c["processes"] = int(parts[3].split("/")[1])
        except (OSError, IndexError, ValueError):
            pass

        # 스레드 수
        thread_count = _run("ps -eo nlwp | awk 'NR>1{s+=$1}END{print s}'")
        c["threads"] = int(thread_count) if thread_count else 0

        return c

    def collect_memory(self) -> dict[str, Any]:
        mem = self._read_meminfo()
        total_gb = mem["MemTotal"] / 1024**2
        free_gb = mem.get("MemFree", 0) / 1024**2
        available_gb = mem.get("MemAvailable", free_gb) / 1024**2
        buffers_gb = mem.get("Buffers", 0) / 1024**2
        cached_gb = mem.get("Cached", 0) / 1024**2
        active_gb = mem.get("Active", 0) / 1024**2
        inactive_gb = mem.get("Inactive", 0) / 1024**2
        swap_total = mem.get("SwapTotal", 0) / 1024**2
        swap_free = mem.get("SwapFree", 0) / 1024**2
        used_gb = total_gb - available_gb

        return {
            "total_gb": round(total_gb, 1),
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 2),
            "active_gb": round(active_gb, 1),
            "inactive_gb": round(inactive_gb, 1),
            "wired_gb": round(buffers_gb + cached_gb, 1),  # buffers+cached ≈ wired 역할
            "compressed_gb": 0.0,
            "pressure_pct": round((used_gb / total_gb) * 100) if total_gb > 0 else 0,
            "swap_ins": 0,  # /proc/vmstat에서 읽을 수 있지만 단순화
            "swap_outs": 0,
        }

    def collect_disk(self) -> dict[str, Any]:
        out = _run("df -h / 2>/dev/null")
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
    def _read_meminfo() -> dict[str, int]:
        """/proc/meminfo → {이름: kB값} 딕셔너리."""
        info: dict[str, int] = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        info[key] = int(parts[1])
        except OSError:
            pass
        return info

    @staticmethod
    def _parse_size(s: str) -> float:
        """df 출력의 크기 문자열 → float (단위 제거)."""
        return float(re.sub(r"[A-Za-z]", "", s) or 0)
