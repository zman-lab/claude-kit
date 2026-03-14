"""actions 모듈 테스트."""
from unittest.mock import patch

from sysmon.actions import ActionRunner


class TestKillAllMcp:
    def test_kill_all_mcp_returns_logs(self):
        runner = ActionRunner()
        with patch("sysmon.actions._run") as mock_run:
            mock_run.return_value = "0"
            result = runner.run("kill_all_mcp")
        assert "logs" in result
        assert isinstance(result["logs"], list)

    def test_action_duration(self):
        runner = ActionRunner()
        with patch("sysmon.actions._run") as mock_run:
            mock_run.return_value = "0"
            result = runner.run("kill_all_mcp")
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], (int, float))
        assert result["duration_ms"] >= 0


class TestPurgeAction:
    def test_purge_without_password(self):
        runner = ActionRunner()
        result = runner.run("purge_cache")
        logs_text = "\n".join(result["logs"])
        assert "비밀번호" in logs_text


class TestUnknownAction:
    def test_unknown_action(self):
        runner = ActionRunner()
        result = runner.run("nonexistent_action_xyz")
        logs_text = "\n".join(result["logs"])
        assert "알 수 없는" in logs_text
