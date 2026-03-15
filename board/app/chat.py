"""채팅 세션/메시지 관리 API."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from . import models, schemas
from .database import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _utcnow():
    return datetime.now(timezone.utc)


def _session_to_out(session: models.ChatSession, msg_count: int) -> schemas.ChatSessionOut:
    return schemas.ChatSessionOut(
        id=session.id,
        title=session.title,
        cli_session_hash=session.cli_session_hash,
        is_active=session.is_active,
        is_resumable=session.is_resumable,
        skill_command=session.skill_command,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count,
    )


def _get_msg_count(db: Session, session_id: int) -> int:
    return db.query(sa_func.count(models.ChatMessage.id)).filter(
        models.ChatMessage.session_id == session_id
    ).scalar() or 0


# --- 세션 CRUD ---

@router.get("/sessions", response_model=list[schemas.ChatSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(models.ChatSession).order_by(
        models.ChatSession.updated_at.desc()
    ).all()
    return [_session_to_out(s, _get_msg_count(db, s.id)) for s in sessions]


@router.post("/sessions", response_model=schemas.ChatSessionOut)
def create_session(req: schemas.ChatSessionCreate, db: Session = Depends(get_db)):
    # 기존 마지막 세션의 is_resumable을 False로
    db.query(models.ChatSession).filter(
        models.ChatSession.is_resumable == True
    ).update({"is_resumable": False})

    session = models.ChatSession(
        skill_command=req.skill_command,
        is_active=True,
        is_resumable=True,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_to_out(session, 0)


@router.get("/sessions/{session_id}", response_model=schemas.ChatSessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    return _session_to_out(session, _get_msg_count(db, session_id))


@router.put("/sessions/{session_id}", response_model=schemas.ChatSessionOut)
def update_session(session_id: int, req: schemas.ChatSessionUpdate, db: Session = Depends(get_db)):
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    if req.title is not None:
        session.title = req.title
    session.updated_at = _utcnow()
    db.commit()
    db.refresh(session)
    return _session_to_out(session, _get_msg_count(db, session_id))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    db.delete(session)
    db.commit()
    return {"ok": True, "deleted_session_id": session_id}


@router.post("/sessions/{session_id}/archive")
def archive_session(session_id: int, db: Session = Depends(get_db)):
    """세션을 히스토리로 보관 (is_active=False)."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    session.is_active = False
    session.is_resumable = False
    session.updated_at = _utcnow()

    # AI 제목 자동 생성 (첫 사용자 메시지 기반)
    if not session.title:
        first_msg = db.query(models.ChatMessage).filter(
            models.ChatMessage.session_id == session_id,
            models.ChatMessage.role == "user",
        ).order_by(models.ChatMessage.created_at).first()
        if first_msg:
            session.title = first_msg.content[:50].strip()
            if len(first_msg.content) > 50:
                session.title += "..."

    db.commit()
    return {"ok": True}


# --- 메시지 ---

@router.get("/sessions/{session_id}/messages", response_model=list[schemas.ChatMessageOut])
def list_messages(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    messages = db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id
    ).order_by(models.ChatMessage.created_at).all()
    return [
        schemas.ChatMessageOut(
            id=m.id, session_id=m.session_id, role=m.role,
            content=m.content, is_complete=m.is_complete, created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: int,
    req: schemas.ChatMessageCreate,
    db: Session = Depends(get_db),
):
    """메시지 전송. SSE로 응답 스트리밍.

    Note: 실제 CLI 연동은 claude-core SDK 통합 시 구현.
    현재는 메시지 저장 + 더미 SSE 응답.
    """
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    if not session.is_active:
        raise HTTPException(400, "보관된 세션에는 메시지를 보낼 수 없습니다")

    # 사용자 메시지 저장
    user_msg = models.ChatMessage(
        session_id=session_id,
        role="user",
        content=req.content,
        is_complete=True,
    )
    db.add(user_msg)
    session.updated_at = _utcnow()
    db.commit()

    async def stream_response():
        """SSE 스트리밍. CLI 통합 전까지는 placeholder."""
        import json
        # TODO: claude-core ChatBinder + ClaudeDaemon.ask_stream_chat() 연동
        placeholder = f"[Chat SDK 연동 대기 중] 수신: {req.content[:50]}"

        yield f"data: {json.dumps({'type': 'text', 'content': placeholder})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': str(session_id)})}\n\n"

        # assistant 메시지 저장
        assistant_msg = models.ChatMessage(
            session_id=session_id,
            role="assistant",
            content=placeholder,
            is_complete=True,
        )
        db.add(assistant_msg)
        db.commit()

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/compact")
def compact_session(session_id: int, db: Session = Depends(get_db)):
    """대화 요약 트리거. TODO: CLI 연동."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
        models.ChatSession.is_active == True,
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    # TODO: ClaudeDaemon.send_compact() 호출
    return {"ok": True, "message": "compact 요청됨 (CLI 연동 대기 중)"}


@router.post("/sessions/{session_id}/clear")
def clear_session(session_id: int, db: Session = Depends(get_db)):
    """대화 초기화. 메시지 삭제 + CLI clear."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
        models.ChatSession.is_active == True,
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id
    ).delete()
    db.commit()
    # TODO: ClaudeDaemon.send_clear_explicit() 호출
    return {"ok": True, "message": "대화 초기화됨"}
