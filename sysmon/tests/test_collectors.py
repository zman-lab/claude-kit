"""collectors 모듈 테스트."""
import io
import platform
import plistlib
import tempfile
import os
from unittest.mock import patch, MagicMock

import pytest

from sysmon.collectors import get_collector
from sysmon.collectors.base import (
    _classify_process,
    _build_process_list,
    _scan_launchd_services,
    _SECURITY_PATTERNS,
    _SYSMON_PROCESS_PATTERNS,
)


class TestGetCollector:
    """get_collector()가 플랫폼에 맞는 collector를 반환하는지 테스트."""

    def test_get_collector_returns_platform_specific(self):
        """platform.system()에 따라 맞는 collector 타입을 반환해야 한다."""
        collector = get_collector()
        system = platform.system()

        if system == "Darwin":
            from sysmon.collectors.darwin import DarwinCollector
            assert isinstance(collector, DarwinCollector)
        elif system == "Linux":
            from sysmon.collectors.linux import LinuxCollector
            assert isinstance(collector, LinuxCollector)
        else:
            pytest.skip(f"지원하지 않는 플랫폼: {system}")


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS 전용 테스트")
class TestDarwinCollector:
    """macOS DarwinCollector 테스트."""

    def setup_method(self):
        from sysmon.collectors.darwin import DarwinCollector
        self.collector = DarwinCollector()

    def test_darwin_collect_quick(self):
        """collect_quick()은 cpu_pct, ram_pct 키를 포함해야 한다."""
        result = self.collector.collect_quick()
        assert "cpu_pct" in result
        assert "ram_pct" in result
        # 값 범위 확인: 0~100
        assert 0 <= result["cpu_pct"] <= 100
        assert 0 <= result["ram_pct"] <= 100

    def test_darwin_collect_system(self):
        """collect_system()은 cores > 0, total_ram_gb > 0이어야 한다."""
        result = self.collector.collect_system()
        assert result["cores"] > 0
        assert result["total_ram_gb"] > 0

    def test_darwin_collect_memory(self):
        """collect_memory()의 pressure_pct는 0~100 범위여야 한다."""
        result = self.collector.collect_memory()
        assert 0 <= result["pressure_pct"] <= 100

    def test_darwin_collect_disk(self):
        """collect_disk()의 total_gb는 0보다 커야 한다."""
        result = self.collector.collect_disk()
        assert result["total_gb"] > 0


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
class TestLinuxCollectorMocked:
    """Linux collector를 subprocess mock으로 테스트."""

    def test_linux_collect_quick(self):
        """mock된 subprocess로 LinuxCollector.collect_quick() 테스트."""
        # LinuxCollector import를 platform 체크 우회하여 수행
        with patch("platform.system", return_value="Linux"):
            from sysmon.collectors.linux import LinuxCollector

        collector = LinuxCollector()

        # /proc/stat CPU 데이터 mock
        cpu_stat = "cpu  100 0 50 800 10 0 0 0 0 0\n"
        # /proc/meminfo 데이터 mock
        meminfo = (
            "MemTotal:       16384000 kB\n"
            "MemAvailable:    8192000 kB\n"
        )

        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            mock_result.returncode = 0

            if isinstance(cmd, list):
                cmd_str = " ".join(cmd)
            else:
                cmd_str = str(cmd)

            if "/proc/stat" in cmd_str or "mpstat" in cmd_str:
                mock_result.stdout = "15.0"
            elif "/proc/meminfo" in cmd_str or "free" in cmd_str:
                mock_result.stdout = "50.0"
            else:
                mock_result.stdout = ""

            return mock_result

        with patch("subprocess.run", side_effect=mock_run):
            result = collector.collect_quick()

        assert "cpu_pct" in result
        assert "ram_pct" in result
        assert isinstance(result["cpu_pct"], (int, float))
        assert isinstance(result["ram_pct"], (int, float))


# ─── _classify_process 테스트 ───

