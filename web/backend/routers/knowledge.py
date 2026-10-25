import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

import vse  # noqa: F401  注入 viral-structure-engine 路径
from app_config import STORAGE_ROOT
from auth import get_current_user
from database import get_session
from db_models import KnowledgeOwnership, User
from media import get_current_user_media, range_file_response

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

DEMO_DIR = STORAGE_ROOT / "knowledge_demos"
KnowledgeScope = Literal["mine", "system", "all"]


def _demo_path(entry_id: str, variant: str = "example") -> Path:
    # entry_id 由系统生成（形如 k_0），仍做一层防路径穿越校验
    safe = Path(entry_id).name
    suffix = ".teaching" if variant == "teaching" else ""
    return DEMO_DIR / f"{safe}{suffix}.mp4"


def _available_demos(entry_id: str, source: str) -> list[dict]:
    demos = []
    for variant in ("teaching", "example"):
        path = _demo_path(entry_id, variant)
        reference_recut = False
        if variant == "teaching" and source == "user":
            try:
                metadata = json.loads((DEMO_DIR / f"{Path(entry_id).name}.teaching.json").read_text(encoding="utf-8"))
                if metadata.get("mode") not in {"personal-effect-v3", "personal-effect-v4"} or metadata.get('status') == 'pending':
                    continue
                reference_recut = bool((metadata.get("recipe") or {}).get("reference_recut"))
                if reference_recut:
                    continue
            except (OSError, ValueError):
                continue
        if path.is_file() and path.stat().st_size > 0:
            demo = {
                "variant": variant,
                "label": "效果示例" if variant == "teaching" else "教学演示" if source == "system" else "原片示例",
            }
            if variant == 'teaching' and source == 'user':
                demo['description'] = '使用独立素材重新制作的技法示例。' + ('主体部分采用定格抠像合成。' if any(clip.get('atomic', {}).get('cutout') for clip in (metadata.get('recipe') or {}).get('edited', [])) else '')
                demo['version'] = str(metadata.get('fingerprint') or path.stat().st_mtime_ns)[:24]
            demos.append(demo)
    return demos


def _pending_demo_reason(entry_id: str) -> str | None:
    try:
        metadata = json.loads((DEMO_DIR / f"{Path(entry_id).name}.teaching.json").read_text(encoding='utf-8'))
        if metadata.get('status') == 'pending':
            return metadata.get('reason') or '效果示例待实现'
        if (metadata.get('recipe') or {}).get('reference_recut'):
            return '旧示例来自原片，已停止作为效果示例展示，等待独立素材重建'
    except (OSError, ValueError):
        pass
    return None


def _load_store():
    """每次请求重新加载，保证提炼入库的新知识立即可见。"""
    from knowledge.store import KnowledgeStore

    return KnowledgeStore()


def _ownership_map(session: Session) -> dict[str, int]:
    """知识条目归属：entry_id -> user_id。无记录的条目 = 公共种子，全员可见。"""
    return {o.entry_id: o.user_id for o in session.exec(select(KnowledgeOwnership)).all()}


def _is_visible(entry_id: str, ownership: dict[str, int], user_id: int) -> bool:
    """公共（无归属记录）或本人提炼的知识可见；他人私有知识表现为不存在。"""
    owner = ownership.get(entry_id)
    return owner is None or owner == user_id


def _entry_source(entry_id: str, ownership: dict[str, int], user_id: int) -> str | None:
    """返回当前用户视角下的知识来源；他人的个人知识返回 None。"""
    owner = ownership.get(entry_id)
    if owner is None:
        return "system"
    if owner == user_id:
        return "user"
    return None


def _matches_scope(source: str | None, scope: KnowledgeScope) -> bool:
    if source is None:
        return False
    return scope == "all" or source == ("user" if scope == "mine" else "system")


