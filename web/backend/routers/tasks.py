import json
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from auth import get_current_user
from app_config import STORAGE_ROOT
from database import engine, get_session
from db_models import MaterialType, Project, Task, TaskCreate, TaskRead, TaskStatus, TaskType, User
from media import get_current_user_media, range_file_response
from queue_manager import queue
from pipeline_runner import VSE_DIR
from storage import delete_file
from websocket_manager import ws_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

ALLOWED_TRANSITIONS = {
    "cut", "fade", "dissolve", "zoom_in", "zoom_out", "flash_white",
    "flash_black", "slide", "slide_left", "slide_right", "slide_up",
    "slide_down", "wipe_left", "wipe_right", "wipe_up", "wipe_down",
    "blur_in", "rotate_in", "whip", "mask", "circle_reveal", "zoom_flash",
    "glitch", "spin", "zoom_heavy", "light_leak", "freeze_frame", "flip_3d",
    "radial_wipe", "zoom_through", "liquid_warp", "chromatic_aberration", "none",
}


def _owned_task(task_id: int, user_id: int, session: Session) -> tuple[Task, Project]:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = session.get(Project, task.project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task, project


def _task_root(user_id: int, project_id: int, task_id: int) -> Path:
    return STORAGE_ROOT / "users" / str(user_id) / "projects" / str(project_id) / "tasks" / str(task_id)


def _storyboard_paths(task: Task, user_id: int) -> tuple[Path, Path]:
    root = _task_root(user_id, task.project_id, task.id)
    return root / "output" / "scheme.json", root / "analysis" / "material_inventory.json"


def _load_json_file(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{label}不存在") from None
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail=f"{label}损坏") from None


def _normalized_storyboard(scheme: dict) -> list[dict]:
    frames = scheme.get("storyboard", [])
    return [
        {
            **frame,
            "draft_id": frame.get("draft_id") or f"frame-{index}",
            "index": index,
            "material_id": frame.get("material_id") or frame.get("source_material_id", ""),
            "transition": frame.get("transition") or frame.get("transition_in", "cut"),
        }
        for index, frame in enumerate(frames)
    ]


def _storyboard_payload(task: Task, user_id: int) -> dict:
    scheme_path, inventory_path = _storyboard_paths(task, user_id)
    scheme = _load_json_file(scheme_path, "分镜草案")
    inventory = _load_json_file(inventory_path, "素材库存")
    items = inventory if isinstance(inventory, list) else inventory.get("items", inventory.get("materials", []))
    return {
        "task_id": task.id,
        "status": task.status.value,
        "revision": task.draft_revision,
        "title": scheme.get("title", ""),
        "target_topic": scheme.get("target_topic", ""),
        "target_duration": scheme.get("target_duration", 0),
        "storyboard": _normalized_storyboard(scheme),
        "materials": [
            {
                "id": item.get("id", ""),
                "filename": Path(item.get("path", "")).name,
                "description": item.get("description", ""),
                "preview_url": f"/tasks/{task.id}/storyboard/materials/{item.get('id', '')}",
            }
            for item in items
            if item.get("id")
        ],
        "updated_at": task.updated_at.isoformat(),
    }


@router.get("/project/{project_id}", response_model=list[TaskRead])
def list_project_tasks(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = session.exec(select(Task).where(Task.project_id == project_id)).all()
    return tasks


@router.get("", response_model=list[TaskRead])
def list_user_tasks(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # 获取当前用户所有项目的任务
    projects = session.exec(select(Project.id).where(Project.user_id == current_user.id)).all()
    project_ids = [p for p in projects]
    if not project_ids:
        return []
    tasks = session.exec(select(Task).where(Task.project_id.in_(project_ids))).all()
    return tasks


@router.post("/project/{project_id}", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    project_id: int,
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    supported_types = {
        TaskType.END_TO_END,
        TaskType.ANALYZE_VIDEO,
        TaskType.MATERIAL_ANALYSIS,
    }
    if task_in.type not in supported_types:
        raise HTTPException(status_code=400, detail="该任务类型暂未开放")

    from db_models import Material
    materials = session.exec(select(Material).where(Material.project_id == project_id)).all()
    has_video = any(m.type == MaterialType.VIDEO for m in materials)
    has_photo = any(m.type == MaterialType.IMAGE for m in materials)
    if task_in.type == TaskType.ANALYZE_VIDEO and not has_video:
        raise HTTPException(status_code=400, detail="分析参考视频需要至少一个视频素材")
    if task_in.type == TaskType.MATERIAL_ANALYSIS and not has_photo:
        raise HTTPException(status_code=400, detail="分析素材需要至少一张图片")
    if task_in.type == TaskType.END_TO_END and (not has_video or not has_photo):
        raise HTTPException(status_code=400, detail="完整生成需要至少一个参考视频和一张图片")

    task = Task(
        project_id=project_id,
        type=task_in.type,
        status=TaskStatus.PENDING,
        progress=0,
        logs=[],
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    # 入队
    queue.enqueue(task.id, project_id, current_user.id)

    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = session.get(Project, task.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/evaluation")
def get_task_evaluation(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task, project = _owned_task(task_id, current_user.id, session)
    if task.type != TaskType.END_TO_END or project.pipeline_mode.value != "agent_pipeline":
        raise HTTPException(status_code=404, detail="该任务没有 Agent 评测报告")
    report_path = VSE_DIR / "data" / "runs" / f"web_task_{task_id}" / "evaluation" / "report.json"
    return _load_json_file(report_path, "Agent 评测报告")


@router.get("/{task_id}/storyboard")
def get_storyboard(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task, _ = _owned_task(task_id, current_user.id, session)
    if task.type != TaskType.END_TO_END or not task.scheme_path:
        raise HTTPException(status_code=404, detail="该任务还没有分镜草案")
    return _storyboard_payload(task, current_user.id)


@router.put("/{task_id}/storyboard")
def update_storyboard(
    task_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task, _ = _owned_task(task_id, current_user.id, session)
    if task.status != TaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="只有等待确认的分镜可以编辑")

    scheme_path, inventory_path = _storyboard_paths(task, current_user.id)
    scheme = _load_json_file(scheme_path, "分镜草案")
    inventory = _load_json_file(inventory_path, "素材库存")
    items = inventory if isinstance(inventory, list) else inventory.get("items", inventory.get("materials", []))
    valid_material_ids = {item.get("id") for item in items if item.get("id")}
    existing = {
        frame.get("draft_id") or f"frame-{index}": frame
        for index, frame in enumerate(scheme.get("storyboard", []))
    }
    requested = payload.get("storyboard")
    if payload.get("revision") != task.draft_revision:
        raise HTTPException(status_code=409, detail="分镜已在其他页面更新，请刷新后重试")
    if not isinstance(requested, list) or not 1 <= len(requested) <= 200:
        raise HTTPException(status_code=422, detail="分镜数量必须在 1 到 200 之间")

    seen_ids = set()
    updated_frames = []
    for index, incoming in enumerate(requested):
        if not isinstance(incoming, dict):
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜格式错误")
        draft_id = str(incoming.get("draft_id", ""))
        if not draft_id or draft_id not in existing or draft_id in seen_ids:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜标识无效")
        seen_ids.add(draft_id)

        try:
            duration = round(float(incoming.get("duration", 0)), 3)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜时长无效") from None
        if not 0.2 <= duration <= 30:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜时长需在 0.2 到 30 秒之间")

        material_id = str(incoming.get("material_id", ""))
        if material_id and material_id not in valid_material_ids:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜素材不存在")
        transition = str(incoming.get("transition", "cut"))
        if transition not in ALLOWED_TRANSITIONS:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜转场不受支持")
        subtitle = str(incoming.get("subtitle_text", "")).strip()
        if len(subtitle) > 200:
            raise HTTPException(status_code=422, detail=f"第 {index + 1} 个分镜字幕不能超过 200 字")

        frame = dict(existing[draft_id])
        frame.update({
            "draft_id": draft_id,
            "index": index,
            "material_id": material_id,
            "duration": duration,
            "subtitle_text": subtitle,
            "transition": transition,
            "transition_in": transition,
        })
        updated_frames.append(frame)

    total_duration = round(sum(frame["duration"] for frame in updated_frames), 3)
    if total_duration > 600:
        raise HTTPException(status_code=422, detail="视频总时长不能超过 600 秒")
    title = str(payload.get("title", scheme.get("title", ""))).strip()
    if not title or len(title) > 120:
        raise HTTPException(status_code=422, detail="标题长度必须在 1 到 120 字之间")

    scheme["title"] = title
    scheme["target_duration"] = total_duration
    scheme["storyboard"] = updated_frames
    temp_path = scheme_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(scheme, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(scheme_path)

    task.draft_revision += 1
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return _storyboard_payload(task, current_user.id)


@router.post("/{task_id}/storyboard/confirm", response_model=TaskRead)
def confirm_storyboard(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task, project = _owned_task(task_id, current_user.id, session)
    if task.status != TaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="该分镜当前不能确认渲染")
    scheme_path, inventory_path = _storyboard_paths(task, current_user.id)
    _load_json_file(scheme_path, "分镜草案")
    _load_json_file(inventory_path, "素材库存")

    task.workflow_stage = "render"
    task.status = TaskStatus.PENDING
    task.progress = 70
    task.error_message = None
    logs = list(task.logs or [])
    logs.append({
        "time": datetime.utcnow().isoformat(),
        "step": "storyboard",
        "message": f"用户已确认第 {task.draft_revision} 版分镜，进入渲染队列",
    })
    task.logs = logs
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    queue.enqueue(task.id, project.id, current_user.id)
    return task


@router.get("/{task_id}/storyboard/materials/{material_id}")
def get_storyboard_material(
    task_id: int,
    material_id: str,
    current_user: User = Depends(get_current_user_media),
    session: Session = Depends(get_session),
):
    task, project = _owned_task(task_id, current_user.id, session)
    _, inventory_path = _storyboard_paths(task, current_user.id)
    inventory = _load_json_file(inventory_path, "素材库存")
    items = inventory if isinstance(inventory, list) else inventory.get("items", inventory.get("materials", []))
    item = next((entry for entry in items if entry.get("id") == material_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="素材不存在")

    from db_models import Material
    project_materials = session.exec(select(Material).where(Material.project_id == project.id)).all()
    allowed_paths = {Path(material.storage_path).resolve() for material in project_materials}
    source = Path(item.get("path", "")).resolve()
    if source not in allowed_paths or not source.is_file():
        raise HTTPException(status_code=404, detail="素材不存在")
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    return FileResponse(source, media_type=media_type)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = session.get(Project, task.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.result_path:
        delete_file(task.result_path)
    task_root = _task_root(current_user.id, task.project_id, task.id).resolve()
    session.delete(task)
    session.commit()
    if task_root.is_dir():
        shutil.rmtree(task_root, ignore_errors=True)
    return None


@router.get("/{task_id}/download")
def download_task_result(
    task_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_media),
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task or task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=404, detail="Result not ready")
    project = session.get(Project, task.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.result_path or not Path(task.result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    return range_file_response(
        request,
        task.result_path,
        media_type="video/mp4",
        filename=f"task_{task_id}_result.mp4",
    )


@router.websocket("/{task_id}/ws")
async def task_websocket(websocket: WebSocket, task_id: str):
    await ws_manager.connect(task_id, websocket)
    try:
        while True:
            # 保持连接，前端可发送 ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except Exception:
        pass
    finally:
        ws_manager.disconnect(task_id, websocket)
