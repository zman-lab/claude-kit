"""이벤트 큐 관리. 게시글/댓글 생성 시 파일 기반 이벤트 발행.

PREFIX_TEAM_MAP을 하드코딩하지 않고 DB에서 동적으로 조회한다.
"""

import os, json, time, logging, tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

EVENT_DIR = Path(os.getenv("BOARD_EVENT_DIR", "/tmp/claude-board-events"))
PENDING = EVENT_DIR / "pending"
CLAIMED = EVENT_DIR / "claimed"
DONE = EVENT_DIR / "done"


def ensure_dirs():
    for d in (PENDING, CLAIMED, DONE):
        d.mkdir(parents=True, exist_ok=True)


def _get_prefix_team_map() -> dict[str, str]:
    """DB에서 활성 팀 목록을 조회하여 prefix -> team 매핑 생성.
    DB 접근 실패 시 빈 딕셔너리 반환 (graceful degradation)."""
    try:
        from app.database import SessionLocal
        from app.models import Team
        db = SessionLocal()
        try:
            teams = db.query(Team).filter(Team.is_active == True).all()
            mapping = {}
            for t in teams:
                mapping[f"[{t.slug}]"] = t.slug
            return mapping
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"팀 매핑 조회 실패 (non-fatal): {e}")
        return {}


def _resolve_target(prefix: str, board_slug: str) -> str:
    """prefix에서 대상 팀 추출. 없으면 board_slug에서 추론."""
    if prefix:
        prefix_team_map = _get_prefix_team_map()
        for pfx, team in prefix_team_map.items():
            if pfx in prefix.lower() or prefix.lower().startswith(pfx):
                return team
    # board_slug에서 추론 (예: "alpha-work" -> "alpha")
    if "-work" in board_slug:
        return board_slug.replace("-work", "")
    return "all"  # 공지/자유 등은 모든 세션 대상


def emit_event(post, board, event_type: str, parent_post=None):
    """게시글/댓글 생성 시 이벤트 파일 발행. 실패해도 예외 전파 안 함."""
    try:
        ensure_dirs()
        target = _resolve_target(
            getattr(post, 'prefix', '') or '',
            getattr(board, 'slug', '') or ''
        )
        event = {
            "id": post.id,
            "type": event_type,
            "board_slug": getattr(board, 'slug', ''),
            "board_name": getattr(board, 'name', ''),
            "prefix": getattr(post, 'prefix', ''),
            "tag": getattr(post, 'tag', ''),
            "title": post.title if hasattr(post, 'title') and post.title else (
                parent_post.title if parent_post else ""
            ),
            "author": getattr(post, 'author', ''),
            "target": target,
            "parent_id": getattr(post, 'parent_id', None),
            "ts": post.created_at.isoformat() if hasattr(post, 'created_at') and post.created_at else "",
        }
        # atomic write: tempfile -> rename
        filename = f"{target}_{post.id}.json"
        fd, tmp_path = tempfile.mkstemp(dir=str(PENDING), suffix=".tmp")
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(event, f, ensure_ascii=False)
            os.rename(tmp_path, str(PENDING / filename))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning(f"Event emit failed (non-fatal): {e}")


def claim_event(filename: str, session_id: str) -> dict | None:
    """이벤트 점유. rename atomic. 실패 시 None 반환."""
    try:
        src = PENDING / filename
        dst = CLAIMED / f"{session_id}_{filename}"
        os.rename(str(src), str(dst))
        with open(str(dst)) as f:
            return json.load(f)
    except (FileNotFoundError, OSError):
        return None


def complete_event(claimed_filename: str):
    """처리 완료. claimed -> done 이동."""
    try:
        src = CLAIMED / claimed_filename
        dst = DONE / claimed_filename
        os.rename(str(src), str(dst))
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"Event complete failed: {e}")


def list_pending(target: str = None) -> list[str]:
    """pending 이벤트 파일 목록. target 필터 가능."""
    try:
        files = [f for f in os.listdir(str(PENDING)) if f.endswith('.json')]
        if target:
            files = [f for f in files if f.startswith(f"{target}_")]
        return sorted(files)
    except FileNotFoundError:
        return []


def cleanup_done(max_age_hours: int = 24):
    """done/ 내 오래된 파일 삭제."""
    try:
        cutoff = time.time() - (max_age_hours * 3600)
        for f in os.listdir(str(DONE)):
            fpath = DONE / f
            if fpath.stat().st_mtime < cutoff:
                fpath.unlink()
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"Cleanup failed: {e}")
