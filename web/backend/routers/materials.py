import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from db_models import Material, MaterialType, Project, User, MaterialRead
from media import get_current_user_media, range_file_response
from storage import delete_file, save_upload

router = APIRouter(prefix="/api/materials", tags=["materials"])


def _guess_material_type(filename: str, form_type: str | None) -> MaterialType:
    if form_type:
        return MaterialType(form_type)
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext in {"mp4", "mov", "webm", "avi"}:
        return MaterialType.VIDEO
    if ext in {"jpg", "jpeg", "png", "webp", "bmp", "gif"}:
        return MaterialType.IMAGE
    if ext in {"mp3", "wav", "aac", "m4a", "ogg"}:
        return MaterialType.AUDIO
    return MaterialType.IMAGE


@router.post("/upload", response_model=MaterialRead, status_code=status.HTTP_201_CREATED)
def upload_material(
    project_id: int = Form(...),
    type: str | None = Form(default=None),
    role: str | None = Form(default=None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    material_type = _guess_material_type(file.filename or "", type)
    saved_path = save_upload(current_user.id, project_id, file, material_type.value)

    material = Material(
        project_id=project_id,
        type=material_type,
        filename=file.filename or "unnamed",
        storage_path=str(saved_path),
    )
    if role in {"reference", "target"}:
        material.set_metadata({"role": role})
    session.add(material)
    session.commit()
    session.refresh(material)
    return MaterialRead(
        id=material.id,
        project_id=material.project_id,
        type=material.type,
        filename=material.filename,
        meta=material.get_metadata(),
        created_at=material.created_at,
    )


@router.get("/project/{project_id}", response_model=list[MaterialRead])
def list_project_materials(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    materials = session.exec(
        select(Material).where(Material.project_id == project_id)
    ).all()
    return [
        MaterialRead(
            id=m.id,
            project_id=m.project_id,
            type=m.type,
            filename=m.filename,
            meta=m.get_metadata(),
            created_at=m.created_at,
        )
        for m in materials
    ]


@router.get("/{material_id}/media")
def get_material_media(
    material_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_media),
    session: Session = Depends(get_session),
):
    """Stream an owned project material with HTTP Range support for video seeking."""
    material = session.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    project = session.get(Project, material.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Material not found")
    path = Path(material.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Material file not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return range_file_response(request, path, media_type=media_type)


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    material = session.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    project = session.get(Project, material.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    delete_file(material.storage_path)
    session.delete(material)
    session.commit()
    return None
