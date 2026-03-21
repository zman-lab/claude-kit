"""actions 모듈 테스트."""
import os
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


class TestKillProcess:
    """kill_process_<pid> 액션 테스트."""

    def test_kill_process_success_sigterm(self):
        """SIGTERM으로 정상 종료되는 경우."""
        runner = ActionRunner()
        fake_pid = "12345"

        def mock_run(cmd: str, timeout: int = 10) -> str:
            if "ps -p" in cmd and "-o command=" in cmd:
                return "/usr/bin/some-app"
            if "ps -p" in cmd and "-o pid=" in cmd:
                return ""  # SIGTERM 후 프로세스 사라짐
            return ""

        with patch("sysmon.actions._run", side_effect=mock_run):
            result = runner.run(f"kill_process_{fake_pid}")
        logs_text = "\n".join(result["logs"])
        assert "SIGTERM" in logs_text
        assert "보호" not in logs_text

    def test_kill_process_invalid_pid_nonnumeric(self):
        """숫자가 아닌 PID는 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_abc")
        logs_text = "\n".join(result["logs"])
        assert "유효하지 않은" in logs_text

    def test_kill_process_self_pid_rejected(self):
        """sysmon 자신의 PID(os.getpid())는 종료를 거부해야 한다."""
        runner = ActionRunner()
        self_pid = str(os.getpid())
        result = runner.run(f"kill_process_{self_pid}")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    def test_kill_process_security_pattern_rejected(self):
        """security 카테고리(broadcom 등) 프로세스는 종료를 거부해야 한다."""
        runner = ActionRunner()
        fake_pid = "99999"

        def mock_run(cmd: str, timeout: int = 10) -> str:
            if "ps -p" in cmd and "-o command=" in cmd:
                return "/Library/Application Support/com.broadcom.antivirus/agent"
            return ""

        with patch("sysmon.actions._run", side_effect=mock_run):
            result = runner.run(f"kill_process_{fake_pid}")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    def test_kill_process_not_found(self):
        """존재하지 않는 PID는 '찾을 수 없습니다' 메시지를 반환해야 한다."""
        runner = ActionRunner()
        fake_pid = "99998"

        def mock_run(cmd: str, timeout: int = 10) -> str:
            # ps -p → 빈 문자열 = 프로세스 없음
            return ""

        with patch("sysmon.actions._run", side_effect=mock_run):
            result = runner.run(f"kill_process_{fake_pid}")
        logs_text = "\n".join(result["logs"])
        assert "찾을 수 없습니다" in logs_text

    def test_kill_process_sigkill_fallback(self):
        """SIGTERM 후 살아있으면 SIGKILL로 강제 종료해야 한다."""
        runner = ActionRunner()
        fake_pid = "12346"

        def mock_run(cmd: str, timeout: int = 10) -> str:
            if "ps -p" in cmd and "-o command=" in cmd:
                return "/usr/bin/stubborn-app"
            if "ps -p" in cmd and "-o pid=" in cmd:
                return fake_pid  # SIGTERM 후에도 살아있음
            return ""

        with patch("sysmon.actions._run", side_effect=mock_run):
            with patch("sysmon.actions.time.sleep"):  # sleep 스킵
                result = runner.run(f"kill_process_{fake_pid}")
        logs_text = "\n".join(result["logs"])
        assert "SIGKILL" in logs_text

    # ─── 경계값 테스트 ───

    def test_kill_process_pid_zero_rejected(self):
        """PID=0은 시스템 보호 대상으로 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_0")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    def test_kill_process_pid_one_rejected(self):
        """PID=1 (launchd/init)은 시스템 보호 대상으로 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_1")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    def test_kill_process_parent_pid_rejected(self):
        """sysmon 부모 프로세스(os.getppid())는 종료를 거부해야 한다."""
        runner = ActionRunner()
        parent_pid = str(os.getppid())
        result = runner.run(f"kill_process_{parent_pid}")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    # ─── 엣지케이스 테스트 ───

    def test_kill_process_negative_number_rejected(self):
        """음수 PID는 isdigit() 검사에 의해 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_-999")
        logs_text = "\n".join(result["logs"])
        assert "유효하지 않은" in logs_text

    def test_kill_process_empty_pid_rejected(self):
        """빈 PID 문자열은 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_")
        logs_text = "\n".join(result["logs"])
        assert "유효하지 않은" in logs_text

    def test_kill_process_result_has_duration_ms(self):
        """결과에 duration_ms 필드가 있어야 한다."""
        runner = ActionRunner()
        result = runner.run("kill_process_abc")
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], (int, float))
        assert result["duration_ms"] >= 0
