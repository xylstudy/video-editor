import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from db_models import Material, MaterialType, Project, Task, TaskStatus, TaskType, User

router = APIRouter(prefix="/api/works", tags=["works"])


def _task_reference_material(task: Task, materials: list[Material]) -> Material | None:
    """Resolve the reference used by this task, falling back for legacy runs."""
    videos = [material for material in materials if material.type == MaterialType.VIDEO]
    if not videos:
        return None

    if task.result_path:
        report_path = Path(task.result_path).parent.parent / "analysis" / "reference_report.json"
        try:
            source_path = json.loads(report_path.read_text(encoding="utf-8")).get("source_path")
            if source_path:
                expected = os.path.normcase(str(Path(source_path).resolve()))
                exact = next(
                    (
                        material
                        for material in videos
                        if os.path.normcase(str(Path(material.storage_path).resolve())) == expected
                    ),
                    None,
                )
                if exact:
                    return exact
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    return next(
        (material for material in videos if material.get_metadata().get("role") == "reference"),
        videos[0],
    )


@router.get("")
def list_works(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """聚合当前用户所有端到端成功任务的成片。"""
    projects = session.exec(
        select(Project).where(Project.user_id == current_user.id)
    ).all()
    project_map = {p.id: p for p in projects}
    if not project_map:
        return []

    tasks = session.exec(
        select(Task)
        .where(Task.project_id.in_(project_map.keys()))
        .where(Task.status == TaskStatus.SUCCESS)
        .where(Task.type == TaskType.END_TO_END)
        .order_by(Task.id.desc())
    ).all()

    materials = session.exec(
        select(Material).where(Material.project_id.in_(project_map.keys()))
    ).all()
    materials_by_project: dict[int, list[Material]] = {}
    for material in materials:
        materials_by_project.setdefault(material.project_id, []).append(material)

    works = []
    for t in tasks:
        if not t.result_path:
            continue
        path = Path(t.result_path)
        if not path.exists() or path.suffix.lower() != ".mp4":
            continue
        project = project_map.get(t.project_id)
        reference = _task_reference_material(t, materials_by_project.get(t.project_id, []))
        works.append({
            "task_id": t.id,
            "project_id": t.project_id,
            "project_name": project.name if project else "",
            "pipeline_mode": project.pipeline_mode.value if project else "",
            "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
            "created_at": t.updated_at,
            "reference_material_id": reference.id if reference else None,
            "reference_filename": reference.filename if reference else "",
        })
    return works