@router.get("")
def list_knowledge(
    type: str | None = None,
    q: str | None = None,
    scope: KnowledgeScope = "mine",
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    store = _load_store()
    ownership = _ownership_map(session)
    entries = []
    for entry in store.get_all_entries():
        source = _entry_source(entry.id, ownership, current_user.id)
        if not _matches_scope(source, scope):
            continue
        entries.append({
            **entry.to_dict(),
            "source": source,
            "mine": source == "user",
        })

    if type:
        entries = [e for e in entries if e["type"] == type]
    if q:
        keyword = q.strip().lower()
        entries = [
            e
            for e in entries
            if keyword in e["title"].lower()
            or keyword in e["content"].lower()
            or any(keyword in str(t).lower() for t in e["tags"])
        ]
    # Newly extracted knowledge is more useful at the top of the personal view.
    entries.sort(
        key=lambda item: (item.get("derivation") or {}).get("extracted_at", ""),
        reverse=True,
    )
    # 标记每个条目是否有演示视频
    for e in entries:
        e["demos"] = _available_demos(e["id"], e["source"])
        e["has_demo"] = bool(e["demos"])
        e["has_teaching_demo"] = any(demo["variant"] == "teaching" for demo in e["demos"])
        e['demo_pending_reason'] = _pending_demo_reason(e['id']) if e['source'] == 'user' and not e['has_teaching_demo'] else None
    return entries


@router.get("/stats")
def knowledge_stats(
    scope: KnowledgeScope = "mine",
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    store = _load_store()
    ownership = _ownership_map(session)
    counts: dict[str, int] = {}
    total = 0
    for e in store.get_all_entries():
        source = _entry_source(e.id, ownership, current_user.id)
        if not _matches_scope(source, scope):
            continue
        total += 1
        key = e.type.value
        counts[key] = counts.get(key, 0) + 1
    return {"total": total, "by_type": counts}


@router.get("/{entry_id}/demo")
def get_knowledge_demo(
    entry_id: str,
    request: Request,
    variant: Literal["example", "teaching"] = "example",
    current_user: User = Depends(get_current_user_media),
    session: Session = Depends(get_session),
):
    """知识条目的技法演示视频（支持 Range 拖动播放）。"""
    store = _load_store()
    ownership = _ownership_map(session)
    if not store.get_entry(entry_id) or not _is_visible(
        entry_id, ownership, current_user.id
    ):
        raise HTTPException(status_code=404, detail="知识条目不存在")
    if variant == "teaching" and not any(
        demo["variant"] == "teaching"
        for demo in _available_demos(entry_id, _entry_source(entry_id, ownership, current_user.id))
    ):
        raise HTTPException(status_code=404, detail="该知识的效果示例尚未生成")
    path = _demo_path(entry_id, variant)
    if not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="该知识暂无演示视频")
    return range_file_response(request, path, media_type="video/mp4")


@router.delete("/{entry_id}", status_code=204)
def delete_knowledge(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    store = _load_store()
    if not store.get_entry(entry_id):
        raise HTTPException(status_code=404, detail="知识条目不存在")
    owner = _ownership_map(session).get(entry_id)
    if owner is not None and owner != current_user.id:
        # 他人私有知识：不泄露存在性
        raise HTTPException(status_code=404, detail="知识条目不存在")
    if owner is None:
        raise HTTPException(status_code=403, detail="公共知识不可删除")
    store.remove_entry(entry_id)
    row = session.get(KnowledgeOwnership, entry_id)
    if row:
        session.delete(row)
        session.commit()
    # 同步清理演示视频
    _demo_path(entry_id).unlink(missing_ok=True)
    _demo_path(entry_id, "teaching").unlink(missing_ok=True)
    (DEMO_DIR / f"{Path(entry_id).name}.teaching.json").unlink(missing_ok=True)
    (DEMO_DIR / f"{Path(entry_id).name}.mp4.source.json").unlink(missing_ok=True)
    return None
