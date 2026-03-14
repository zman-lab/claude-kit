"""collectors 모듈 테스트."""
import platform
from unittest.mock import patch, MagicMock

import pytest

from sysmon.collectors import get_collector


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
