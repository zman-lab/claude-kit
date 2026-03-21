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


class TestLaunchdAction:
    """launchd_disable_* / launchd_enable_* 액션 테스트."""

    def test_disable_normal_label(self):
        """일반 레이블을 disable하면 launchctl이 호출되고 로그에 완료 메시지가 있어야 한다."""
        runner = ActionRunner()
        label = "com.example.myapp"

        with patch("sysmon.actions.subprocess.run") as mock_proc:
            mock_proc.return_value.returncode = 0
            mock_proc.return_value.stderr = ""
            mock_proc.return_value.stdout = ""
            result = runner.run(f"launchd_disable_{label}")

        assert result["success"] is True
        logs_text = "\n".join(result["logs"])
        assert "비활성화" in logs_text
        assert "재부팅" in logs_text
        # launchctl disable 명령이 호출되었는지 확인
        called_cmd = mock_proc.call_args[1].get("args") or mock_proc.call_args[0][0]
        assert "disable" in called_cmd
        assert label in called_cmd

    def test_enable_normal_label(self):
        """일반 레이블을 enable하면 launchctl이 호출되고 로그에 완료 메시지가 있어야 한다."""
        runner = ActionRunner()
        label = "com.example.myapp"

        with patch("sysmon.actions.subprocess.run") as mock_proc:
            mock_proc.return_value.returncode = 0
            mock_proc.return_value.stderr = ""
            mock_proc.return_value.stdout = ""
            result = runner.run(f"launchd_enable_{label}")

        assert result["success"] is True
        logs_text = "\n".join(result["logs"])
        assert "활성화" in logs_text
        assert "재부팅" in logs_text
        called_cmd = mock_proc.call_args[1].get("args") or mock_proc.call_args[0][0]
        assert "enable" in called_cmd
        assert label in called_cmd

    def test_protected_label_rejected(self):
        """보호 대상 레이블(com.claude-sysmon)은 변경을 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("launchd_disable_com.claude-sysmon")
        logs_text = "\n".join(result["logs"])
        assert "보호 대상" in logs_text

    def test_security_pattern_label_rejected(self):
        """security 패턴을 포함하는 레이블은 변경을 거부해야 한다."""
        runner = ActionRunner()
        # _SECURITY_PATTERNS에 "broadcom"이 있으므로 이를 포함한 레이블은 거부
        result = runner.run("launchd_disable_com.broadcom.antivirus")
        logs_text = "\n".join(result["logs"])
        assert "보안 서비스" in logs_text

    def test_empty_label_rejected(self):
        """빈 레이블은 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("launchd_disable_")
        logs_text = "\n".join(result["logs"])
        assert "비어있습니다" in logs_text

    def test_launchctl_failure_logged(self):
        """launchctl 명령 실패 시 에러 메시지가 로그에 포함되어야 한다."""
        runner = ActionRunner()
        label = "com.example.myapp"

        with patch("sysmon.actions.subprocess.run") as mock_proc:
            mock_proc.return_value.returncode = 1
            mock_proc.return_value.stderr = "No such process"
            mock_proc.return_value.stdout = ""
            result = runner.run(f"launchd_disable_{label}")

        logs_text = "\n".join(result["logs"])
        assert "실패" in logs_text

    def test_result_has_duration_ms(self):
        """결과에 duration_ms 필드가 있어야 한다."""
        runner = ActionRunner()
        result = runner.run("launchd_disable_")
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], (int, float))
        assert result["duration_ms"] >= 0

    def test_launchd_invalid_label_rejected(self):
        """쉘 메타문자가 포함된 레이블은 인젝션 방지를 위해 거부해야 한다."""
        runner = ActionRunner()
        result = runner.run("launchd_disable_com.test; rm -rf /")
        assert any("유효하지 않은" in l for l in result["logs"])
