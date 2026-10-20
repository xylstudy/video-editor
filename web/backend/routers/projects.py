import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from db_models import Gene, GeneStatus, Material, MaterialType, Project, ProjectCreate, ProjectRead, User
from storage import get_project_dir

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    projects = session.exec(
        select(Project).where(Project.user_id == current_user.id)
    ).all()
    return projects


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    gene = None
    if project_in.gene_id is not None:
        gene = session.get(Gene, project_in.gene_id)
        if not gene or gene.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="所选基因不存在")
        if gene.status != GeneStatus.DONE:
            raise HTTPException(status_code=400, detail="所选基因尚未完成提取")
        if not Path(gene.video_path).is_file():
            raise HTTPException(status_code=404, detail="基因视频文件不存在")

    project = Project(
        name=project_in.name,
        topic=project_in.topic,
        pipeline_mode=project_in.pipeline_mode,
        user_id=current_user.id,
        gene_id=gene.id if gene else None,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    # 从基因库选择参考视频：复制基因视频为项目素材
    if gene:
        src = Path(gene.video_path)
        material_dir = get_project_dir(current_user.id, project.id) / "video"
        material_dir.mkdir(parents=True, exist_ok=True)
        dest = material_dir / src.name
        shutil.copy2(src, dest)
        reference = Material(
            project_id=project.id,
            type=MaterialType.VIDEO,
            filename=gene.source_filename or src.name,
            storage_path=str(dest),
        )
        reference.set_metadata({"role": "reference", "source_gene_id": gene.id})
        session.add(reference)
        session.commit()

    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    project_in: ProjectCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    project.name = project_in.name
    project.topic = project_in.topic
    project.pipeline_mode = project_in.pipeline_mode
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    # 级联删除：任务（含结果文件）→ 素材（含文件）→ 项目
    from db_models import Task
    from storage import delete_file

    tasks = session.exec(select(Task).where(Task.project_id == project_id)).all()
    for t in tasks:
        if t.result_path:
            delete_file(t.result_path)
        session.delete(t)

    materials = session.exec(select(Material).where(Material.project_id == project_id)).all()
    for m in materials:
        delete_file(m.storage_path)
        session.delete(m)

    session.delete(project)
    session.commit()

    # 清理项目目录
    shutil.rmtree(get_project_dir(current_user.id, project_id), ignore_errors=True)
    return None
