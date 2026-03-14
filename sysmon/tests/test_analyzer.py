"""analyzer 모듈 테스트."""
from sysmon.analyzer import Analyzer


def _make_metrics(mcp_count=5, mcp_mb=100, ram_pct=50, claude_total=2,
                  claude_main=2, claude_sub=0, claude_mb=500,
                  total_gb=36, used_gb=18, inactive_gb=5, compressed_gb=2,
                  wired_gb=3, swap_outs=0, breakdown=None):
    return {
        "mcp": {
            "total_count": mcp_count,
            "total_mb": mcp_mb,
            "breakdown": breakdown or {},
            "pids": [],
        },
        "memory": {
            "total_gb": total_gb, "used_gb": used_gb, "free_gb": total_gb - used_gb,
            "pressure_pct": ram_pct, "inactive_gb": inactive_gb,
            "compressed_gb": compressed_gb, "wired_gb": wired_gb,
            "swap_outs": swap_outs,
        },
        "claude": {
            "total_count": claude_total, "main_count": claude_main,
            "sub_count": claude_sub, "total_mb": claude_mb,
            "sessions": [],
        },
    }


class TestMcpExplosion:
    def test_mcp_over_30_is_critical(self):
        m = _make_metrics(mcp_count=55, mcp_mb=5000, claude_total=10, claude_mb=3000)
        insights = Analyzer().generate_insights(m)
        critical = [i for i in insights if i["severity"] == "critical"]
        assert any("MCP" in i["title"] for i in critical)

    def test_mcp_under_10_no_warning(self):
        m = _make_metrics(mcp_count=5, mcp_mb=100)
        insights = Analyzer().generate_insights(m)
        mcp_ins = [i for i in insights if "MCP" in i.get("title", "") and i["severity"] in ("critical", "warning")]
        assert len(mcp_ins) == 0


class TestRamPressure:
    def test_ram_95_is_critical(self):
        m = _make_metrics(ram_pct=96, used_gb=34.5, total_gb=36, swap_outs=500000,
                          inactive_gb=10, compressed_gb=8)
        insights = Analyzer().generate_insights(m)
        critical = [i for i in insights if i["severity"] == "critical"]
        assert any("RAM" in i["title"] for i in critical)

    def test_ram_50_no_critical(self):
        m = _make_metrics(ram_pct=50)
        insights = Analyzer().generate_insights(m)
        critical = [i for i in insights if i["severity"] == "critical"]
        assert not any("RAM" in i.get("title", "") for i in critical)


class TestInsightActions:
    def test_mcp_critical_has_kill_action(self):
        m = _make_metrics(mcp_count=60, mcp_mb=8000, claude_total=10, claude_mb=3000)
        insights = Analyzer().generate_insights(m)
        mcp_critical = [i for i in insights if i["severity"] == "critical" and "MCP" in i["title"]]
        assert len(mcp_critical) >= 1
        actions = mcp_critical[0].get("actions", [])
        assert any(a["id"] == "kill_all_mcp" for a in actions)

    def test_action_has_confirm(self):
        m = _make_metrics(mcp_count=60, mcp_mb=8000, claude_total=10, claude_mb=3000)
        insights = Analyzer().generate_insights(m)
        mcp_critical = [i for i in insights if i["severity"] == "critical" and "MCP" in i["title"]]
        for action in mcp_critical[0].get("actions", []):
            assert "confirm" in action
            assert len(action["confirm"]) > 0


class TestHealthySystem:
    def test_no_critical_when_healthy(self):
        m = _make_metrics(mcp_count=3, mcp_mb=50, ram_pct=40)
        insights = Analyzer().generate_insights(m)
        critical = [i for i in insights if i["severity"] == "critical"]
        assert len(critical) == 0