class TestClassifyProcess:
    """base.py의 _classify_process() 함수 테스트."""

    def test_security_pattern_is_protected(self):
        """보안 소프트웨어 패턴은 protected=True를 반환해야 한다."""
        cat, protected = _classify_process(
            "/Library/Application Support/com.broadcom.antivirus/agent"
        )
        assert cat == "security"
        assert protected is True

    def test_chrome_pattern_not_protected(self):
        """Chrome 브라우저는 protected=False를 반환해야 한다."""
        cat, protected = _classify_process(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        assert cat == "chrome"
        assert protected is False

    def test_docker_pattern_not_protected(self):
        """Docker 가상화 프로세스는 protected=False를 반환해야 한다."""
        cat, protected = _classify_process(
            "/Applications/Docker.app/Contents/MacOS/com.docker.backend"
        )
        assert cat == "docker"
        assert protected is False

    def test_sysmon_process_is_protected(self):
        """sysmon 자기 자신은 protected=True를 반환해야 한다."""
        cat, protected = _classify_process(
            "/usr/bin/uvicorn sysmon.server:app --port 8000"
        )
        assert cat == "other"
        assert protected is True

    def test_unknown_process_is_other(self):
        """분류 규칙에 없는 프로세스는 ('other', False)를 반환해야 한다."""
        cat, protected = _classify_process("/usr/bin/unknown-custom-app")
        assert cat == "other"
        assert protected is False

    def test_case_insensitive_matching(self):
        """패턴 매칭은 대소문자를 구분하지 않아야 한다."""
        cat_lower, _ = _classify_process("/applications/google chrome/chrome")
        cat_upper, _ = _classify_process("/Applications/Google Chrome/Chrome")
        assert cat_lower == cat_upper

    def test_ide_pattern(self):
        """JetBrains/Cursor IDE 패턴은 ide 카테고리를 반환해야 한다."""
        cat, protected = _classify_process(
            "/Applications/Cursor.app/Contents/MacOS/Cursor"
        )
        assert cat == "ide"
        assert protected is False

    def test_system_pattern(self):
        """macOS 시스템 프로세스는 system 카테고리를 반환해야 한다."""
        cat, protected = _classify_process("/System/Library/CoreServices/Finder.app")
        assert cat == "system"
        assert protected is False


# ─── _build_process_list 테스트 ───

class TestBuildProcessList:
    """base.py의 _build_process_list() 함수 테스트."""

    def _make_proc(self, pid: str, cmd: str, rss_mb: float, ppid: str = "1") -> dict:
        return {"pid": pid, "ppid": ppid, "cmd": cmd, "rss_mb": rss_mb}

    def test_basic_fields_present(self):
        """반환 항목에 pid, ppid, cmd, rss_mb, category, protected 필드가 있어야 한다."""
        procs = [self._make_proc("100", "/usr/bin/some-app --flag", 50.0)]
        result = _build_process_list(procs, [])
        assert len(result) == 1
        entry = result[0]
        for field in ("pid", "ppid", "cmd", "rss_mb", "category", "protected"):
            assert field in entry, f"필드 누락: {field}"

    def test_mcp_pids_excluded(self):
        """MCP PID 목록에 포함된 프로세스는 결과에서 제외해야 한다."""
        procs = [
            self._make_proc("200", "/usr/bin/mcp-server", 30.0),
            self._make_proc("201", "/usr/bin/other-app", 30.0),
        ]
        result = _build_process_list(procs, mcp_pids=["200"])
        pids = [p["pid"] for p in result]
        assert "200" not in pids
        assert "201" in pids

    def test_claude_processes_excluded(self):
        """'claude'가 cmd에 포함된 프로세스는 결과에서 제외해야 한다."""
        procs = [
            self._make_proc("300", "/usr/local/bin/claude --model opus", 100.0),
            self._make_proc("301", "/usr/bin/vim", 20.0),
        ]
        result = _build_process_list(procs, [])
        pids = [p["pid"] for p in result]
        assert "300" not in pids
        assert "301" in pids

    def test_security_process_is_protected(self):
        """security 패턴 프로세스는 protected=True를 가져야 한다."""
        procs = [
            self._make_proc(
                "400",
                "/Library/Application Support/com.broadcom.antivirus/agent",
                200.0,
            )
        ]
        result = _build_process_list(procs, [])
        assert result[0]["protected"] is True
        assert result[0]["category"] == "security"

    def test_normal_process_not_protected(self):
        """일반 프로세스는 protected=False를 가져야 한다."""
        procs = [self._make_proc("500", "/usr/bin/vim", 15.0)]
        result = _build_process_list(procs, [])
        assert result[0]["protected"] is False

    def test_empty_procs(self):
        """빈 프로세스 목록은 빈 리스트를 반환해야 한다."""
        result = _build_process_list([], [])
        assert result == []

    def test_ppid_defaults_to_empty_string_when_missing(self):
        """ppid 필드가 없는 프로세스는 ppid가 빈 문자열로 처리되어야 한다."""
        proc = {"pid": "600", "cmd": "/usr/bin/noppid-app", "rss_mb": 10.0}
        result = _build_process_list([proc], [])
        assert result[0]["ppid"] == ""

    def test_multiple_mcp_and_claude_excluded(self):
        """여러 MCP PID와 claude 프로세스가 동시에 제외되어야 한다."""
        procs = [
            self._make_proc("701", "/usr/bin/mcp-a", 10.0),
            self._make_proc("702", "/usr/bin/mcp-b", 10.0),
            self._make_proc("703", "/opt/claude-code/bin/claude", 80.0),
            self._make_proc("704", "/usr/bin/firefox", 150.0),
        ]
        result = _build_process_list(procs, mcp_pids=["701", "702"])
        pids = [p["pid"] for p in result]
        assert pids == ["704"]


# ─── _SECURITY_PATTERNS / _SYSMON_PROCESS_PATTERNS 상수 테스트 ───

class TestPatternConstants:
    """공개 상수가 올바르게 초기화되는지 확인."""

    def test_security_patterns_not_empty(self):
        """_SECURITY_PATTERNS는 비어있지 않아야 한다."""
        assert len(_SECURITY_PATTERNS) > 0

    def test_security_patterns_contains_broadcom(self):
        """_SECURITY_PATTERNS에는 'broadcom' 패턴이 포함되어야 한다."""
        assert any("broadcom" in pat.lower() for pat in _SECURITY_PATTERNS)

    def test_sysmon_process_patterns_not_empty(self):
        """_SYSMON_PROCESS_PATTERNS는 비어있지 않아야 한다."""
        assert len(_SYSMON_PROCESS_PATTERNS) > 0

    def test_sysmon_process_patterns_contains_uvicorn(self):
        """_SYSMON_PROCESS_PATTERNS에 'uvicorn'이 포함되어야 한다."""
        assert "uvicorn" in _SYSMON_PROCESS_PATTERNS


# ─── collect_all() processes 필드 통합 테스트 ───

@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS 전용 테스트")
class TestCollectAllProcesses:
    """collect_all()이 processes 키를 올바르게 반환하는지 확인."""

    def setup_method(self):
        from sysmon.collectors.darwin import DarwinCollector
        self.collector = DarwinCollector()

    def test_collect_all_has_processes_key(self):
        """collect_all() 결과에 'processes' 키가 있어야 한다."""
        result = self.collector.collect_all()
        assert "processes" in result

    def test_collect_all_processes_is_list(self):
        """collect_all()의 'processes' 값은 리스트여야 한다."""
        result = self.collector.collect_all()
        assert isinstance(result["processes"], list)

    def test_collect_all_processes_entry_structure(self):
        """processes 리스트의 각 항목에 필수 필드가 있어야 한다."""
        result = self.collector.collect_all()
        for entry in result["processes"]:
            for field in ("pid", "cmd", "rss_mb", "category", "protected"):
                assert field in entry, f"필드 누락: {field}"

    def test_collect_all_processes_no_claude_entries(self):
        """processes 리스트에 'claude' 프로세스가 포함되지 않아야 한다."""
        result = self.collector.collect_all()
        for entry in result["processes"]:
            assert "claude" not in entry["cmd"].lower(), (
                f"claude 프로세스가 포함됨: {entry['cmd']}"
            )

    def test_collect_all_has_launchd_services_key(self):
        """collect_all() 결과에 'launchd_services' 키가 있어야 한다."""
        result = self.collector.collect_all()
        assert "launchd_services" in result

    def test_collect_all_launchd_services_is_list(self):
        """collect_all()의 'launchd_services' 값은 리스트여야 한다."""
        result = self.collector.collect_all()
        assert isinstance(result["launchd_services"], list)

    def test_collect_all_processes_have_launchd_fields(self):
        """processes 항목에 launchd_label, launchd_disabled 필드가 있어야 한다."""
        result = self.collector.collect_all()
        for entry in result["processes"]:
            assert "launchd_label" in entry, f"launchd_label 필드 누락: {entry}"
            assert "launchd_disabled" in entry, f"launchd_disabled 필드 누락: {entry}"


# ─── _scan_launchd_services 테스트 ───

@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS 전용 테스트")
class TestScanLaunchdServices:
    """base.py의 _scan_launchd_services() 함수 테스트."""

    def _make_plist_bytes(self, label: str, program: str = "/usr/bin/app") -> bytes:
        """테스트용 plist 바이트 생성."""
        data = {"Label": label, "Program": program}
        return plistlib.dumps(data)

    def test_returns_list(self):
        """정상 케이스: 리스트를 반환해야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 더미 plist 생성
            plist_path = os.path.join(tmpdir, "com.test.myapp.plist")
            with open(plist_path, "wb") as fh:
                fh.write(self._make_plist_bytes("com.test.myapp"))

            with patch("sysmon.collectors.base._run") as mock_run:
                mock_run.return_value = ""  # launchctl list / print-disabled 빈 출력
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        assert isinstance(result, list)
        assert len(result) == 1
        entry = result[0]
        assert entry["label"] == "com.test.myapp"
        assert entry["program"] == "/usr/bin/app"
        assert entry["running"] is False
        assert entry["disabled"] is False

    def test_running_service_detected(self):
        """launchctl list에 PID가 있으면 running=True로 표시해야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plist_path = os.path.join(tmpdir, "com.test.running.plist")
            with open(plist_path, "wb") as fh:
                fh.write(self._make_plist_bytes("com.test.running"))

            def mock_run(cmd: str, timeout: int = 10) -> str:
                if "launchctl list" in cmd:
                    return "1234\t0\tcom.test.running"
                return ""

            with patch("sysmon.collectors.base._run", side_effect=mock_run):
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        assert len(result) == 1
        assert result[0]["running"] is True
        assert result[0]["pid"] == "1234"

    def test_disabled_service_detected(self):
        """launchctl print-disabled에서 true로 표시된 서비스는 disabled=True여야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plist_path = os.path.join(tmpdir, "com.test.disabled.plist")
            with open(plist_path, "wb") as fh:
                fh.write(self._make_plist_bytes("com.test.disabled"))

            def mock_run(cmd: str, timeout: int = 10) -> str:
                if "print-disabled" in cmd:
                    return '"com.test.disabled" => true'
                return ""

            with patch("sysmon.collectors.base._run", side_effect=mock_run):
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        assert len(result) == 1
        assert result[0]["disabled"] is True

    def test_plist_parse_failure_skipped(self):
        """plist 파싱 실패 시 해당 항목을 스킵하고 다른 항목은 정상 처리해야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 유효한 plist
            good_path = os.path.join(tmpdir, "com.test.good.plist")
            with open(good_path, "wb") as fh:
                fh.write(self._make_plist_bytes("com.test.good"))

            # 깨진 plist (텍스트로 덮어씀)
            bad_path = os.path.join(tmpdir, "com.test.bad.plist")
            with open(bad_path, "w") as fh:
                fh.write("this is not a valid plist !@#$")

            with patch("sysmon.collectors.base._run", return_value=""):
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        labels = [s["label"] for s in result]
        assert "com.test.good" in labels
        assert "com.test.bad" not in labels

    def test_no_label_in_plist_skipped(self):
        """Label 키 없는 plist는 스킵해야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plist_path = os.path.join(tmpdir, "nolabel.plist")
            with open(plist_path, "wb") as fh:
                fh.write(plistlib.dumps({"Program": "/usr/bin/nolabel"}))

            with patch("sysmon.collectors.base._run", return_value=""):
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        assert result == []

    def test_program_from_program_arguments(self):
        """Program 키 없이 ProgramArguments만 있는 경우 첫 번째 요소를 program으로 사용해야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plist_path = os.path.join(tmpdir, "com.test.args.plist")
            data = {
                "Label": "com.test.args",
                "ProgramArguments": ["/usr/local/bin/myapp", "--flag"],
            }
            with open(plist_path, "wb") as fh:
                fh.write(plistlib.dumps(data))

            with patch("sysmon.collectors.base._run", return_value=""):
                with patch("os.path.expanduser", return_value=tmpdir):
                    result = _scan_launchd_services()

        assert len(result) == 1
        assert result[0]["program"] == "/usr/local/bin/myapp"

    def test_linux_returns_empty_list(self):
        """Linux 환경에서는 빈 리스트를 반환해야 한다."""
        with patch("platform.system", return_value="Linux"):
            result = _scan_launchd_services()
        assert result == []


# ─── _build_process_list launchd 매핑 테스트 ───

class TestBuildProcessListLaunchd:
    """_build_process_list()의 launchd 매핑 기능 테스트."""

    def _make_proc(self, pid: str, cmd: str, rss_mb: float) -> dict:
        return {"pid": pid, "ppid": "1", "cmd": cmd, "rss_mb": rss_mb}

    def test_launchd_fields_present_when_no_services(self):
        """launchd_services가 없을 때도 launchd_label/launchd_disabled 필드가 있어야 한다."""
        procs = [self._make_proc("100", "/usr/bin/app", 50.0)]
        result = _build_process_list(procs, [])
        assert "launchd_label" in result[0]
        assert "launchd_disabled" in result[0]
        assert result[0]["launchd_label"] == ""
        assert result[0]["launchd_disabled"] is False

    def test_launchd_pid_matched(self):
        """launchd 서비스 PID가 프로세스 PID와 일치하면 launchd_label이 매핑되어야 한다."""
        procs = [self._make_proc("200", "/usr/bin/myapp", 30.0)]
        services = [
            {"label": "com.test.myapp", "pid": "200", "running": True,
             "disabled": False, "program": "/usr/bin/myapp", "plist_path": "/tmp/x.plist"}
        ]
        result = _build_process_list(procs, [], launchd_services=services)
        assert result[0]["launchd_label"] == "com.test.myapp"
        assert result[0]["launchd_disabled"] is False

    def test_launchd_disabled_flag_propagated(self):
        """launchd 서비스가 disabled=True이면 launchd_disabled=True로 매핑해야 한다."""
        procs = [self._make_proc("300", "/usr/bin/disabledapp", 20.0)]
        services = [
            {"label": "com.test.disabled", "pid": "300", "running": True,
             "disabled": True, "program": "/usr/bin/disabledapp", "plist_path": "/tmp/y.plist"}
        ]
        result = _build_process_list(procs, [], launchd_services=services)
        assert result[0]["launchd_disabled"] is True
