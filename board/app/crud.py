"""DB CRUD 로직. 하드코딩된 팀명 없이 동적으로 처리."""

import hashlib
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models import Board, Post, Like, Attachment, AccessPassword, Team, TokenUsage
from app.schemas import BoardCreate, PostCreate, ReplyCreate, TeamCreate, TeamUpdate


# -- Team CRUD --

def get_teams(db: Session, active_only: bool = True) -> list[Team]:
    """팀 목록 조회."""
    query = db.query(Team)
    if active_only:
        query = query.filter(Team.is_active == True)
    return query.order_by(Team.sort_order, Team.id).all()


def get_team_by_slug(db: Session, slug: str) -> Team | None:
    return db.query(Team).filter(Team.slug == slug).first()


def create_team(db: Session, data: TeamCreate) -> tuple[Team, Board]:
    """팀 생성 + 자동으로 {slug}-work 게시판 생성. (team, board) 반환."""
    team = Team(
        name=data.name,
        slug=data.slug,
        icon=data.icon,
        color=data.color,
        color_dark=data.color_dark,
        description=data.description,
        sort_order=data.sort_order,
    )
    db.add(team)
    db.flush()

    # 팀 업무게시판 자동 생성
    board_slug = f"{data.slug}-work"
    board = Board(
        name=f"[{data.slug}] 업무게시판",
        slug=board_slug,
        category="team",
        team=data.slug,
        icon=data.icon,
        description=f"{data.name} 팀 업무 공유 게시판",
        sort_order=data.sort_order,
        allowed_tags="work,todo,issue,done,knowhow",
        default_tag="work",
    )
    db.add(board)
    db.flush()

    # 환영 글 작성
    welcome_post = Post(
        board_id=board.id,
        title=f"{data.name} 팀 업무게시판에 오신 것을 환영합니다!",
        content=f"""안녕하세요, {data.name} 팀!

이 게시판은 팀의 **업무 공유와 기술 논의**를 위한 공간입니다.

## 이런 글을 올려주세요
- 오늘의 작업 요약 (진행/완료/블로커)
- 기술적 문제 & 해결 방법
- 의사결정이 필요한 이슈
- 노하우 공유 (knowhow 태그)

## 태그 안내
- **work**: 일반 업무 (기본값)
- **todo**: 할 일
- **issue**: 이슈/문제
- **done**: 완료
- **knowhow**: 팁/노하우

함께 만들어갑시다!""",
        author="system",
        is_pinned=True,
    )
    db.add(welcome_post)

    db.commit()
    db.refresh(team)
    db.refresh(board)

    # 글로벌 게시판의 allowed_prefixes에 새 팀 추가
    _update_global_board_prefixes(db)

    return team, board


def update_team(db: Session, team_id: int, data: TeamUpdate) -> Team | None:
    """팀 정보 수정."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(team, key, value)
    # 팀 아이콘이 변경되면 연관 게시판도 업데이트
    if "icon" in update_data:
        board = db.query(Board).filter(Board.slug == f"{team.slug}-work").first()
        if board:
            board.icon = update_data["icon"]
    db.commit()
    db.refresh(team)
    return team


def delete_team(db: Session, team_id: int) -> bool:
    """팀 소프트 삭제 + 연관 게시판 비활성화."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        return False
    team.is_active = False
    # 연관 게시판 비활성화
    board = db.query(Board).filter(Board.slug == f"{team.slug}-work").first()
    if board:
        board.is_active = False
    db.commit()
    # 글로벌 게시판의 allowed_prefixes에서 팀 제거
    _update_global_board_prefixes(db)
    return True


def _update_global_board_prefixes(db: Session):
    """DB의 활성 팀 목록을 기반으로 글로벌 게시판의 allowed_prefixes를 동적 업데이트."""
    teams = get_teams(db, active_only=True)
    team_prefixes = [f"[{t.slug}]" for t in teams]

    # request 게시판
    request_board = db.query(Board).filter(Board.slug == "request").first()
    if request_board:
        prefixes = team_prefixes + ["[인프라]", "[자문]", "[전체]"]
        request_board.allowed_prefixes = ",".join(prefixes)

    # notice 게시판
    notice_board = db.query(Board).filter(Board.slug == "notice").first()
    if notice_board:
        prefixes = ["[전체]"] + team_prefixes + ["[긴급]"]
        notice_board.allowed_prefixes = ",".join(prefixes)

    db.commit()


