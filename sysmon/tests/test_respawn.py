"""재시작 루프 탐지 + stale pidfile 점검 테스트.

실제 사고 데이터(2026-09-14 Privacy-i PIAgent)를 재현 케이스로 쓴다.
"""
from unittest.mock import patch

from sysmon import respawn
from sysmon.actions import _LABEL_PATTERN, ActionRunner

# 2026-09-14 실측 커맨드를 줄인 것. java 는 인자가 길어 group_key 안정성 검증에 쓴다.
PIAGENT_CMD = (
    "/usr/local/Privacy-i/jre/Contents/Home/bin/java -server -Dos.bit=64 -DPIAGENTA "
    "-Xmx512m -cp /usr/local/Privacy-i/discover/serveri.jar "
    "com.somansa.privacyi.apps.agent.piagent.PIAgent"
)


def _snap(*procs):
    """(pid, cmd) 또는 (pid, cmd, cpu) 튜플들을 스냅샷 형태로."""
    out = []
    for p in procs:
        pid, cmd = p[0], p[1]
        cpu = p[2] if len(p) > 2 else 0.0
        out.append({"pid": pid, "ppid": 1, "cpu": cpu, "cmd": cmd})
    return out


class TestGroupKey:
    def test_java_key_stable_across_restarts(self):
        """PID 가 바뀌어도 같은 커맨드면 같은 키여야 한다."""
        assert respawn.group_key(PIAGENT_CMD) == respawn.group_key(PIAGENT_CMD)

    def test_flags_dropped(self):
        """-D/-X 플래그는 키에서 빠지고 실행경로·메인클래스는 남는다."""
        key = respawn.group_key(PIAGENT_CMD)
        assert "-Xmx512m" not in key
        assert "-DPIAGENTA" not in key
        assert "com.somansa.privacyi.apps.agent.piagent.PIAgent" in key
        assert "/usr/local/Privacy-i/jre/Contents/Home/bin/java" in key

    def test_empty_cmd(self):
        assert respawn.group_key("") == ""


class TestDetectRespawnLoops:
    def test_detects_sequential_restart(self):
        """PID 가 교대로 바뀌면 루프로 잡는다 — Privacy-i 사고 재현."""
        snaps = [
            _snap((100, PIAGENT_CMD, 120.0)),
            _snap((205, PIAGENT_CMD, 150.0)),
            _snap((311, PIAGENT_CMD, 90.0)),
        ]
        loops = respawn.detect_respawn_loops(snaps)
        assert len(loops) == 1
        assert loops[0]["distinct_pids"] == 3
        assert loops[0]["cpu_peak"] == 150.0
        assert loops[0]["security"] is True  # Privacy-i 는 보안 카테고리

    def test_worker_pool_not_flagged(self):
        """동시에 여러 개 살아 있는 워커 풀은 루프가 아니다 (핵심 오탐 방지)."""
        cmd = "/Applications/Foo.app/Contents/MacOS/Foo --type=renderer"
        snaps = [
            _snap((10, cmd), (11, cmd), (12, cmd)),
            _snap((11, cmd), (12, cmd), (13, cmd)),
        ]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_stable_process_not_flagged(self):
        """PID 가 그대로면 루프가 아니다."""
        snaps = [_snap((77, "/usr/sbin/stabled")) for _ in range(5)]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_single_pid_below_threshold(self):
        """서로 다른 PID 가 1개뿐이면 판정하지 않는다 (엣지: 관찰 창이 짧을 때)."""
        snaps = [_snap((100, PIAGENT_CMD))]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_empty_snapshots(self):
        assert respawn.detect_respawn_loops([]) == []
        assert respawn.detect_respawn_loops([[], []]) == []

    def test_non_security_loop_detected(self):
        """보안SW 가 아닌 루프도 똑같이 잡되 security 플래그는 False."""
        cmd = "/usr/local/bin/flappy-daemon --serve"
        snaps = [_snap((1, cmd)), _snap((2, cmd))]
        loops = respawn.detect_respawn_loops(snaps)
        assert len(loops) == 1
        assert loops[0]["security"] is False


