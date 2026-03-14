"""FastAPI 앱. 게시판 REST API + HTML 라우터 + 팀/셋업 관리 API."""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, Form, Header, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db, init_db, DB_PATH
from app.seed import seed_data
from app import crud
from app.schemas import (
    BoardCreate, PostCreate, PostUpdate, ReplyCreate, ReplyUpdate, LikeCreate,
    VerifyRequest, PasswordCreate, PasswordAction,
    TeamCreate, TeamUpdate, SetupInit,
)

UPLOAD_DIR = Path(os.path.dirname(DB_PATH)) / "uploads"
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.event_queue import ensure_dirs, cleanup_done
    ensure_dirs()
    cleanup_done()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    db = next(get_db())
    try:
        seed_data(db)
    finally:
        db.close()
    # seed 후 pending 비우기 (seed 데이터는 이벤트 대상 아님)
    from app.event_queue import PENDING
    import os as _os
    for f in _os.listdir(str(PENDING)):
        try:
            (PENDING / f).unlink()
        except OSError:
            pass
    yield


app = FastAPI(title="Claude Board", lifespan=lifespan)

# static/templates 마운트 (존재할 때만)
_static_dir = Path(__file__).parent / "static"
_templates_dir = Path(__file__).parent / "templates"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
if _templates_dir.exists():
    templates = Jinja2Templates(directory=str(_templates_dir))
else:
    templates = None


def _get_prefix(request: Request) -> str:
    """프록시 prefix를 읽음 (헤더 -> 쿼리 파라미터 순으로 탐색)."""
    prefix = request.headers.get("x-forwarded-prefix", "")
    if not prefix:
        prefix = request.query_params.get("_bp", "")
    return prefix.rstrip("/")


def _ctx(request: Request, **kwargs):
    """템플릿 컨텍스트 생성."""
    return {
        "request": request,
        "bp": _get_prefix(request),
        **kwargs,
    }


def _redirect(request: Request, path: str) -> RedirectResponse:
    """프록시 prefix를 포함한 리다이렉트."""
    bp = _get_prefix(request)
    return RedirectResponse(f"{bp}{path}", status_code=303)


def _time_ago(dt) -> str:
    if isinstance(dt, str):
        from datetime import datetime as _dt
        try:
            dt = _dt.fromisoformat(dt)
        except ValueError:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = datetime.now(timezone.utc) - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    if seconds < 604800:
        return f"{seconds // 86400}일 전"
    return dt.strftime("%Y-%m-%d")


if templates:
    templates.env.filters["time_ago"] = _time_ago


# -- HTML Pages --

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    if not templates:
        return HTMLResponse("<h1>Claude Board API</h1><p>No templates configured.</p>")
    summary = crud.get_dashboard_summary(db)
    team_stats = crud.get_team_stats(db)
    tag_distribution = crud.get_tag_distribution(db)
    recent_posts = crud.get_recent_posts_activity(db, limit=10)
    recent_replies = crud.get_recent_replies_activity(db, limit=10)
    daily_trend = crud.get_daily_post_counts(db)
    daily_trend_by_team = crud.get_daily_post_counts_by_team(db)
    token_usage = crud.get_token_usage_chart(db, period="7d", group_by="team")
    return templates.TemplateResponse("dashboard.html", _ctx(request,
        summary=summary, team_stats=team_stats, tag_distribution=tag_distribution,
        recent_posts=recent_posts, recent_replies=recent_replies,
        daily_trend=daily_trend, daily_trend_by_team=daily_trend_by_team,
        token_usage=token_usage,
    ))


@app.get("/boards", response_class=HTMLResponse)
def boards_page(request: Request, db: Session = Depends(get_db)):
    if not templates:
        raise HTTPException(404)
    boards = crud.get_boards(db)
    return templates.TemplateResponse("index.html", _ctx(request, boards=boards))