# -- Board CRUD --

def get_boards(db: Session, active_only: bool = True) -> list[dict]:
    query = db.query(Board)
    if active_only:
        query = query.filter(Board.is_active == True)
    boards = query.order_by(Board.sort_order, Board.id).all()

    result = []
    for b in boards:
        count = (
            db.query(func.count(Post.id))
            .filter(Post.board_id == b.id, Post.parent_id == None, Post.is_deleted == False)
            .scalar()
        )
        latest = (
            db.query(Post)
            .filter(Post.board_id == b.id, Post.parent_id == None, Post.is_deleted == False)
            .order_by(desc(Post.created_at))
            .first()
        )
        result.append({
            "board": b,
            "post_count": count,
            "latest_post": latest,
        })
    return result


def get_board_by_slug(db: Session, slug: str) -> Board | None:
    return db.query(Board).filter(Board.slug == slug).first()


def create_board(db: Session, data: BoardCreate) -> Board:
    board = Board(**data.model_dump())
    db.add(board)
    db.commit()
    db.refresh(board)
    return board


# -- Post --

def _get_like_info(db: Session, post_id: int) -> dict:
    count = db.query(func.count(Like.id)).filter(Like.post_id == post_id).scalar()
    authors = [r[0] for r in db.query(Like.author).filter(Like.post_id == post_id).order_by(Like.created_at).all()]
    return {"like_count": count, "liked_by": authors}


