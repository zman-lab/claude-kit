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


# 2026-09-11 실측 ps 출력을 그대로 쓴 픽스처.
# VS Code 가 Gatekeeper 격리(AppTranslocation)로 임시 경로에서 돌다가 부모가 죽어
# PPID=1 고아가 된 상태. 합계 CPU 965% 로 11코어 맥북 로드가 84 까지 올라갔다.
_SWEEP_PS_FIXTURE = """  PID  PPID STAT %CPU   RSS COMMAND
41881     1 R    443.4 40000 /private/var/folders/jx/T/AppTranslocation/B815A7CC/d/Visual Studio Code.app/Contents/MacOS/Electron
42013     1 R    344.6 10000 /private/var/folders/jx/T/AppTranslocation/B815A7CC/d/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper
41924     1 R    151.3  5000 /var/folders/jx/T/AppTranslocation/B815A7CC/d/Visual Studio Code.app/Contents/Frameworks/Electron Framework.framework/Helpers/chrome_crashpad_handler
  349     1 R     24.0 170000 /Library/SystemExtensions/78BBD058/com.broadcom.mes.systemextension/Contents/MacOS/com.broadcom.mes.systemextension
  164     1 R     24.1 60000 /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer
 3996     1 R     23.5 150000 /Applications/cmux.app/Contents/MacOS/cmux
 3256     1 R    195.0 130000 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
72335 42315 R    180.0 100000 /Users/nhn/.vscode/extensions/redhat.java/jre/bin/java -jar x.jar
81085     1 Z      0.0     0 <defunct>
 1226     1 R      5.0 50000 /opt/homebrew/bin/Python -m sysmon --no-browser
 4100  4099 R     10.0 20000 /usr/bin/some-normal-helper
"""


def _sweep_with_fixture(mode):
    """픽스처 ps 출력으로 후보 판정만 돌린다 (실제 kill 없음)."""
    def fake_run(cmd, timeout=10):
        return _SWEEP_PS_FIXTURE if cmd.startswith("ps -Ao") else ""
    with patch("sysmon.actions._run", side_effect=fake_run):
        return ActionRunner._sweep_candidates(mode)


class TestCpuSweepCandidates:
    """CPU 해악 프로세스 판정 — 오늘 실측 상황 기준."""

    def test_conservative_catches_translocation_and_zombie(self):
        pids = {c["pid"] for c in _sweep_with_fixture("conservative")}
        # 격리 경로 VS Code 고아 3개 + 좀비
        assert {41881, 42013, 41924, 81085} <= pids

    def test_conservative_spares_running_apps(self):
        """정상 부모가 있거나 사용자가 쓰는 앱은 보수적 모드에서 제외된다."""
        pids = {c["pid"] for c in _sweep_with_fixture("conservative")}
        assert 72335 not in pids, "부모 있는 java 인덱싱은 보수적 대상 아님"
        assert 3256 not in pids, "Chrome 은 never-kill"
        assert 3996 not in pids, "cmux(터미널) 은 never-kill"

    def test_aggressive_adds_runaway_only(self):
        """적극적 모드는 부모 있는 폭주(java)를 추가로 잡는다."""
        cons = {c["pid"] for c in _sweep_with_fixture("conservative")}
        aggr = {c["pid"] for c in _sweep_with_fixture("aggressive")}
        assert 72335 in aggr and 72335 not in cons
        assert aggr - cons == {72335}, "적극적이 추가로 잡는 건 폭주 프로세스뿐"

    def test_never_kill_survives_aggressive(self):
        """Chrome 은 195% 폭주여도 never-kill 이라 적극적에서도 제외된다."""
        pids = {c["pid"] for c in _sweep_with_fixture("aggressive")}
        assert 3256 not in pids

    def test_security_and_system_always_excluded(self):
        for mode in ("conservative", "aggressive"):
            pids = {c["pid"] for c in _sweep_with_fixture(mode)}
            assert 349 not in pids, "broadcom 보안 프로세스"
            assert 164 not in pids, "WindowServer"

    def test_sysmon_itself_excluded(self):
        for mode in ("conservative", "aggressive"):
            pids = {c["pid"] for c in _sweep_with_fixture(mode)}
            assert 1226 not in pids

    def test_reason_labels(self):
        by_pid = {c["pid"]: c["reason"] for c in _sweep_with_fixture("aggressive")}
        assert by_pid[41881] == "translocation"
        assert by_pid[81085] == "zombie"
        assert by_pid[72335] == "runaway"

    def test_sorted_by_cpu_desc(self):
        cpus = [c["cpu"] for c in _sweep_with_fixture("aggressive")]
        assert cpus == sorted(cpus, reverse=True)


