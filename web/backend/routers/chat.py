import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlmodel import Session, select

from app_config import STORAGE_ROOT
from auth import get_current_user
from chat_service import (
    _authorise_context,
    _memory_for_client,
    _message_dict,
    _normalise_context,
    _parse_json,
    _session_or_404,
    handle_message,
)
from database import get_session
from db_models import (
    ChatAttachment,
    ChatContextUpdate,
    ChatMessage,
    ChatMessageCreate,
    ChatSession,
    ChatSessionCreate,
    User,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_UPLOAD_EXTENSIONS = {
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".avi": "video",
    ".mkv": "video",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".bmp": "image",
    ".gif": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".aac": "audio",
    ".m4a": "audio",
    ".ogg": "audio",
}


def _safe_filename(filename: str | None) -> str:
    safe = Path(filename or "upload").name
    for char in '\\/:*?"<>|':
        safe = safe.replace(char, "_")
    return safe[:180] or "upload"


def _upload_media_type(filename: str, content_type: str | None, kind: str | None) -> str | None:
    extension_type = _UPLOAD_EXTENSIONS.get(Path(filename).suffix.lower())
    if extension_type:
        return extension_type
    if kind in {"video", "image", "audio"}:
        return kind
    if content_type and content_type.startswith("video/"):
        return "video"
    if content_type and content_type.startswith("image/"):
        return "image"
    if content_type and content_type.startswith("audio/"):
        return "audio"
    return None


def _session_read(chat: ChatSession) -> dict:
    raw_context = _parse_json(chat.context_json, {})
    context = {
        key: raw_context[key]
        for key in ("route", "project_id", "task_id", "gene_id")
        if isinstance(raw_context, dict) and key in raw_context
    }
    return {
        "id": chat.id,
        "title": chat.title,
        "context": context,
        "memory": _memory_for_client(chat),
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
    }


@router.get("/sessions")
def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    chats = session.exec(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(30)
    ).all()
    return [_session_read(chat) for chat in chats]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_chat_session(
    payload: ChatSessionCreate | None = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    payload = payload or ChatSessionCreate()
    title = (payload.title or "新对话").strip()[:80] or "新对话"
    context = _authorise_context(
        session,
        current_user,
        _normalise_context("{}", payload.context),
    )
    chat = ChatSession(
        user_id=current_user.id,
        title=title,
        context_json=json.dumps(context, ensure_ascii=False),
    )
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return _session_read(chat)


@router.patch("/sessions/{session_id}/context")
def update_chat_context(
    session_id: int,
    payload: ChatContextUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Explicitly set a conversation's active project/task/gene context."""
    try:
        chat = _session_or_404(session, session_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context = _authorise_context(
        session,
        current_user,
        _normalise_context(chat.context_json, payload.context),
    )
    chat.context_json = json.dumps(context, ensure_ascii=False)
    memory = _memory_for_client(chat)
    memory["workspace"] = {
        key: context[key]
        for key in ("project_id", "task_id", "gene_id")
        if context.get(key)
    }
    chat.memory_json = json.dumps(memory, ensure_ascii=False)
    chat.updated_at = datetime.utcnow()
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return _session_read(chat)


@router.delete("/sessions/{session_id}/context")
def clear_chat_context(
    session_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Clear the workspace selection without deleting conversation history."""
    try:
        chat = _session_or_404(session, session_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    context = _normalise_context(chat.context_json, {})
    for key in ("project_id", "task_id", "gene_id", "attachment_ids"):
        context.pop(key, None)
    context["route"] = "/assistant"
    chat.context_json = json.dumps(context, ensure_ascii=False)
    memory = _memory_for_client(chat)
    memory["workspace"] = {}
    chat.memory_json = json.dumps(memory, ensure_ascii=False)
    chat.updated_at = datetime.utcnow()
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return _session_read(chat)


@router.post("/sessions/{session_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_chat_attachment(
    session_id: int,
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        chat = _session_or_404(session, session_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    filename = _safe_filename(file.filename)
    media_type = _upload_media_type(filename, file.content_type, kind)
    if not media_type:
        raise HTTPException(status_code=415, detail="仅支持视频、图片或音频文件")

    upload_dir = STORAGE_ROOT / "users" / str(current_user.id) / "chat" / str(chat.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / filename
    counter = 1
    while destination.exists():
        destination = upload_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
        counter += 1

    total = 0
    try:
        with destination.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="单个附件不能超过 500 MB")
                buffer.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"附件保存失败：{exc}") from exc
    finally:
        await file.close()

    attachment = ChatAttachment(
        session_id=chat.id,
        user_id=current_user.id,
        filename=filename,
        media_type=media_type,
        storage_path=str(destination),
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return {
        "id": attachment.id,
        "session_id": attachment.session_id,
        "filename": attachment.filename,
        "media_type": attachment.media_type,
        "status": attachment.status,
        "created_at": attachment.created_at,
    }


@router.get("/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: int,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        chat = _session_or_404(session, session_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    statement = select(ChatMessage).where(ChatMessage.session_id == chat.id)
    if before_id:
        statement = statement.where(ChatMessage.id < before_id)
    rows = session.exec(
        statement.order_by(ChatMessage.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    messages = list(reversed(rows[:limit]))
    return {
        "items": [_message_dict(message) for message in messages],
        "has_more": has_more,
        "next_before_id": messages[0].id if has_more and messages else None,
    }


@router.post("/sessions/{session_id}/messages")
async def send_chat_message(
    session_id: int,
    payload: ChatMessageCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        chat = _session_or_404(session, session_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = await handle_message(
            session,
            current_user,
            chat,
            payload.content,
            payload.context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if chat.title == "新对话":
        chat.title = payload.content.strip()[:36] or chat.title
        chat.updated_at = datetime.utcnow()
        session.add(chat)
        session.commit()
    return result
