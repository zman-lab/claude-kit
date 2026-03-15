"""채팅 세션/메시지 관리 API."""
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from . import models, schemas
from .database import get_db
from .chat_daemon import is_sdk_available, get_chat_binder, get_chat_daemon

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


def _save_assistant_msg(db: Session, session_id: int, content: str, is_complete: bool = True):
    """assistant 메시지 DB 저장 헬퍼."""
    msg = models.ChatMessage(
        session_id=session_id,
        role="assistant",
        content=content,
        is_complete=is_complete,
    )
    db.add(msg)
    db.commit()


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
async def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    # SDK unbind (프로세스 종료)
    if is_sdk_available():
        binder = get_chat_binder()
        await binder.unbind(str(session_id))

    db.delete(session)
    db.commit()
    return {"ok": True, "deleted_session_id": session_id}


@router.post("/sessions/{session_id}/archive")
async def archive_session(session_id: int, db: Session = Depends(get_db)):
    """세션을 히스토리로 보관 (is_active=False)."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    session.is_active = False
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

    # SDK unbind → session_hash 보관
    if is_sdk_available():
        binder = get_chat_binder()
        session_hash = await binder.unbind(str(session_id))
        if session_hash:
            session.cli_session_hash = session_hash

    db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/resume", response_model=schemas.ChatSessionOut)
async def resume_session(session_id: int, db: Session = Depends(get_db)):
    """마지막 세션 이어하기. is_resumable=True인 세션만 가능."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    if not session.is_resumable:
        raise HTTPException(403, "이 세션은 이어하기가 불가능합니다")
    if not session.cli_session_hash:
        raise HTTPException(400, "세션 해시가 없어 이어가기 불가능합니다")

    # 세션을 다시 active로
    session.is_active = True
    session.updated_at = _utcnow()
    db.commit()

    msg_count = db.query(sa_func.count(models.ChatMessage.id)).filter(
        models.ChatMessage.session_id == session_id
    ).scalar()

    return schemas.ChatSessionOut(
        id=session.id, title=session.title,
        cli_session_hash=session.cli_session_hash,
        is_active=session.is_active, is_resumable=session.is_resumable,
        skill_command=session.skill_command,
        created_at=session.created_at, updated_at=session.updated_at,
        message_count=msg_count or 0,
    )


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
    """메시지 전송. SSE로 응답 스트리밍."""
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

    # session 상태를 로컬 변수로 캡처 (클로저에서 사용)
    cli_session_hash = session.cli_session_hash
    is_resumable = session.is_resumable

    async def stream_response():
        if not is_sdk_available():
            # SDK 미설치 시 placeholder
            placeholder = f"[SDK 미설치] 수신: {req.content[:50]}"
            yield f"data: {json.dumps({'type': 'text', 'content': placeholder})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': str(session_id)})}\n\n"
            _save_assistant_msg(db, session_id, placeholder)
            return

        binder = get_chat_binder()
        daemon = get_chat_daemon()

        # 프로세스 확보 (바인딩 안 되어 있으면 바인딩)
        process = await binder.get(str(session_id))
        if process is None:
            try:
                if cli_session_hash and is_resumable:
                    process = await binder.resume(str(session_id), cli_session_hash)
                else:
                    process = await binder.bind(str(session_id))
                    # 초기 명령 실행 (설정된 경우)
                    initial_cmd = os.getenv("CHAT_INITIAL_COMMAND")
                    if initial_cmd:
                        await daemon.run_initial_command(process, initial_cmd)
            except Exception as e:
                error_msg = f"CLI 연결 실패: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                _save_assistant_msg(db, session_id, f"⚠️ {error_msg}", is_complete=True)
                return

        # 스트리밍 응답
        full_text = ""
        try:
            async for event_json in daemon.ask_stream_chat(process, req.content):
                event = json.loads(event_json)
                event_type = event.get("type", "")

                if event_type == "text":
                    text = event.get("content", "")
                    full_text += text
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

                elif event_type == "tool_status":
                    yield f"data: {json.dumps(event)}\n\n"

                elif event_type == "done":
                    final_text = event.get("full_text", full_text)
                    new_sid = event.get("session_id")
                    if new_sid:
                        # CLI session hash 업데이트
                        db.query(models.ChatSession).filter(
                            models.ChatSession.id == session_id
                        ).update({"cli_session_hash": new_sid})
                        db.commit()
                    yield f"data: {json.dumps({'type': 'done', 'session_id': str(session_id)})}\n\n"
                    _save_assistant_msg(db, session_id, final_text or full_text)
                    return

                elif event_type == "error":
                    error_msg = event.get("message", "알 수 없는 오류")
                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                    _save_assistant_msg(db, session_id, f"⚠️ {error_msg}")
                    return

                elif event_type == "keepalive":
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

        except Exception as e:
            error_msg = f"스트리밍 오류: {str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
            if full_text:
                _save_assistant_msg(db, session_id, full_text, is_complete=False)

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/compact")
async def compact_session(session_id: int, db: Session = Depends(get_db)):
    """대화 요약 트리거."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
        models.ChatSession.is_active == True,
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    if is_sdk_available():
        binder = get_chat_binder()
        daemon = get_chat_daemon()
        process = await binder.get(str(session_id))
        if process:
            success = await daemon.send_compact(process)
            return {"ok": success, "message": "compact 완료" if success else "compact 실패"}

    return {"ok": True, "message": "compact 요청됨 (SDK 미설치)"}


@router.post("/sessions/{session_id}/clear")
async def clear_session(session_id: int, db: Session = Depends(get_db)):
    """대화 초기화. 메시지 삭제 + CLI clear."""
    session = db.query(models.ChatSession).filter(
        models.ChatSession.id == session_id,
        models.ChatSession.is_active == True,
    ).first()
    if not session:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    # 메시지 삭제
    db.query(models.ChatMessage).filter(
        models.ChatMessage.session_id == session_id
    ).delete()
    db.commit()

    if is_sdk_available():
        daemon = get_chat_daemon()
        binder = get_chat_binder()
        process = await binder.get(str(session_id))
        if process:
            await daemon.send_clear_explicit(process)

    return {"ok": True, "message": "대화 초기화됨"}