@app.get("/board/{slug}", response_class=HTMLResponse)
def board_page(slug: str, request: Request, page: int = 1, tag: str | None = None, db: Session = Depends(get_db)):
    if not templates:
        raise HTTPException(404)
    board = crud.get_board_by_slug(db, slug)
    if not board:
        raise HTTPException(404, "게시판을 찾을 수 없습니다")
    limit = 20
    offset = (page - 1) * limit
    posts = crud.get_posts(db, board.id, limit=limit, offset=offset, tag=tag)
    total = crud.get_post_count(db, board.id)
    total_pages = max(1, (total + limit - 1) // limit)
    return templates.TemplateResponse("board.html", _ctx(request,
        board=board, posts=posts, page=page, total_pages=total_pages, total=total,
    ))


@app.get("/post/{post_id}", response_class=HTMLResponse)
def post_page(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not templates:
        raise HTTPException(404)
    data = crud.get_post(db, post_id)
    if not data:
        raise HTTPException(404, "게시글을 찾을 수 없습니다")
    data["attachments"] = crud.get_attachments(db, post_id)
    for item in data["replies"]:
        item["attachments"] = crud.get_attachments(db, item["reply"].id)
    return templates.TemplateResponse("post.html", _ctx(request, **data))


# -- Like Form Action --

@app.post("/action/like/{post_id}")
def action_toggle_like(
    post_id: int,
    request: Request,
    author: str = Form("anonymous"),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        crud.toggle_like(db, post_id, author or "anonymous")
    except ValueError:
        raise HTTPException(404, "게시글을 찾을 수 없습니다")
    if redirect_to:
        return RedirectResponse(redirect_to, status_code=303)
    return _redirect(request, f"/post/{post_id}")


@app.get("/new/{slug}", response_class=HTMLResponse)
def new_post_page(slug: str, request: Request, db: Session = Depends(get_db)):
    if not templates:
        raise HTTPException(404)
    board = crud.get_board_by_slug(db, slug)
    if not board:
        raise HTTPException(404, "게시판을 찾을 수 없습니다")
    return templates.TemplateResponse("new_post.html", _ctx(request, board=board))


# -- Form Actions --

@app.post("/action/post")
def action_create_post(
    request: Request,
    board_slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    author: str = Form(...),
    prefix: str = Form(""),
    tag: str = Form(""),
    db: Session = Depends(get_db),
):
    data = PostCreate(
        board_slug=board_slug, title=title, content=content,
        author=author, prefix=prefix or None, tag=tag or None,
    )
    post = crud.create_post(db, data)
    return _redirect(request, f"/post/{post.id}")


@app.post("/action/reply/{post_id}")
def action_create_reply(
    post_id: int,
    request: Request,
    content: str = Form(...),
    author: str = Form(...),
    db: Session = Depends(get_db),
):
    data = ReplyCreate(content=content, author=author)
    crud.create_reply(db, post_id, data)
    return _redirect(request, f"/post/{post_id}")


# -- REST API --

@app.get("/api/boards")
def api_list_boards(db: Session = Depends(get_db)):
    boards = crud.get_boards(db)
    return [
        {
            "id": b["board"].id, "name": b["board"].name, "slug": b["board"].slug,
            "category": b["board"].category, "team": b["board"].team,
            "icon": b["board"].icon, "description": b["board"].description,
            "post_count": b["post_count"],
        }
        for b in boards
    ]


@app.get("/api/posts")
def api_list_posts(board_slug: str | None = None, tag: str | None = None, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    if board_slug:
        board = crud.get_board_by_slug(db, board_slug)
        if not board:
            raise HTTPException(404, "Board not found")
        posts = crud.get_posts(db, board.id, limit=limit, offset=offset, tag=tag)
    else:
        posts = crud.get_recent_posts(db, limit=limit)
    return [
        {
            "id": p["post"].id, "title": p["post"].title, "author": p["post"].author,
            "prefix": p["post"].prefix, "tag": p["post"].tag, "is_pinned": p["post"].is_pinned,
            "created_at": p["post"].created_at.isoformat(),
            "updated_at": p["post"].updated_at.isoformat() if p["post"].updated_at else None,
            "reply_count": p["reply_count"],
            "like_count": p["like_count"], "liked_by": p["liked_by"],
        }
        for p in posts
    ]


@app.get("/api/posts/{post_id}")
def api_get_post(post_id: int, db: Session = Depends(get_db)):
    data = crud.get_post(db, post_id)
    if not data:
        raise HTTPException(404, "Post not found")
    return {
        "id": data["post"].id, "title": data["post"].title,
        "content": data["post"].content, "author": data["post"].author,
        "prefix": data["post"].prefix, "tag": data["post"].tag, "is_pinned": data["post"].is_pinned,
        "created_at": data["post"].created_at.isoformat(),
        "updated_at": data["post"].updated_at.isoformat() if data["post"].updated_at else None,
        "board_slug": data["board"].slug, "board_name": data["board"].name,
        "like_count": data["like_count"], "liked_by": data["liked_by"],
        "replies": [
            {
                "id": r["reply"].id, "content": r["reply"].content, "author": r["reply"].author,
                "created_at": r["reply"].created_at.isoformat(),
                "updated_at": r["reply"].updated_at.isoformat() if r["reply"].updated_at else None,
                "like_count": r["like_count"], "liked_by": r["liked_by"],
            }
            for r in data["replies"]
        ],
    }


@app.post("/api/posts")
def api_create_post(data: PostCreate, db: Session = Depends(get_db)):
    try:
        post = crud.create_post(db, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": post.id, "title": post.title, "created_at": post.created_at.isoformat()}


@app.post("/api/posts/{post_id}/reply")
def api_create_reply(post_id: int, data: ReplyCreate, db: Session = Depends(get_db)):
    try:
        reply = crud.create_reply(db, post_id, data)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"id": reply.id, "created_at": reply.created_at.isoformat()}


@app.post("/api/posts/{post_id}/like")
def api_toggle_like(post_id: int, data: LikeCreate, db: Session = Depends(get_db)):
    try:
        result = crud.toggle_like(db, post_id, data.author)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@app.get("/api/posts/{post_id}/likes")
def api_get_likes(post_id: int, db: Session = Depends(get_db)):
    return crud.get_likes(db, post_id)


@app.put("/api/posts/{post_id}")
def api_update_post(post_id: int, data: PostUpdate, db: Session = Depends(get_db)):
    try:
        post = crud.update_post(db, post_id, title=data.title, content=data.content,
                                prefix=data.prefix, tag=data.tag)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not post:
        raise HTTPException(404, "Post not found")
    return {
        "id": post.id, "title": post.title, "content": post.content,
        "prefix": post.prefix, "tag": post.tag,
        "updated_at": post.updated_at.isoformat() if post.updated_at else None,
    }


@app.put("/api/replies/{reply_id}")
def api_update_reply(reply_id: int, data: ReplyUpdate, db: Session = Depends(get_db)):
    reply = crud.update_reply(db, reply_id, data.content)
    if not reply:
        raise HTTPException(404, "Reply not found")
    return {
        "id": reply.id, "content": reply.content,
        "updated_at": reply.updated_at.isoformat() if reply.updated_at else None,
    }


@app.delete("/api/posts/{post_id}")
def api_delete_post(post_id: int, db: Session = Depends(get_db)):
    ok = crud.delete_post(db, post_id)
    if not ok:
        raise HTTPException(404, "Post not found")
    return {"ok": True}


@app.post("/api/posts/{post_id}/restore")
def api_restore_post(post_id: int, db: Session = Depends(get_db)):
    ok = crud.restore_post(db, post_id)
    if not ok:
        raise HTTPException(404, "Post not found or not deleted")
    return {"ok": True, "post_id": post_id}


@app.post("/api/boards")
def api_create_board(data: BoardCreate, db: Session = Depends(get_db)):
    existing = crud.get_board_by_slug(db, data.slug)
    if existing:
        raise HTTPException(409, f"Board '{data.slug}' already exists")
    board = crud.create_board(db, data)
    return {"id": board.id, "slug": board.slug}


@app.get("/recent-all", response_class=HTMLResponse)
def recent_all_page(request: Request, team: str | None = None, tag: str | None = None, scope: str = "all", limit: int = 30, db: Session = Depends(get_db)):
    if not templates:
        raise HTTPException(404)
    posts = crud.get_recent_all_posts(db, team=team, tag=tag, scope=scope, limit=limit)
    return templates.TemplateResponse("recent_all.html", _ctx(request,
        posts=posts, team=team, tag=tag, scope=scope, limit=limit,
    ))


@app.get("/api/recent-all")
def api_recent_all(team: str | None = None, tag: str | None = None, scope: str = "all", limit: int = 30, db: Session = Depends(get_db)):
    results = crud.get_recent_all_posts(db, team=team, tag=tag, scope=scope, limit=limit)
    return [
        {
            "id": r["post"].id, "title": r["post"].title, "author": r["post"].author,
            "prefix": r["post"].prefix, "tag": r["post"].tag,
            "is_pinned": r["post"].is_pinned,
            "board_slug": r["board"].slug if r["board"] else "",
            "board_name": r["board"].name if r["board"] else "",
            "created_at": r["post"].created_at.isoformat(),
            "updated_at": r["post"].updated_at.isoformat() if r["post"].updated_at else None,
            "reply_count": r["reply_count"],
            "like_count": r["like_count"], "liked_by": r["liked_by"],
        }
        for r in results
    ]


@app.get("/api/search")
def api_search(q: str, board_slug: str | None = None, limit: int = 20, db: Session = Depends(get_db)):
    results = crud.search_posts(db, q, board_slug=board_slug, limit=limit)
    return [
        {
            "id": r["post"].id, "title": r["post"].title, "author": r["post"].author,
            "board_slug": r["board"].slug if r["board"] else "",
            "board_name": r["board"].name if r["board"] else "",
            "created_at": r["post"].created_at.isoformat(),
            "updated_at": r["post"].updated_at.isoformat() if r["post"].updated_at else None,
            "reply_count": r["reply_count"],
            "like_count": r["like_count"],
        }
        for r in results
    ]


@app.get("/api/recent")
def api_recent(limit: int = 10, db: Session = Depends(get_db)):
    results = crud.get_recent_posts(db, limit=limit)
    return [
        {
            "id": r["post"].id, "title": r["post"].title, "author": r["post"].author,
            "board_slug": r["board"].slug if r["board"] else "",
            "board_name": r["board"].name if r["board"] else "",
            "created_at": r["post"].created_at.isoformat(),
            "updated_at": r["post"].updated_at.isoformat() if r["post"].updated_at else None,
            "reply_count": r["reply_count"],
            "like_count": r["like_count"],
        }
        for r in results
    ]


# -- Dashboard API --

@app.get("/api/dashboard/summary")
def api_dashboard_summary(db: Session = Depends(get_db)):
    return crud.get_dashboard_summary(db)


@app.get("/api/dashboard/team-stats")
def api_dashboard_team_stats(db: Session = Depends(get_db)):
    return crud.get_team_stats(db)


@app.get("/api/dashboard/tag-distribution")
def api_dashboard_tag_distribution(db: Session = Depends(get_db)):
    return crud.get_tag_distribution(db)


@app.get("/api/dashboard/recent-activity")
def api_dashboard_recent_activity(limit: int = 10, db: Session = Depends(get_db)):
    return crud.get_recent_activity(db, limit=limit)


@app.get("/api/dashboard/daily-trend")
def api_daily_trend(days: int = 14, db: Session = Depends(get_db)):
    return crud.get_daily_post_counts(db, days=days)


@app.get("/api/dashboard/daily-trend-by-team")
def api_daily_trend_by_team(days: int = 14, db: Session = Depends(get_db)):
    return crud.get_daily_post_counts_by_team(db, days=days)


@app.get("/api/last-activity")
def api_last_activity(db: Session = Depends(get_db)):
    data = crud.get_last_activity(db)
    def _iso(dt) -> str | None:
        return dt.isoformat() if dt else None
    return {
        "last_post_at": _iso(data["last_post_at"]),
        "last_updated_at": _iso(data["last_updated_at"]),
        "last_comment_at": _iso(data["last_comment_at"]),
        "last_like_at": _iso(data["last_like_at"]),
        "last_activity_at": _iso(data["last_activity_at"]),
    }


@app.get("/api/token-usage")
def api_token_usage(period: str = "7d", group_by: str = "team",
                    db: Session = Depends(get_db)):
    return crud.get_token_usage_chart(db, period=period, group_by=group_by)


@app.post("/api/token-usage/collect")
def api_collect_token_usage(since: str = None, db: Session = Depends(get_db)):
    from app.token_collector import collect_all
    return collect_all(db, since=since)


# -- Attachment API --

@app.post("/api/posts/{post_id}/attachments")
async def api_upload_attachment(
    post_id: int,
    file: UploadFile = File(...),
    uploader: str = Form("anonymous"),
    db: Session = Depends(get_db),
):
    post = db.query(crud.Post).filter(crud.Post.id == post_id, crud.Post.is_deleted == False).first()
    if not post:
        raise HTTPException(404, "Post not found")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "파일 크기가 20MB를 초과합니다")
    post_dir = UPLOAD_DIR / str(post_id)
    post_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    (post_dir / stored_name).write_bytes(content)
    att = crud.create_attachment(
        db, post_id=post_id, filename=file.filename, stored_name=stored_name,
        file_size=len(content), mime_type=file.content_type, uploader=uploader,
    )
    return {
        "id": att.id, "filename": att.filename, "stored_name": att.stored_name,
        "file_size": att.file_size, "mime_type": att.mime_type,
        "created_at": att.created_at.isoformat(),
    }


@app.get("/api/posts/{post_id}/attachments")
def api_list_attachments(post_id: int, db: Session = Depends(get_db)):
    atts = crud.get_attachments(db, post_id)
    return [
        {
            "id": a.id, "filename": a.filename, "stored_name": a.stored_name,
            "file_size": a.file_size, "mime_type": a.mime_type, "uploader": a.uploader,
            "created_at": a.created_at.isoformat(),
        }
        for a in atts
    ]


@app.get("/api/attachments/{attachment_id}/download")
def api_download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    att = crud.get_attachment(db, attachment_id)
    if not att:
        raise HTTPException(404, "첨부파일을 찾을 수 없습니다")
    file_path = UPLOAD_DIR / str(att.post_id) / att.stored_name
    if not file_path.exists():
        raise HTTPException(404, "파일이 존재하지 않습니다")
    return FileResponse(
        path=str(file_path),
        filename=att.filename,
        media_type=att.mime_type or "application/octet-stream",
    )


@app.delete("/api/attachments/{attachment_id}")
def api_delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    ok = crud.delete_attachment(db, attachment_id)
    if not ok:
        raise HTTPException(404, "첨부파일을 찾을 수 없습니다")
    return {"ok": True}


# -- Admin / Auth API --

def _verify_admin(x_admin_password: str = Header(None), db: Session = Depends(get_db)):
    """관리자 비밀번호 검증 의존성."""
    if not x_admin_password:
        raise HTTPException(401, "인증 필요")
    result = crud.verify_password(db, x_admin_password)
    if not result.get("valid") or result.get("password_type") != "admin":
        raise HTTPException(403, "관리자 권한 필요")
    return result


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    if not templates:
        raise HTTPException(404)
    return templates.TemplateResponse("admin.html", _ctx(request))


@app.post("/api/auth/verify")
def api_auth_verify(data: VerifyRequest, db: Session = Depends(get_db)):
    result = crud.verify_password(db, data.password, data.visitor_id)
    return result


@app.get("/api/admin/passwords")
def api_list_passwords(
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    return crud.list_passwords(db)


@app.post("/api/admin/passwords")
def api_create_password(
    data: PasswordCreate,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    try:
        result = crud.create_password(
            db, data.password, data.label, data.password_type, data.expires_hours,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return result


@app.patch("/api/admin/passwords/{pw_id}")
def api_update_password(
    pw_id: int,
    data: PasswordAction,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    try:
        result = crud.update_password_action(db, pw_id, data.action, data.minutes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@app.delete("/api/admin/passwords/{pw_id}")
def api_delete_password(
    pw_id: int,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    ok = crud.delete_password(db, pw_id)
    if not ok:
        raise HTTPException(404, "비밀번호를 찾을 수 없습니다")
    return {"ok": True}


# -- Team Admin API --

# 인증 불필요 — MCP instructions 생성 + 사이드바 팀 목록 로드용으로 공개
@app.get("/api/admin/teams")
def api_list_teams(db: Session = Depends(get_db)):
    """팀 목록 조회 (활성+비활성 전부)."""
    teams = crud.get_teams(db, active_only=False)
    return [
        {
            "id": t.id, "name": t.name, "slug": t.slug,
            "icon": t.icon, "color": t.color, "color_dark": t.color_dark,
            "description": t.description, "sort_order": t.sort_order,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in teams
    ]


@app.post("/api/admin/teams")
def api_create_team(
    data: TeamCreate,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    """팀 생성 + 업무게시판 자동 생성."""
    existing = crud.get_team_by_slug(db, data.slug)
    if existing:
        raise HTTPException(409, f"Team '{data.slug}' already exists")
    team, board = crud.create_team(db, data)
    return {
        "team": {
            "id": team.id, "name": team.name, "slug": team.slug,
            "icon": team.icon, "color": team.color,
        },
        "board": {
            "id": board.id, "slug": board.slug, "name": board.name,
        },
    }


@app.put("/api/admin/teams/{team_id}")
def api_update_team(
    team_id: int,
    data: TeamUpdate,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    """팀 정보 수정."""
    team = crud.update_team(db, team_id, data)
    if not team:
        raise HTTPException(404, "Team not found")
    return {
        "id": team.id, "name": team.name, "slug": team.slug,
        "icon": team.icon, "color": team.color, "color_dark": team.color_dark,
        "description": team.description, "sort_order": team.sort_order,
        "is_active": team.is_active,
    }


@app.delete("/api/admin/teams/{team_id}")
def api_delete_team(
    team_id: int,
    _admin=Depends(_verify_admin),
    db: Session = Depends(get_db),
):
    """팀 삭제 (소프트 삭제 + 게시판 비활성화)."""
    ok = crud.delete_team(db, team_id)
    if not ok:
        raise HTTPException(404, "Team not found")
    return {"ok": True}


# -- Setup API --

@app.get("/api/setup/status")
def api_setup_status(db: Session = Depends(get_db)):
    """초기 설정 완료 여부. admin 비밀번호가 하나도 없으면 미설정."""
    return {"setup_complete": crud.has_any_admin_password(db)}


@app.post("/api/setup/init")
def api_setup_init(data: SetupInit, db: Session = Depends(get_db)):
    """초기 설정: admin 비밀번호 생성 + 선택적으로 첫 팀 생성."""
    if crud.has_any_admin_password(db):
        raise HTTPException(409, "이미 초기 설정이 완료되었습니다")

    # admin 비밀번호 생성
    pw_result = crud.create_password(
        db, data.admin_password, data.admin_label, "admin", expires_hours=None,
    )

    result = {"admin_password": pw_result}

    # 첫 팀 생성 (선택)
    if data.team_name and data.team_slug:
        team_data = TeamCreate(
            name=data.team_name,
            slug=data.team_slug,
            icon=data.team_icon,
            color=data.team_color,
        )
        team, board = crud.create_team(db, team_data)
        result["team"] = {"id": team.id, "name": team.name, "slug": team.slug}
        result["board"] = {"id": board.id, "slug": board.slug}

    return result


# -- Config API --

@app.get("/api/config/teams-css")
def api_teams_css(db: Session = Depends(get_db)):
    """팀 색상 CSS 변수를 동적 생성하여 text/css로 반환."""
    teams = crud.get_teams(db, active_only=True)
    lines = [":root {"]
    for t in teams:
        lines.append(f"  --team-{t.slug}-color: {t.color};")
        if t.color_dark:
            lines.append(f"  --team-{t.slug}-color-dark: {t.color_dark};")
    lines.append("}")

    # 팀별 클래스
    for t in teams:
        lines.append(f".team-{t.slug} {{ color: {t.color}; }}")
        if t.color_dark:
            lines.append(f"@media (prefers-color-scheme: dark) {{ .team-{t.slug} {{ color: {t.color_dark}; }} }}")

    return Response(content="\n".join(lines), media_type="text/css")
