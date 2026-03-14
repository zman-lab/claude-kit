"""Claude Board MCP Server (SSE mode).
REST API를 호출하는 래퍼. instructions를 DB에서 동적 생성.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("BOARD_URL", "http://127.0.0.1:8585")


def _build_instructions() -> str:
    """DB에서 팀/게시판 목록을 조회하여 MCP instructions를 동적 생성."""
    base = """Claude Board - 팀 간 소통 게시판 시스템.
게시판에 글을 쓰고, 읽고, 댓글을 달 수 있습니다.

태그 시스템 (팀 게시판 필수):
- work: 일반 업무 -> 기본값
- todo: 해야 할 일
- issue: 문제/버그 (원인+재현조건 권장)
- done: 완료 (커밋 해시 권장)
- knowhow: 팁/노하우

글 작성 시 주의:
- 제목은 구체적으로 (10자 이상)
- author는 반드시 세션 ID (예: alpha-a3f2)
- status/related_commit으로 구조화된 메타데이터 추가 가능
"""
    # 팀 목록을 REST API에서 가져오기
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5) as client:
            r = client.get("/api/admin/teams")
            if r.status_code == 200:
                teams = r.json()
                active_teams = [t for t in teams if t.get("is_active")]
                if active_teams:
                    team_lines = []
                    for t in active_teams:
                        desc = f" - {t['description']}" if t.get("description") else ""
                        team_lines.append(f"  {t['icon']} {t['name']} (slug: {t['slug']}){desc}")
                    base += "\n등록된 팀:\n" + "\n".join(team_lines)
    except Exception:
        pass  # API 접근 실패 시 기본 instructions 사용

    return base


mcp = FastMCP("claude-board", instructions=_build_instructions())


def _enrich_content(content: str, status: str | None, related_commit: str | None, related_branch: str | None) -> str:
    """Prepend structured metadata block to content."""
    meta_lines = []
    if status:
        meta_lines.append(f"**상태**: {status}")
    if related_commit:
        meta_lines.append(f"**커밋**: `{related_commit}`")
    if related_branch:
        meta_lines.append(f"**브랜치**: `{related_branch}`")
    if meta_lines:
        meta_block = " | ".join(meta_lines)
        return f"> {meta_block}\n\n{content}"
    return content


def _validate_content_quality(title: str, content: str, tag: str | None) -> list[str]:
    """Soft validation - returns warnings (not errors)."""
    warnings = []
    if len(title) < 10:
        warnings.append("제목이 너무 짧습니다 (10자 이상 권장)")
    if tag == "issue" and "재현" not in content and "원인" not in content:
        warnings.append("issue 태그: 원인/재현조건 포함 권장")
    if tag == "done" and "커밋" not in content.lower() and "commit" not in content.lower():
        warnings.append("done 태그: 커밋 해시 포함 권장")
    return warnings


def _get(path: str, params: dict | None = None) -> dict | list:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.get(path, params=params)
        r.raise_for_status()
        return r.json()


def _post(path: str, json: dict) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.post(path, json=json)
        r.raise_for_status()
        return r.json()


def _put(path: str, json: dict) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.put(path, json=json)
        r.raise_for_status()
        return r.json()


def _delete(path: str) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        r = client.delete(path)
        r.raise_for_status()
        return r.json()


def _fmt(dt_str: str | None) -> str:
    """ISO 8601 datetime 문자열을 'YYYY-MM-DD HH:MM:SS' 형식으로 변환."""
    if not dt_str:
        return "없음"
    return dt_str[:19].replace("T", " ")


@mcp.tool()
def list_boards() -> str:
    """게시판 목록을 조회합니다."""
    boards = _get("/api/boards")
    if not boards:
        return "게시판 없음"
    lines = []
    for b in boards:
        lines.append(f"{b['icon']} {b['name']} (slug: {b['slug']}) - 글 {b['post_count']}개")
    return "\n".join(lines)


@mcp.tool()
def list_posts(board_slug: str, limit: int = 20, tag: str | None = None) -> str:
    """특정 게시판의 게시글 목록을 조회합니다.

    Args:
        board_slug: 게시판 slug (예: alpha-work, free, notice)
        limit: 조회할 글 수 (기본 20)
        tag: 태그 필터 (예: work, todo, issue, done, knowhow)
    """
    params = {"board_slug": board_slug, "limit": limit}
    if tag:
        params["tag"] = tag
    posts = _get("/api/posts", params)
    if not posts:
        return f"'{board_slug}' 게시판에 글이 없습니다."
    lines = []
    for p in posts:
        pin = "📌 " if p["is_pinned"] else ""
        prefix = f"[{p['prefix']}] " if p.get("prefix") else ""
        reply = f" 💬{p['reply_count']}" if p["reply_count"] > 0 else ""
        like = f" ❤️{p['like_count']}" if p.get("like_count", 0) > 0 else ""
        lines.append(f"[{p['id']}] {pin}{prefix}{p['title']} ({p['author']}, {_fmt(p['created_at'])}){reply}{like}")
    return "\n".join(lines)


@mcp.tool()
def read_post(post_id: int) -> str:
    """게시글 상세 내용과 댓글을 조회합니다.

    Args:
        post_id: 게시글 ID
    """
    data = _get(f"/api/posts/{post_id}")
    like_str = ""
    if data.get("like_count", 0) > 0:
        who = ", ".join(data.get("liked_by", []))
        like_str = f" | ❤️ {data['like_count']} ({who})"
    edited = data.get("updated_at") and data["updated_at"] != data["created_at"]
    time_line = f"작성일: {_fmt(data['created_at'])}"
    if edited:
        time_line += f"  (수정됨: {_fmt(data['updated_at'])})"
    lines = [
        f"제목: {data['title']}",
        f"작성자: {data['author']} | 게시판: {data['board_name']}{like_str}",
        time_line,
        "---",
        data["content"],
    ]
    if data.get("replies"):
        lines.append(f"\n--- 댓글 {len(data['replies'])}개 ---")
        for r in data["replies"]:
            r_like = ""
            if r.get("like_count", 0) > 0:
                r_who = ", ".join(r.get("liked_by", []))
                r_like = f" ❤️{r['like_count']}({r_who})"
            lines.append(f"\n[{r['author']}] ({_fmt(r['created_at'])}){r_like}")
            lines.append(r["content"])
    return "\n".join(lines)


@mcp.tool()
def create_post(
    board_slug: str,
    title: str,
    content: str,
    author: str,
    prefix: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    related_commit: str | None = None,
    related_branch: str | None = None,
) -> str:
    """게시판에 새 글을 작성합니다.

    Args:
        board_slug: 게시판 slug (예: alpha-work, free, notice)
        title: 글 제목 - 구체적으로! (나쁜 예: "작업 완료", 좋은 예: "JWT 토큰 갱신 로직 구현 완료")
        content: 글 내용 (마크다운 지원)
        author: 세션 ID (예: alpha-a3f2) - 반드시 세션 ID 사용!
        prefix: 머릿말 (공지게시판용, 예: [전체], [긴급])
        tag: **필수 권장** - 팀 게시판 태그:
            - work: 일반 업무 진행 사항
            - todo: 앞으로 해야 할 일
            - issue: 문제/버그 발견 (원인, 재현조건 포함 권장)
            - done: 완료된 작업 (결과물/커밋 포함 권장)
            - knowhow: 팁/노하우 공유
        status: 작업 상태 (선택): in-progress, blocked, completed
        related_commit: 관련 커밋 해시 (선택)
        related_branch: 관련 브랜치명 (선택)
    """
    enriched = _enrich_content(content, status, related_commit, related_branch)
    warnings = _validate_content_quality(title, content, tag)

    result = _post("/api/posts", {
        "board_slug": board_slug, "title": title, "content": enriched,
        "author": author, "prefix": prefix, "tag": tag,
    })

    msg = f"게시글 작성 완료! ID: {result['id']}, 제목: {title}"
    if warnings:
        msg += "\n" + "\n".join(f"⚠️ {w}" for w in warnings)
    return msg


@mcp.tool()
def reply_to_post(post_id: int, content: str, author: str) -> str:
    """게시글에 댓글을 답니다.

    Args:
        post_id: 게시글 ID
        content: 댓글 내용
        author: 작성자 이름
    """
    result = _post(f"/api/posts/{post_id}/reply", {"content": content, "author": author})
    return f"댓글 작성 완료! ID: {result['id']}"


@mcp.tool()
def create_board(name: str, slug: str, category: str = "team", team: str | None = None,
                 description: str = "", icon: str = "📋") -> str:
    """새 게시판을 생성합니다.

    Args:
        name: 게시판 이름 (예: "[newproject] 업무게시판")
        slug: URL용 식별자 (예: "newproject-work")
        category: "team" 또는 "global"
        team: 팀명 (team 카테고리일 때)
        description: 게시판 설명
        icon: 아이콘 이모지
    """
    result = _post("/api/boards", {
        "name": name, "slug": slug, "category": category,
        "team": team, "description": description, "icon": icon,
    })
    return f"게시판 생성 완료! slug: {result['slug']}"


@mcp.tool()
def search_posts(keyword: str, board_slug: str | None = None, limit: int = 20) -> str:
    """게시글을 검색합니다.

    Args:
        keyword: 검색 키워드
        board_slug: 특정 게시판에서만 검색 (선택)
        limit: 결과 수 (기본 20)
    """
    params = {"q": keyword, "limit": limit}
    if board_slug:
        params["board_slug"] = board_slug
    results = _get("/api/search", params)
    if not results:
        return f"'{keyword}' 검색 결과 없음"
    lines = []
    for r in results:
        lines.append(f"[{r['id']}] {r['title']} ({r['board_name']}, {r['author']}, {_fmt(r['created_at'])}) 💬{r['reply_count']}")
    return "\n".join(lines)


@mcp.tool()
def get_recent_posts(limit: int = 10) -> str:
    """전체 게시판의 최신 글을 조회합니다.

    Args:
        limit: 조회 수 (기본 10)
    """
    results = _get("/api/recent", {"limit": limit})
    if not results:
        return "최신 글 없음"
    lines = []
    for r in results:
        like = f" ❤️{r['like_count']}" if r.get("like_count", 0) > 0 else ""
        lines.append(f"[{r['id']}] {r['title']} ({r['board_name']}, {r['author']}, {_fmt(r['created_at'])}) 💬{r['reply_count']}{like}")
    return "\n".join(lines)


@mcp.tool()
def like_post(post_id: int, author: str) -> str:
    """게시글에 좋아요를 누릅니다 (토글 - 이미 눌렀으면 취소).

    Args:
        post_id: 게시글 ID
        author: 좋아요 누르는 사람 이름 (팀명 또는 세션명)
    """
    result = _post(f"/api/posts/{post_id}/like", {"author": author})
    action = "좋아요!" if result["action"] == "liked" else "좋아요 취소"
    who = ", ".join(result.get("liked_by", []))
    return f"{action} (현재 ❤️ {result['like_count']}개: {who})"


@mcp.tool()
def get_last_activity() -> str:
    """전체 게시판의 마지막 활동 시간을 조회합니다."""
    data = _get("/api/last-activity")
    last = _fmt(data.get("last_activity_at"))
    lines = [
        f"마지막 활동: {last}",
        f"- 글 작성: {_fmt(data.get('last_post_at'))}",
        f"- 글 수정: {_fmt(data.get('last_updated_at'))}",
        f"- 댓글:   {_fmt(data.get('last_comment_at'))}",
        f"- 좋아요: {_fmt(data.get('last_like_at'))}",
    ]
    return "\n".join(lines)


@mcp.tool()
def get_dashboard() -> str:
    """대시보드 요약 정보를 조회합니다."""
    summary = _get("/api/dashboard/summary")
    team_stats = _get("/api/dashboard/team-stats")

    lines = [
        "📊 대시보드 요약",
        f"- 전체 글: {summary['total_posts']}개",
        f"- 오늘 활동: {summary['today_posts']}개",
        f"- 미해결 이슈: {summary['open_issues']}개",
        f"- 활성 팀 (24h): {summary['active_teams_24h']}개",
        "",
        "팀별 현황:",
    ]
    for ts in team_stats:
        parts = []
        for tag in ['work', 'todo', 'issue', 'done', 'knowhow']:
            if ts.get(tag, 0) > 0:
                parts.append(f"{tag}:{ts[tag]}")
        if parts:
            lines.append(f"  {ts['team']}: {', '.join(parts)}")

    return "\n".join(lines)


@mcp.tool()
def update_post(
    post_id: int,
    title: str | None = None,
    content: str | None = None,
    prefix: str | None = None,
    tag: str | None = None,
) -> str:
    """게시글의 제목, 내용, 머릿말, 태그를 수정합니다.

    Args:
        post_id: 수정할 게시글 ID
        title: 새 제목 (선택)
        content: 새 내용 (선택)
        prefix: 새 머릿말 (선택)
        tag: 새 태그 (선택): work, todo, issue, done, knowhow
    """
    payload = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    if prefix is not None:
        payload["prefix"] = prefix
    if tag is not None:
        payload["tag"] = tag
    if not payload:
        return "수정할 필드가 없습니다."
    result = _put(f"/api/posts/{post_id}", payload)
    return f"게시글 {result['id']} 수정 완료! 제목: {result.get('title', '-')}, 태그: {result.get('tag', '-')}"


@mcp.tool()
def update_reply(reply_id: int, content: str) -> str:
    """댓글 내용을 수정합니다.

    Args:
        reply_id: 수정할 댓글 ID
        content: 새 내용
    """
    result = _put(f"/api/replies/{reply_id}", {"content": content})
    return f"댓글 {result['id']} 수정 완료!"


@mcp.tool()
def delete_post(post_id: int) -> str:
    """게시글을 삭제합니다 (소프트 삭제).

    Args:
        post_id: 삭제할 게시글 ID
    """
    _delete(f"/api/posts/{post_id}")
    return f"게시글 {post_id} 삭제 완료"


if __name__ == "__main__":
    mcp.run(transport="sse")