class TestNoiseFilter:
    """단명 유틸 오탐 차단 — 2026-09-14 실측에서 5건 중 4건이 이 노이즈였다."""

    def test_scanner_own_ps_ignored(self):
        """스캐너가 매 샘플마다 띄우는 ps 자신이 잡히면 안 된다."""
        snaps = [
            _snap((10, "ps -Ao pid,ppid,pcpu,command")),
            _snap((11, "ps -Ao pid,ppid,pcpu,command")),
            _snap((12, "ps -Ao pid,ppid,pcpu,command")),
        ]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_sleep_ignored(self):
        snaps = [_snap((1, "sleep 0.3")), _snap((2, "sleep 0.3"))]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_bracketed_cmd_ignored(self):
        """ps 가 괄호로 감싼 건 종료 처리 중이라 실행 주체를 특정할 수 없다."""
        snaps = [_snap((1, "(bash)")), _snap((2, "(bash)"))]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_shell_script_still_detected(self):
        """sh 는 blocklist 에 없다 — Privacy-i 의 piagentad_darwin.sh 가 이 형태다."""
        cmd = "/bin/sh /usr/local/Privacy-i/discover/bin/piagentad_darwin.sh"
        snaps = [_snap((1, cmd)), _snap((2, cmd))]
        loops = respawn.detect_respawn_loops(snaps)
        assert len(loops) == 1
        assert "piagentad_darwin.sh" in loops[0]["name"]

    def test_absolute_path_util_ignored(self):
        """절대경로로 불려도 basename 으로 판정한다."""
        assert respawn.is_ignorable("/bin/sleep 5") is True
        assert respawn.is_ignorable("/usr/bin/grep foo") is True

    def test_sysmon_own_top_ignored(self):
        """sysmon 이 메트릭 수집에 쓰는 top 이 결과에 오르면 안 된다."""
        snaps = [_snap((1, "top -l 2 -n 15", 62.5)), _snap((2, "top -l 2 -n 15", 40.0))]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_shell_wrapped_util_ignored(self):
        """셸 래퍼를 관통해 판정한다 — sh -c top 이 blocklist 를 빠져나가면 안 된다."""
        snaps = [_snap((1, "/bin/sh -c top -l 2")), _snap((2, "/bin/sh -c top -l 2"))]
        assert respawn.detect_respawn_loops(snaps) == []

    def test_effective_exe(self):
        assert respawn.effective_exe("/bin/sh -c top -l 2") == "top"
        assert respawn.effective_exe("/bin/sh /x/piagentad_darwin.sh") == "piagentad_darwin.sh"
        assert respawn.effective_exe("/usr/bin/java -cp x Main") == "java"
        assert respawn.effective_exe("") == ""

    def test_shell_wrapper_does_not_swallow_real_script(self):
        """래퍼 관통이 과해서 진짜 스크립트 루프를 놓치면 안 된다."""
        cmd = "/bin/sh /usr/local/Privacy-i/discover/bin/piagentad_darwin.sh"
        assert respawn.is_ignorable(cmd) is False

    def test_empty_cmd_ignorable(self):
        assert respawn.is_ignorable("") is True


class TestScanRespawn:
    def test_scan_uses_injected_sampler(self):
        """샘플러/슬리퍼 주입 — 실제 20초를 기다리지 않는다."""
        calls = {"n": 0}

        def sampler():
            calls["n"] += 1
            return _snap((calls["n"] * 10, PIAGENT_CMD, 100.0))

        result = respawn.scan_respawn(
            window_sec=4, interval_sec=1.0, sampler=sampler, sleeper=lambda s: None
        )
        assert result["samples"] == 4
        assert len(result["loops"]) == 1
        # 4초에 4회 스폰 = 분당 60회
        assert result["loops"][0]["spawns_per_min"] == 60.0

    def test_scan_minimum_two_rounds(self):
        """window 가 아주 짧아도 최소 2회는 샘플링해야 비교가 가능하다."""
        result = respawn.scan_respawn(
            window_sec=0, interval_sec=1.0, sampler=lambda: [], sleeper=lambda s: None
        )
        assert result["samples"] == 2