class TestCpuSweepDryRun:
    """미리보기는 절대 kill 하지 않는다."""

    def test_preview_issues_no_kill(self):
        calls = []

        def fake_run(cmd, timeout=10):
            calls.append(cmd)
            return _SWEEP_PS_FIXTURE if cmd.startswith("ps -Ao") else ""

        runner = ActionRunner()
        with patch("sysmon.actions._run", side_effect=fake_run):
            result = runner.run("cpu_sweep_preview_conservative")

        assert not any("kill" in c for c in calls), "미리보기에서 kill 이 호출됐다"
        text = "\n".join(result["logs"])
        assert "미리보기" in text
        assert "종료하지 않았습니다" in text

    def test_preview_lists_targets(self):
        def fake_run(cmd, timeout=10):
            return _SWEEP_PS_FIXTURE if cmd.startswith("ps -Ao") else ""
        runner = ActionRunner()
        with patch("sysmon.actions._run", side_effect=fake_run):
            text = "\n".join(runner.run("cpu_sweep_preview_aggressive")["logs"])
        assert "41881" in text and "translocation" in text
        assert "Visual Studio Code" in text, "앱 이름이 보여야 한다"

    def test_empty_candidates_message(self):
        def fake_run(cmd, timeout=10):
            return "  PID  PPID STAT %CPU   RSS COMMAND\n" if cmd.startswith("ps -Ao") else ""
        runner = ActionRunner()
        with patch("sysmon.actions._run", side_effect=fake_run):
            text = "\n".join(runner.run("cpu_sweep_conservative")["logs"])
        assert "정리할 프로세스가 없습니다" in text


class TestCpuSweepExecute:
    """실행 모드 — SIGKILL 을 버티는 UE 상태 대응 포함."""

    def test_sends_term_then_kill(self):
        calls = []

        def fake_run(cmd, timeout=10):
            calls.append(cmd)
            if cmd.startswith("ps -Ao"):
                return _SWEEP_PS_FIXTURE
            if cmd.startswith("ps -p"):
                return ""  # 전부 죽은 것으로 본다
            return ""

        runner = ActionRunner()
        with patch("sysmon.actions._run", side_effect=fake_run), \
             patch("sysmon.actions.time.sleep"):
            result = runner.run("cpu_sweep_conservative")

        assert any("kill -TERM 41881" in c for c in calls)
        assert "종료 완료" in "\n".join(result["logs"])

    def test_retries_when_kill_ignored(self):
        """UE 상태처럼 SIGKILL 이 무시되면 라운드를 반복하고 경고를 남긴다."""
        def fake_run(cmd, timeout=10):
            if cmd.startswith("ps -Ao"):
                return _SWEEP_PS_FIXTURE
            if cmd.startswith("ps -p"):
                return "41881"  # 계속 살아있다고 응답
            return ""

        runner = ActionRunner()
        with patch("sysmon.actions._run", side_effect=fake_run), \
             patch("sysmon.actions.time.sleep"):
            text = "\n".join(runner.run("cpu_sweep_conservative")["logs"])

        assert "round 1" in text and "round 3" in text, "3라운드까지 재시도해야 한다"
        assert "종료되지 않았습니다" in text


class TestSweepFollowupContract:
    """
    UI 2단 흐름(드라이런 → 팝업 하단 실행)이 의존하는 서버측 계약.

    프론트 applySweepFollowup() 은 로그에 '정리할 프로세스가 없습니다' 가 있으면
    실행 버튼을 숨긴다. 그 문구가 바뀌면 0건인데도 실행 버튼이 뜨므로 여기서 고정한다.
    """

    _EMPTY_PS = "  PID  PPID STAT %CPU   RSS COMMAND\n"

    def _logs(self, action, ps_out):
        def fake_run(cmd, timeout=10):
            return ps_out if cmd.startswith("ps -Ao") else ""
        with patch("sysmon.actions._run", side_effect=fake_run):
            return "\n".join(ActionRunner().run(action)["logs"])

    def test_empty_marker_exact_string(self):
        """0건일 때 프론트가 찾는 문구가 그대로 나온다 → 실행 버튼 숨김."""
        for act in ("cpu_sweep_preview_conservative", "cpu_sweep_preview_aggressive"):
            assert "정리할 프로세스가 없습니다" in self._logs(act, self._EMPTY_PS)

    def test_preview_with_targets_lacks_empty_marker(self):
        """대상이 있으면 그 문구가 없어야 한다 → 실행 버튼 노출."""
        text = self._logs("cpu_sweep_preview_conservative", _SWEEP_PS_FIXTURE)
        assert "정리할 프로세스가 없습니다" not in text
        assert "미리보기" in text

    def test_followup_action_ids_exist(self):
        """프론트 SWEEP_FOLLOWUP 이 가리키는 실행 액션이 실제로 처리된다."""
        for act in ("cpu_sweep_conservative", "cpu_sweep_aggressive"):
            text = self._logs(act, self._EMPTY_PS)
            assert "알 수 없는 액션" not in text
