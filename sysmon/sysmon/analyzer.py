"""인사이트 생성기 — 메트릭 기반 진단 + 액션 제안."""
from typing import Any


class Analyzer:
    """수집된 메트릭에서 인사이트를 생성한다."""

    def generate_insights(self, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        """
        메트릭을 분석하여 인사이트 목록 반환.

        각 인사이트: {severity, title, description, actions}
        severity: "critical" | "warning" | "info" | "summary"
        """
        insights: list[dict[str, Any]] = []
        mem = metrics["memory"]
        mcp = metrics["mcp"]
        cl = metrics["claude"]

        # ── MCP 서버 폭발 ──
        mcp_gb = round(mcp["total_mb"] / 1024, 1)
        if mcp["total_count"] > 30:
            insights.append({
                "severity": "critical",
                "title": f"MCP 서버 {mcp['total_count']}개 — {mcp_gb} GB 점유",
                "description": (
                    f"Claude {cl['total_count']}개 세션이 각각 MCP를 독립 스폰.\n"
                    f"Claude CLI({round(cl['total_mb'] / 1024, 1)}GB)보다 "
                    f"MCP({mcp_gb}GB)가 더 많이 먹음."
                ),
                "actions": [self._kill_all_mcp_action(mcp["total_count"], mcp_gb)],
            })
        elif mcp["total_count"] > 10:
            insights.append({
                "severity": "warning",
                "title": f"MCP 서버 {mcp['total_count']}개 — {mcp_gb} GB",
                "description": "MCP 프로세스가 다소 많음.",
                "actions": [self._kill_all_mcp_action(mcp["total_count"], mcp_gb)],
            })

        # ── RAM 압박 ──
        if mem["pressure_pct"] >= 90:
            insights.append({
                "severity": "critical",
                "title": f"RAM {mem['pressure_pct']}% — 스왑 발생 중",
                "description": (
                    f"전체 {mem['total_gb']}GB 중 {mem['used_gb']}GB 사용.\n"
                    f"압축 {mem['compressed_gb']}GB, 스왑아웃 {mem['swap_outs']:,}건.\n"
                    f"파일 캐시 {mem['inactive_gb']}GB는 회수 가능."
                ),
                "actions": [{
                    "id": "purge_cache",
                    "label": "메모리 캐시 퍼지",
                    "effect": f"파일 캐시 ~{mem['inactive_gb']}GB 강제 회수",
                    "confirm": (
                        "macOS 파일 캐시를 강제 회수합니다.\n\n"
                        "데이터 손실 없음\n"
                        "모든 앱/세션 유지\n"
                        "잠시 디스크 I/O 증가 (앱이 파일 다시 읽음)\n\n"
                        "sudo 비밀번호를 입력해주세요."
                    ),
                }],
            })

        # ── 서브에이전트 과다 ──
        if cl["sub_count"] > 6:
            estimated_gb = round(cl["sub_count"] * 0.8, 1)
            insights.append({
                "severity": "warning",
                "title": f"서브에이전트 {cl['sub_count']}개 — ~{estimated_gb} GB",
                "description": (
                    f"서브에이전트 1개 = Claude ~230MB + MCP ~570MB = ~800MB.\n"
                    f"{cl['sub_count']}개 x 800MB = ~{estimated_gb}GB."
                ),
                "actions": [],
            })

        # ── 메인 세션 과다 ──
        if cl["main_count"] > 3:
            insights.append({
                "severity": "info",
                "title": f"메인 세션 {cl['main_count']}개 동시 실행",
                "description": "세션당 ~1.2GB. 안 쓰는 세션은 터미널에서 Ctrl+C 또는 /exit.",
                "actions": [],
            })

        # ── 개별 MCP 과다 ──
        for name, info in sorted(
            mcp["breakdown"].items(), key=lambda x: -x[1]["total_mb"]
        ):
            if info["count"] > 15 and info["total_mb"] > 500:
                per_session = info["count"] // max(cl["total_count"], 1)
                info_gb = round(info["total_mb"] / 1024, 1)
                insights.append({
                    "severity": "info",
                    "title": f"{name}: {info['count']}개, {info_gb} GB",
                    "description": f"세션당 {per_session}개씩 스폰.",
                    "actions": [{
                        "id": f"kill_mcp_{name}",
                        "label": f"{name} 종료",
                        "effect": f"~{info_gb} GB 회수",
                        "confirm": (
                            f"{name} 프로세스 {info['count']}개를 종료합니다.\n\n"
                            "대화/세션 유지\n"
                            "필요 시 자동 재시작"
                        ),
                    }],
                })

        # ── 요약 ──
        after = max(0, mem["pressure_pct"] - round(mcp_gb / mem["total_gb"] * 100))
        insights.append({
            "severity": "summary",
            "title": f"MCP 전체 정리 시 RAM {mem['pressure_pct']}% → ~{after}%",
            "description": f"최대 ~{mcp_gb} GB 회수 가능.",
            "actions": [],
        })

        return insights

    @staticmethod
    def _kill_all_mcp_action(count: int, gb: float) -> dict[str, Any]:
        """MCP 전체 종료 액션 생성."""
        return {
            "id": "kill_all_mcp",
            "label": f"전체 MCP 종료 ({count}개)",
            "effect": f"~{gb} GB 회수",
            "confirm": (
                f"MCP 서버 {count}개를 종료합니다.\n\n"
                "현재 대화/컨텍스트는 유지됩니다\n"
                "활성 세션의 MCP는 1-2초 내 자동 재시작\n"
                "재시작까지 잠깐 도구(ES, MySQL 등) 사용 불가\n\n"
                f"예상 효과: ~{gb} GB 메모리 회수"
            ),
        }