class TestCheckPidfileGuards:
    GUARD = {
        "id": "privacy_i_piagent",
        "name": "Privacy-i PIAgent",
        "pidfile": "/tmp/ifi_piagent_test",
        "expect_cmd": "PIAGENTA",
        "needs_sudo": True,
        "hint": "테스트",
    }

    def test_stale_when_pid_reused(self):
        """PID 는 살아 있지만 다른 프로세스 — 실제 사고 조건."""
        rows = respawn.check_pidfile_guards(
            [self.GUARD],
            cmd_of=lambda pid: "/usr/libexec/diagnosticd",
            reader=lambda p: "512\n",
        )
        assert rows[0]["status"] == "stale"
        assert rows[0]["pid"] == 512
        assert "diagnosticd" in rows[0]["detail"]

    def test_ok_when_pid_matches(self):
        rows = respawn.check_pidfile_guards(
            [self.GUARD],
            cmd_of=lambda pid: PIAGENT_CMD,
            reader=lambda p: "19242\n",
        )
        assert rows[0]["status"] == "ok"

    def test_dead_when_pid_absent(self):
        rows = respawn.check_pidfile_guards(
            [self.GUARD], cmd_of=lambda pid: "", reader=lambda p: "99999"
        )
        assert rows[0]["status"] == "dead"

    def test_missing_when_file_absent(self):
        def boom(path):
            raise FileNotFoundError(path)

        rows = respawn.check_pidfile_guards(
            [self.GUARD], cmd_of=lambda pid: "", reader=boom
        )
        assert rows[0]["status"] == "missing"

    def test_garbage_pidfile(self):
        """엣지: 숫자가 아닌 내용이 들어 있어도 죽지 않는다."""
        rows = respawn.check_pidfile_guards(
            [self.GUARD], cmd_of=lambda pid: "", reader=lambda p: "not-a-pid"
        )
        assert rows[0]["status"] == "missing"

    def test_shipped_guards_json_is_valid(self):
        """동봉한 pidfile_guards.json 이 스키마를 지키는지."""
        guards = respawn.load_guards()
        assert guards, "guards 가 비어 있다"
        for g in guards:
            assert g["id"] and g["pidfile"] and g["expect_cmd"]
            # 액션 ID 로 쓰이므로 셸 인젝션 방어 패턴을 통과해야 한다.
            assert _LABEL_PATTERN.match(g["id"])

    def test_load_guards_missing_file(self):
        from pathlib import Path

        assert respawn.load_guards(Path("/tmp/definitely-not-here.json")) == []


class TestRepairPidfile:
    GUARD = {
        "id": "x",
        "pidfile": "/tmp/ifi_test",
        "needs_sudo": True,
    }

    def test_refuses_without_password(self):
        ok, msg = respawn.repair_pidfile(self.GUARD, password="")
        assert ok is False
        assert "비밀번호" in msg

    def test_moves_not_deletes(self):
        """삭제가 아니라 이동이어야 한다 (롤백 가능)."""
        seen = {}

        def runner(cmd, stdin):
            seen["cmd"] = cmd
            return 0, ""

        ok, msg = respawn.repair_pidfile(self.GUARD, password="pw", runner=runner)
        assert ok is True
        assert seen["cmd"].startswith("sudo -S mv ")
        assert "rm " not in seen["cmd"]
        assert ".bak" in msg

    def test_wrong_password(self):
        ok, msg = respawn.repair_pidfile(
            self.GUARD, password="bad", runner=lambda c, s: (1, "Sorry, try again.")
        )
        assert ok is False
        assert "비밀번호가 틀" in msg

    def test_no_sudo_when_not_needed(self):
        seen = {}

        def runner(cmd, stdin):
            seen["cmd"] = cmd
            return 0, ""

        respawn.repair_pidfile({"id": "y", "pidfile": "/tmp/a", "needs_sudo": False},
                               runner=runner)
        assert not seen["cmd"].startswith("sudo")

    def test_empty_pidfile_path(self):
        ok, msg = respawn.repair_pidfile({"id": "z"}, password="pw")
        assert ok is False