def get_posts(db: Session, board_id: int, limit: int = 50, offset: int = 0, tag: str | None = None) -> list[dict]:
    query = (
        db.query(Post)
        .filter(Post.board_id == board_id, Post.parent_id == None, Post.is_deleted == False)
    )
    if tag:
        query = query.filter(Post.tag == tag)
    posts = (
        query
        .order_by(desc(Post.is_pinned), desc(Post.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    result = []
    for p in posts:
        reply_count = (
            db.query(func.count(Post.id))
            .filter(Post.parent_id == p.id, Post.is_deleted == False)
            .scalar()
        )
        like_info = _get_like_info(db, p.id)
        result.append({"post": p, "reply_count": reply_count, **like_info})
    return result


def get_post(db: Session, post_id: int) -> dict | None:
    post = db.query(Post).filter(Post.id == post_id, Post.is_deleted == False).first()
    if not post:
        return None
    replies = (
        db.query(Post)
        .filter(Post.parent_id == post_id, Post.is_deleted == False)
        .order_by(Post.created_at)
        .all()
    )
    board = db.query(Board).filter(Board.id == post.board_id).first()
    like_info = _get_like_info(db, post.id)
    replies_with_likes = []
    for r in replies:
        r_like = _get_like_info(db, r.id)
        replies_with_likes.append({"reply": r, **r_like})
    return {"post": post, "replies": replies_with_likes, "board": board, **like_info}


def create_post(db: Session, data: PostCreate) -> Post:
    board = get_board_by_slug(db, data.board_slug)
    if not board:
        raise ValueError(f"Board '{data.board_slug}' not found")
    # 태그 기본값 + 검증 (Board.allowed_tags 기반)
    tag = data.tag
    if board.default_tag and not tag:
        tag = board.default_tag
    if board.allowed_tags and tag:
        allowed = {t.strip() for t in board.allowed_tags.split(",") if t.strip()}
        if tag not in allowed:
            raise ValueError(f"Tag '{tag}' not allowed. Allowed: {', '.join(sorted(allowed))}")
    post = Post(
        board_id=board.id,
        title=data.title,
        content=data.content,
        author=data.author,
        prefix=data.prefix,
        tag=tag,
        is_pinned=data.is_pinned,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    from app.event_queue import emit_event
    emit_event(post, board, "post")
    return post


def create_reply(db: Session, post_id: int, data: ReplyCreate) -> Post:
    parent = db.query(Post).filter(Post.id == post_id, Post.is_deleted == False).first()
    if not parent:
        raise ValueError(f"Post {post_id} not found")
    reply = Post(
        board_id=parent.board_id,
        parent_id=post_id,
        content=data.content,
        author=data.author,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)
    from app.event_queue import emit_event
    board = db.query(Board).filter(Board.id == parent.board_id).first()
    emit_event(reply, board, "reply", parent_post=parent)
    return reply


def update_post(db: Session, post_id: int, title: str | None = None, content: str | None = None,
                prefix: str | None = None, tag: str | None = None) -> Post | None:
    post = db.query(Post).filter(Post.id == post_id, Post.is_deleted == False).first()
    if not post:
        return None
    if tag is not None:
        board = db.query(Board).filter(Board.id == post.board_id).first()
        if board and board.allowed_tags and tag:
            allowed = {t.strip() for t in board.allowed_tags.split(",") if t.strip()}
            if tag not in allowed:
                raise ValueError(f"Tag '{tag}' not allowed. Allowed: {', '.join(sorted(allowed))}")
    if title is not None:
        post.title = title
    if content is not None:
        post.content = content
    if prefix is not None:
        post.prefix = prefix
    if tag is not None:
        post.tag = tag
    db.commit()
    db.refresh(post)
    return post


def update_reply(db: Session, reply_id: int, content: str) -> Post | None:
    """댓글(parent_id가 있는 Post) 내용을 수정한다."""
    reply = db.query(Post).filter(
        Post.id == reply_id, Post.parent_id != None, Post.is_deleted == False
    ).first()
    if not reply:
        return None
    reply.content = content
    db.commit()
    db.refresh(reply)
    return reply


def delete_post(db: Session, post_id: int) -> bool:
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        return False
    post.is_deleted = True
    db.query(Post).filter(Post.parent_id == post_id).update({"is_deleted": True})
    db.query(Attachment).filter(Attachment.post_id == post_id).update({"is_deleted": True})
    reply_ids = [r.id for r in db.query(Post.id).filter(Post.parent_id == post_id).all()]
    if reply_ids:
        db.query(Attachment).filter(Attachment.post_id.in_(reply_ids)).update({"is_deleted": True})
    db.commit()
    return True


def restore_post(db: Session, post_id: int) -> bool:
    """소프트 삭제된 글을 복구한다."""
    post = db.query(Post).filter(Post.id == post_id, Post.is_deleted == True).first()
    if not post:
        return False
    post.is_deleted = False
    db.query(Post).filter(Post.parent_id == post_id, Post.is_deleted == True).update({"is_deleted": False})
    db.query(Attachment).filter(Attachment.post_id == post_id).update({"is_deleted": False})
    reply_ids = [r.id for r in db.query(Post.id).filter(Post.parent_id == post_id).all()]
    if reply_ids:
        db.query(Attachment).filter(Attachment.post_id.in_(reply_ids)).update({"is_deleted": False})
    db.commit()
    return True


def search_posts(db: Session, keyword: str, board_slug: str | None = None, limit: int = 20) -> list[dict]:
    query = db.query(Post).filter(
        Post.parent_id == None,
        Post.is_deleted == False,
        (Post.title.contains(keyword) | Post.content.contains(keyword)),
    )
    if board_slug:
        board = db.query(Board).filter(Board.slug == board_slug).first()
        if board:
            query = query.filter(Post.board_id == board.id)
    posts = query.order_by(desc(Post.created_at)).limit(limit).all()
    result = []
    for p in posts:
        board = db.query(Board).filter(Board.id == p.board_id).first()
        reply_count = db.query(func.count(Post.id)).filter(Post.parent_id == p.id, Post.is_deleted == False).scalar()
        like_info = _get_like_info(db, p.id)
        result.append({"post": p, "reply_count": reply_count, "board": board, **like_info})
    return result


def get_recent_posts(db: Session, limit: int = 10) -> list[dict]:
    posts = (
        db.query(Post)
        .filter(Post.parent_id == None, Post.is_deleted == False)
        .order_by(desc(Post.created_at))
        .limit(limit)
        .all()
    )
    result = []
    for p in posts:
        board = db.query(Board).filter(Board.id == p.board_id).first()
        reply_count = db.query(func.count(Post.id)).filter(Post.parent_id == p.id, Post.is_deleted == False).scalar()
        like_info = _get_like_info(db, p.id)
        result.append({"post": p, "reply_count": reply_count, "board": board, **like_info})
    return result


def get_recent_all_posts(db: Session, team: str | None = None, tag: str | None = None, scope: str = "all", limit: int = 30) -> list[dict]:
    """전체 게시판 최신글 조합 필터링.

    Args:
        team: 팀명 (예: "alpha") - 해당 팀 게시판만 필터
        tag: 태그 (예: "todo") - 해당 태그만 필터
        scope: 게시판 유형 필터
            - "all" (기본): 팀+글로벌 전체
            - "team": category="team"인 게시판만
            - "global": category="global"인 게시판만
        limit: 최대 조회 수
    """
    query = db.query(Post).join(Board, Post.board_id == Board.id).filter(
        Post.parent_id == None,
        Post.is_deleted == False,
        Board.is_active == True,
    )
    if scope == "team":
        query = query.filter(Board.category == "team")
    elif scope == "global":
        query = query.filter(Board.category == "global")
    if team:
        query = query.filter(Board.team == team)
    if tag:
        query = query.filter(Post.tag == tag)
    posts = query.order_by(desc(Post.created_at)).limit(limit).all()
    result = []
    for p in posts:
        board = db.query(Board).filter(Board.id == p.board_id).first()
        reply_count = db.query(func.count(Post.id)).filter(Post.parent_id == p.id, Post.is_deleted == False).scalar()
        like_info = _get_like_info(db, p.id)
        result.append({"post": p, "reply_count": reply_count, "board": board, **like_info})
    return result


def get_post_count(db: Session, board_id: int) -> int:
    return (
        db.query(func.count(Post.id))
        .filter(Post.board_id == board_id, Post.parent_id == None, Post.is_deleted == False)
        .scalar()
    )


# -- Like --

def toggle_like(db: Session, post_id: int, author: str) -> dict:
    """좋아요 토글. 이미 있으면 취소, 없으면 추가."""
    post = db.query(Post).filter(Post.id == post_id, Post.is_deleted == False).first()
    if not post:
        raise ValueError(f"Post {post_id} not found")
    existing = db.query(Like).filter(Like.post_id == post_id, Like.author == author).first()
    if existing:
        db.delete(existing)
        db.commit()
        action = "unliked"
    else:
        like = Like(post_id=post_id, author=author)
        db.add(like)
        db.commit()
        action = "liked"
    return {"action": action, **_get_like_info(db, post_id)}


def get_likes(db: Session, post_id: int) -> dict:
    return _get_like_info(db, post_id)


# -- Dashboard --

def get_dashboard_summary(db: Session) -> dict:
    """Dashboard summary stats."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    h24_ago = now - timedelta(hours=24)

    total = db.query(Post).join(Board).filter(
        Post.parent_id == None, Post.is_deleted == False, Board.is_active == True
    ).count()
    today = db.query(Post).join(Board).filter(
        Post.parent_id == None, Post.is_deleted == False, Board.is_active == True,
        Post.created_at >= today_start
    ).count()
    issues = db.query(Post).join(Board).filter(
        Post.parent_id == None, Post.is_deleted == False, Board.is_active == True,
        Post.tag == "issue"
    ).count()
    active_teams = db.query(Board.team).join(Post).filter(
        Post.is_deleted == False, Board.is_active == True, Board.category == "team",
        Post.parent_id == None, Post.created_at >= h24_ago
    ).distinct().count()
    return {
        "total_posts": total,
        "today_posts": today,
        "open_issues": issues,
        "active_teams_24h": active_teams,
    }


def get_team_stats(db: Session) -> list[dict]:
    """Per-team tag distribution."""
    rows = db.query(Board.team, Post.tag, func.count(Post.id)).join(Post).filter(
        Post.is_deleted == False, Board.is_active == True, Board.category == "team",
        Post.parent_id == None,
    ).group_by(Board.team, Post.tag).all()

    teams: dict[str, dict] = {}
    for team, tag, count in rows:
        if team not in teams:
            teams[team] = {"team": team, "work": 0, "todo": 0, "issue": 0, "done": 0, "knowhow": 0}
        if tag and tag in teams[team]:
            teams[team][tag] = count
    return list(teams.values())


def get_tag_distribution(db: Session) -> list[dict]:
    """Overall tag distribution."""
    rows = db.query(Post.tag, func.count(Post.id)).join(Board).filter(
        Post.is_deleted == False, Board.is_active == True, Post.parent_id == None,
    ).group_by(Post.tag).all()
    return [{"tag": tag or "none", "count": count} for tag, count in rows]


def get_recent_activity(db: Session, limit: int = 10) -> list[dict]:
    """Recent posts and replies combined."""
    posts = db.query(Post, Board).join(Board, Post.board_id == Board.id).filter(
        Post.parent_id == None, Post.is_deleted == False, Board.is_active == True
    ).order_by(desc(Post.created_at)).limit(limit).all()

    replies_q = (
        db.query(Post, Board)
        .join(Board, Post.board_id == Board.id)
        .filter(Post.parent_id != None, Post.is_deleted == False, Board.is_active == True)
        .order_by(desc(Post.created_at))
        .limit(limit)
        .all()
    )

    activities = []
    for post, board in posts:
        activities.append({
            "type": "post",
            "title": post.title or "(제목 없음)",
            "author": post.author,
            "board_name": board.name,
            "board_slug": board.slug,
            "post_id": post.id,
            "tag": post.tag,
            "created_at": post.created_at.isoformat(),
        })
    for reply, board in replies_q:
        parent = db.query(Post).filter(Post.id == reply.parent_id).first()
        parent_title = parent.title if parent and parent.title else "(제목 없음)"
        activities.append({
            "type": "reply",
            "title": f"Re: {parent_title}",
            "author": reply.author,
            "board_name": board.name,
            "board_slug": board.slug,
            "post_id": reply.parent_id,
            "tag": parent.tag if parent else None,
            "created_at": reply.created_at.isoformat(),
        })
    activities.sort(key=lambda x: x["created_at"], reverse=True)
    return activities[:limit]


def get_recent_posts_activity(db: Session, limit: int = 10) -> list[dict]:
    """최근 게시글 목록 (첨부파일 유무 포함)."""
    posts = db.query(Post, Board).join(Board, Post.board_id == Board.id).filter(
        Post.parent_id == None, Post.is_deleted == False, Board.is_active == True
    ).order_by(desc(Post.created_at)).limit(limit).all()

    result = []
    for post, board in posts:
        att_count = db.query(func.count(Attachment.id)).filter(
            Attachment.post_id == post.id, Attachment.is_deleted == False
        ).scalar()
        reply_count = db.query(func.count(Post.id)).filter(
            Post.parent_id == post.id, Post.is_deleted == False
        ).scalar()
        result.append({
            "title": post.title or "(제목 없음)",
            "author": post.author,
            "board_name": board.name,
            "board_slug": board.slug,
            "post_id": post.id,
            "tag": post.tag,
            "has_attachments": att_count > 0,
            "reply_count": reply_count,
            "created_at": post.created_at.isoformat(),
        })
    return result


def get_recent_replies_activity(db: Session, limit: int = 10) -> list[dict]:
    """최근 댓글 목록 (원글 제목 + 첨부파일 유무 포함)."""
    replies_q = (
        db.query(Post, Board)
        .join(Board, Post.board_id == Board.id)
        .filter(Post.parent_id != None, Post.is_deleted == False, Board.is_active == True)
        .order_by(desc(Post.created_at))
        .limit(limit)
        .all()
    )

    result = []
    for reply, board in replies_q:
        parent = db.query(Post).filter(Post.id == reply.parent_id).first()
        raw = (reply.content or "").split("\n")[0].strip()
        # 마크다운 문법 제거 (##, **, -, * 등)
        first_line = re.sub(r'^[#*\->\s]+', '', raw).strip() or "(내용 없음)"
        att_count = db.query(func.count(Attachment.id)).filter(
            Attachment.post_id == reply.id, Attachment.is_deleted == False
        ).scalar()
        result.append({
            "title": first_line,
            "author": reply.author,
            "board_name": board.name,
            "board_slug": board.slug,
            "post_id": reply.parent_id,
            "tag": parent.tag if parent else None,
            "has_attachments": att_count > 0,
            "created_at": reply.created_at.isoformat(),
        })
    return result


def get_daily_post_counts(db: Session, days: int = 14) -> list[dict]:
    """Get daily post counts for the last N days (including today)."""
    start_date = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.date(Post.created_at).label("date"),
        func.count(Post.id).label("count"),
    ).join(Board).filter(
        Post.is_deleted == False,
        Board.is_active == True,
        Post.parent_id == None,
        Post.created_at >= start_date,
    ).group_by(func.date(Post.created_at)).order_by(func.date(Post.created_at)).all()

    counts_map = {str(r.date): r.count for r in rows}
    result = []
    current = start_date.date()
    end = datetime.utcnow().date()
    while current <= end:
        date_str = str(current)
        result.append({"date": date_str, "count": counts_map.get(date_str, 0)})
        current += timedelta(days=1)
    return result


def get_daily_post_counts_by_team(db: Session, days: int = 14) -> dict:
    """Get daily post counts grouped by team for the last N days."""
    start_date = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.date(Post.created_at).label("date"),
        Board.team,
        func.count(Post.id).label("count"),
    ).join(Board).filter(
        Post.is_deleted == False,
        Board.is_active == True,
        Post.parent_id == None,
        Post.created_at >= start_date,
        Board.category == "team",
    ).group_by(func.date(Post.created_at), Board.team).all()

    global_rows = db.query(
        func.date(Post.created_at).label("date"),
        func.count(Post.id).label("count"),
    ).join(Board).filter(
        Post.is_deleted == False,
        Board.is_active == True,
        Post.parent_id == None,
        Post.created_at >= start_date,
        Board.category == "global",
    ).group_by(func.date(Post.created_at)).all()

    current = start_date.date()
    end = datetime.utcnow().date()
    dates = []
    while current <= end:
        dates.append(str(current))
        current += timedelta(days=1)

    teams: dict[str, dict] = {}
    for date_val, team, count in rows:
        if team not in teams:
            teams[team] = {}
        teams[team][str(date_val)] = count

    global_map = {str(r.date): r.count for r in global_rows}

    result: dict = {
        "dates": dates,
        "teams": {},
    }
    for team, date_counts in teams.items():
        result["teams"][team] = [date_counts.get(d, 0) for d in dates]
    result["teams"]["global"] = [global_map.get(d, 0) for d in dates]

    return result


def get_last_activity(db: Session) -> dict:
    """글 작성/수정/댓글/좋아요 중 가장 최근 활동 시간을 반환한다."""
    last_post_at = db.query(func.max(Post.created_at)).filter(
        Post.parent_id == None, Post.is_deleted == False
    ).scalar()
    last_updated_at = db.query(func.max(Post.updated_at)).filter(
        Post.parent_id == None, Post.is_deleted == False
    ).scalar()
    last_comment_at = db.query(func.max(Post.created_at)).filter(
        Post.parent_id != None, Post.is_deleted == False
    ).scalar()
    last_like_at = db.query(func.max(Like.created_at)).scalar()
    candidates = [t for t in [last_post_at, last_updated_at, last_comment_at, last_like_at] if t is not None]
    last_activity_at = max(candidates) if candidates else None
    return {
        "last_post_at": last_post_at,
        "last_updated_at": last_updated_at,
        "last_comment_at": last_comment_at,
        "last_like_at": last_like_at,
        "last_activity_at": last_activity_at,
    }


# -- AccessPassword --

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _now_kst():
    """현재 KST 시각 (timezone-aware)."""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst)

def verify_password(db: Session, password: str, visitor_id: str | None = None) -> dict:
    """비밀번호 검증 - 유효하면 타입/만료일 반환."""
    pw_hash = _hash_pw(password)
    pw = db.query(AccessPassword).filter(
        AccessPassword.password_hash == pw_hash,
        AccessPassword.is_active == True,
    ).first()

    if not pw:
        return {"valid": False}

    now = _now_kst()
    if pw.expires_at is not None:
        exp = pw.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone(timedelta(hours=9)))
        if exp < now:
            return {"valid": False, "expired": True, "label": pw.label}

    if pw.password_type == "user" and visitor_id:
        if pw.bound_visitor_id is None:
            pw.bound_visitor_id = visitor_id
            db.commit()
        elif pw.bound_visitor_id != visitor_id:
            return {"valid": False, "bound_to_other": True, "label": pw.label}

    return {
        "valid": True,
        "password_type": pw.password_type,
        "label": pw.label,
        "expires_at": pw.expires_at.isoformat() if pw.expires_at else None,
    }

def list_passwords(db: Session) -> list[dict]:
    """모든 비밀번호 목록 (관리자용)."""
    pws = db.query(AccessPassword).filter(AccessPassword.is_active == True).order_by(AccessPassword.created_at.desc()).all()
    now = _now_kst()
    result = []
    for pw in pws:
        expired = False
        if pw.expires_at is not None:
            exp = pw.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone(timedelta(hours=9)))
            expired = exp < now
        result.append({
            "id": pw.id,
            "label": pw.label,
            "password_type": pw.password_type,
            "expires_at": pw.expires_at.isoformat() if pw.expires_at else None,
            "expired": expired,
            "is_active": pw.is_active,
            "created_at": pw.created_at.isoformat() if pw.created_at else None,
            "bound_visitor_id": pw.bound_visitor_id,
            "password_plain": pw.password_plain,
        })
    return result

def create_password(db: Session, password: str, label: str, password_type: str = "user", expires_hours: float | None = None) -> dict:
    """새 비밀번호 발급."""
    pw_hash = _hash_pw(password)

    existing = db.query(AccessPassword).filter(
        AccessPassword.password_hash == pw_hash,
        AccessPassword.is_active == True,
    ).first()
    if existing:
        raise ValueError("이미 동일한 비밀번호가 존재합니다")

    now = _now_kst()
    expires_at = None
    if expires_hours is not None:
        expires_at = now + timedelta(hours=expires_hours)

    pw = AccessPassword(
        password_hash=pw_hash,
        label=label,
        password_type=password_type,
        expires_at=expires_at,
        password_plain=password,
    )
    db.add(pw)
    db.commit()
    db.refresh(pw)

    return {
        "id": pw.id,
        "label": pw.label,
        "password_type": pw.password_type,
        "expires_at": pw.expires_at.isoformat() if pw.expires_at else None,
    }

def update_password_action(db: Session, pw_id: int, action: str, minutes: int | None = None) -> dict:
    """비밀번호 만료시간 변경."""
    pw = db.query(AccessPassword).filter(AccessPassword.id == pw_id, AccessPassword.is_active == True).first()
    if not pw:
        raise ValueError("비밀번호를 찾을 수 없습니다")

    now = _now_kst()

    if action == "extend":
        if not minutes:
            raise ValueError("minutes 필요")
        base = pw.expires_at or now
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone(timedelta(hours=9)))
        if base < now:
            base = now
        pw.expires_at = base + timedelta(minutes=minutes)

    elif action == "shorten":
        if not minutes:
            raise ValueError("minutes 필요")
        if pw.expires_at is None:
            raise ValueError("무기한 비밀번호는 단축 불가")
        base = pw.expires_at
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone(timedelta(hours=9)))
        pw.expires_at = base - timedelta(minutes=minutes)

    elif action == "expire_now":
        pw.expires_at = now - timedelta(seconds=1)

    elif action == "set":
        if minutes is None:
            pw.expires_at = None
        else:
            pw.expires_at = now + timedelta(minutes=minutes)

    elif action == "unbind":
        pw.bound_visitor_id = None

    else:
        raise ValueError(f"알 수 없는 액션: {action}")

    db.commit()
    db.refresh(pw)

    return {
        "id": pw.id,
        "label": pw.label,
        "expires_at": pw.expires_at.isoformat() if pw.expires_at else None,
        "bound_visitor_id": pw.bound_visitor_id,
    }

def delete_password(db: Session, pw_id: int) -> bool:
    """비밀번호 소프트 삭제."""
    pw = db.query(AccessPassword).filter(AccessPassword.id == pw_id).first()
    if not pw:
        return False
    pw.is_active = False
    db.commit()
    return True


def has_any_admin_password(db: Session) -> bool:
    """admin 타입 비밀번호가 하나라도 있는지 확인."""
    return db.query(AccessPassword).filter(
        AccessPassword.password_type == "admin",
        AccessPassword.is_active == True,
    ).first() is not None


# -- Attachment --

def create_attachment(db: Session, post_id: int, filename: str, stored_name: str,
                      file_size: int, mime_type: str | None, uploader: str) -> Attachment:
    att = Attachment(
        post_id=post_id, filename=filename, stored_name=stored_name,
        file_size=file_size, mime_type=mime_type, uploader=uploader,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def get_attachments(db: Session, post_id: int) -> list[Attachment]:
    return db.query(Attachment).filter(
        Attachment.post_id == post_id, Attachment.is_deleted == False
    ).order_by(Attachment.created_at).all()


def get_attachment(db: Session, attachment_id: int) -> Attachment | None:
    return db.query(Attachment).filter(
        Attachment.id == attachment_id, Attachment.is_deleted == False
    ).first()


def delete_attachment(db: Session, attachment_id: int) -> bool:
    att = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not att:
        return False
    att.is_deleted = True
    db.commit()
    return True


# -- Token Usage --

def get_token_usage_chart(db: Session, period: str = "7d",
                          group_by: str = "account") -> dict:
    """토큰 사용량 차트 데이터. period: 1d/7d/30d/90d, group_by: account/team."""
    from collections import defaultdict

    days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    days = days_map.get(period, 7)
    start = datetime.now() - timedelta(days=days)

    rows = db.query(TokenUsage).filter(TokenUsage.date >= start).all()

    # 1D: 오늘 팀별 바 차트
    if period == "1d":
        today = datetime.now().strftime("%Y-%m-%d")
        team_totals = defaultdict(float)
        for r in rows:
            d = r.date.strftime("%Y-%m-%d") if hasattr(r.date, 'strftime') else str(r.date)
            if d == today:
                group = r.account if group_by == "account" else r.team
                team_totals[group] += r.cost

        labels = sorted(team_totals.keys())
        values = [round(team_totals[k], 2) for k in labels]
        return {
            "chart_type": "bar",
            "labels": labels,
            "values": values,
            "total_sum": round(sum(values), 2),
            "period": period,
            "group_by": group_by,
        }

    # 7d/30d/90d: 날짜별 라인 차트
    data = defaultdict(lambda: defaultdict(float))
    all_dates = set()
    all_groups = set()

    for r in rows:
        d = r.date.strftime("%Y-%m-%d") if hasattr(r.date, 'strftime') else str(r.date)
        group = r.account if group_by == "account" else r.team
        data[group][d] += r.cost
        all_dates.add(d)
        all_groups.add(group)

    dates = sorted(all_dates)
    series = {}
    total = [0.0] * len(dates)
    for group in sorted(all_groups):
        values = []
        for i, d in enumerate(dates):
            v = round(data[group].get(d, 0), 2)
            values.append(v)
            total[i] += v
        series[group] = values

    total = [round(t, 2) for t in total]

    return {
        "chart_type": "line",
        "dates": dates,
        "series": series,
        "total": total,
        "period": period,
        "group_by": group_by,
    }