class TestRespawnActions:
    def test_respawn_scan_reports_loop_and_never_kills(self):
        """스캔은 보고만 한다 — kill 계열 명령을 절대 내보내지 않는다."""
        runner = ActionRunner()
        fake = {
            "window_sec": 20, "samples": 20,
            "loops": [{
                "key": "k", "name": "java PIAgent", "cmd": PIAGENT_CMD,
                "distinct_pids": 6, "pids": [1, 2, 3], "cpu_peak": 180.0,
                "security": True, "spawns_per_min": 18.0,
            }],
        }
        with patch("sysmon.respawn.scan_respawn", return_value=fake), \
             patch("sysmon.respawn.check_pidfile_guards", return_value=[]), \
             patch("sysmon.actions._run") as mock_run:
            result = runner.run("respawn_scan")
        text = "\n".join(result["logs"])
        assert "재시작 루프 1건" in text
        assert "java PIAgent" in text
        assert "[보안SW]" in text
        mock_run.assert_not_called()  # 아무것도 죽이지 않았다

    def test_respawn_scan_emits_repair_marker(self):
        """stale 이 있으면 UI 가 읽을 [REPAIR:id] 마커를 남긴다."""
        runner = ActionRunner()
        stale = [{
            "id": "privacy_i_piagent", "name": "Privacy-i PIAgent",
            "pidfile": "/tmp/x", "needs_sudo": True, "hint": "힌트",
            "expect_cmd": "PIAGENTA", "status": "stale", "detail": "PID 512 은(는) 딴 것",
        }]
        with patch("sysmon.respawn.scan_respawn",
                   return_value={"window_sec": 20, "samples": 20, "loops": []}), \
             patch("sysmon.respawn.check_pidfile_guards", return_value=stale):
            result = runner.run("respawn_scan")
        text = "\n".join(result["logs"])
        assert "[REPAIR:privacy_i_piagent]" in text
        assert "힌트" in text

    def test_respawn_scan_clean(self):
        runner = ActionRunner()
        with patch("sysmon.respawn.scan_respawn",
                   return_value={"window_sec": 20, "samples": 20, "loops": []}), \
             patch("sysmon.respawn.check_pidfile_guards", return_value=[]):
            result = runner.run("respawn_scan")
        assert "재시작 루프 없음" in "\n".join(result["logs"])

    def test_repair_rejects_bad_id(self):
        """인젝션 방어: 셸 메타문자가 섞인 id 는 거부."""
        runner = ActionRunner()
        result = runner.run("pidfile_repair_x;rm -rf /", password="pw")
        assert "유효하지 않은 id" in "\n".join(result["logs"])

    def test_repair_rejects_unregistered_id(self):
        runner = ActionRunner()
        result = runner.run("pidfile_repair_nope", password="pw")
        assert "등록되지 않은" in "\n".join(result["logs"])

    def test_repair_aborts_when_not_stale(self):
        """수리 직전 재확인 — 이미 정상이면 손대지 않는다."""
        runner = ActionRunner()
        guard = {"id": "privacy_i_piagent", "name": "P", "pidfile": "/tmp/x",
                 "expect_cmd": "PIAGENTA", "needs_sudo": True}
        with patch("sysmon.respawn.load_guards", return_value=[guard]), \
             patch("sysmon.respawn.check_pidfile_guards",
                   return_value=[{"id": "privacy_i_piagent", "status": "ok",
                                  "detail": "PID 1 정상"}]), \
             patch("sysmon.respawn.repair_pidfile") as mock_repair:
            result = runner.run("pidfile_repair_privacy_i_piagent", password="pw")
        assert "중단" in "\n".join(result["logs"])
        mock_repair.assert_not_called()

    def test_repair_happy_path(self):
        runner = ActionRunner()
        guard = {"id": "privacy_i_piagent", "name": "P", "pidfile": "/tmp/x",
                 "expect_cmd": "PIAGENTA", "needs_sudo": True}
        with patch("sysmon.respawn.load_guards", return_value=[guard]), \
             patch("sysmon.respawn.check_pidfile_guards",
                   return_value=[{"id": "privacy_i_piagent", "status": "stale",
                                  "detail": "유령"}]), \
             patch("sysmon.respawn.repair_pidfile",
                   return_value=(True, "옮겼습니다")) as mock_repair:
            result = runner.run("pidfile_repair_privacy_i_piagent", password="pw")
        text = "\n".join(result["logs"])
        assert "옮겼습니다" in text
        assert "다시 눌러" in text
        assert mock_repair.call_args.kwargs["password"] == "pw"
