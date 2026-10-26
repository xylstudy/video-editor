"""Durable, retryable asset generation after tasks and gene analyses finish."""
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app_config import STORAGE_ROOT
from database import engine
from db_models import Gene, GeneStatus, LearningJob, Project, Task, TaskStatus, TaskType

logger = logging.getLogger(__name__)
STEPS = ("gene", "knowledge", "examples", "insights")
LABELS = {"gene": "视频基因", "knowledge": "个人知识", "examples": "实拍剪辑示例", "insights": "统计洞察"}
_worker = None


def ensure_task_learning(session: Session, task: Task, user_id: int) -> LearningJob | None:
    """Called in the same transaction that commits task SUCCESS."""
    if task.status != TaskStatus.SUCCESS or task.type not in (TaskType.END_TO_END, TaskType.ANALYZE_VIDEO):
        return None
    key = f"task:{task.id}"
    job = session.exec(select(LearningJob).where(LearningJob.source_key == key)).first()
    if not job:
        from pipeline_runner import find_materials
        video, materials = find_materials(session, task.project_id)
        def snapshot(material):
            path = Path(material.storage_path)
            stat = path.stat() if path.is_file() else None
            return {"id": material.id, "path": str(path), "filename": material.filename,
                    "size": stat.st_size if stat else None, "mtime_ns": stat.st_mtime_ns if stat else None}
        job = LearningJob(source_key=key, user_id=user_id, task_id=task.id, project_id=task.project_id,
                          inputs={"reference": snapshot(video) if video else None, "materials": [snapshot(material) for material in materials]},
                          steps={name: {"status": "pending", "label": LABELS[name]} for name in STEPS})
        session.add(job)
        session.flush()
    return job


def ensure_gene_learning(session: Session, gene: Gene, user_id: int):
    if gene.user_id != user_id or gene.status != GeneStatus.DONE:
        raise ValueError("基因尚未完成或不属于当前用户")
    key = f"gene:{gene.id}"
    job = session.exec(select(LearningJob).where(LearningJob.source_key == key)).first()
    if not job:
        job = LearningJob(source_key=key, user_id=user_id, gene_id=gene.id,
                          steps={name: {"status": "pending", "label": LABELS[name]} for name in STEPS})
    elif job.status in ("completed", "failed"):
        job.status, job.attempts, job.next_retry_at = "pending", 0, 0
        job.steps, job.error = {}, None
    session.add(job)
    return job


def enqueue_gene_learning(gene_id: int, user_id: int):
    with Session(engine) as session:
        gene = session.get(Gene, gene_id)
        if not gene or gene.user_id != user_id or gene.status != GeneStatus.DONE:
            raise ValueError("基因尚未完成或不属于当前用户")
        job = ensure_gene_learning(session, gene, user_id)
        session.commit()
        return job.id


def job_payload(job: LearningJob) -> dict:
    return {"id": job.id, "task_id": job.task_id, "gene_id": job.gene_id, "status": job.status,
            "attempts": job.attempts, "steps": job.steps, "result": job.result, "error": job.error,
            "updated_at": job.updated_at.isoformat()}


async def _update(job_id: int, *, step=None, state=None, **fields):
    with Session(engine) as session:
        job = session.get(LearningJob, job_id)
        if not job:
            raise RuntimeError("资产生成任务已删除")
        if step:
            job.steps = {**job.steps, step: {"label": LABELS[step], "status": state}}
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        payload, task_id = job_payload(job), job.task_id
    if task_id:
        from websocket_manager import ws_manager
        try:
            await ws_manager.broadcast(str(task_id), {"type": "learning", "data": payload})
        except Exception:
            logger.warning("asset status broadcast failed: task=%s", task_id)


async def _resolve_gene(job: LearningJob) -> int:
    if not job.task_id:
        with Session(engine) as session:
            gene = session.get(Gene, job.gene_id)
            if not gene or gene.user_id != job.user_id or gene.status != GeneStatus.DONE:
                raise RuntimeError("来源基因已删除或尚未完成")
            return gene.id
    from gene_sync import sync_task_reference_gene, _read_complete_report, _files_match
    from pipeline_runner import (find_materials, TaskRunContext, _run_video_analysis,
                                 _get_effective_model_env, _require_model)
    import sys

    with Session(engine) as session:
        task, project = session.get(Task, job.task_id), session.get(Project, job.project_id)
        if not task or task.status != TaskStatus.SUCCESS or not project or project.user_id != job.user_id:
            raise RuntimeError("来源任务或项目已删除，无法继续生成资产")
        video, _ = find_materials(session, project.id)
        original = (job.inputs or {}).get("reference")
        if original:
            from db_models import Material
            video = session.get(Material, original["id"])
            if not video or video.project_id != project.id or video.storage_path != original["path"]:
                raise RuntimeError("本次任务的参考素材已删除或改变")
            source = Path(video.storage_path)
            if not source.is_file() or source.stat().st_size != original["size"] or source.stat().st_mtime_ns != original["mtime_ns"]:
                raise RuntimeError("本次任务的参考视频文件已改变，不能将新素材归入旧任务")
        if not video:
            raise RuntimeError("来源任务没有参考视频")
        linked = session.get(Gene, project.gene_id) if project.gene_id else None
        if linked and linked.user_id == job.user_id and linked.status == GeneStatus.DONE and _read_complete_report(Path(linked.report_path or "")) and _files_match(Path(linked.video_path), Path(video.storage_path)):
            return linked.id
    context = TaskRunContext.create(STORAGE_ROOT / "users" / str(job.user_id) / "projects" / str(job.project_id) / "tasks" / str(job.task_id))
    if not _read_complete_report(context.reference_report):
        model_env = _get_effective_model_env(job.user_id)
        _require_model(model_env, "VISION_CONFIGURED", "参考视频分析")
        await _run_video_analysis(video, context, sys.executable, lambda *args: None, model_env)
    gene_id = await asyncio.to_thread(sync_task_reference_gene, task_id=job.task_id, project_id=job.project_id,
                                     user_id=job.user_id, video=video, report_path=context.reference_report,
                                     db_engine=engine, storage_root=STORAGE_ROOT)
    if not gene_id:
        raise RuntimeError("参考视频分析报告不完整")
    return gene_id


async def process_learning_job(job_id: int):
    with Session(engine) as session:
        job = session.get(LearningJob, job_id)
        if not job or job.status == "completed":
            return
        task_id, project_id, user_id = job.task_id, job.project_id, job.user_id
    if task_id and project_id:
        from task_usage import task_usage_scope
        with task_usage_scope(task_id, project_id, user_id, "asset_learning"):
            return await _process_learning_job(job_id)
    return await _process_learning_job(job_id)


async def _process_learning_job(job_id: int):
    """A failed example never changes a successfully rendered task to FAILED."""
    with Session(engine) as session:
        job = session.get(LearningJob, job_id)
        if not job or job.status == "completed":
            return
        attempts, result = job.attempts + 1, dict(job.result or {})
    await _update(job_id, status="running", attempts=attempts, error=None)
    current = "gene"
    try:
        await _update(job_id, step="gene", state="running")
        gene_id = await _resolve_gene(job)
        await _update(job_id, step="gene", state="done", gene_id=gene_id)
        current = "knowledge"
        await _update(job_id, step=current, state="running")
        from knowledge_sync import extract_gene_knowledge
        knowledge = await extract_gene_knowledge(gene_id, job.user_id, render_demos=False)
        result["knowledge_count"] = int(knowledge.get("added", 0)) + int(knowledge.get("existing", 0))
        await _update(job_id, step=current, state="done", result=result)
        current = "examples"
        await _update(job_id, step=current, state="running")
        from learning_materials import prepare_example_materials
        await asyncio.to_thread(prepare_example_materials, gene_id, job.user_id, job.project_id, (job.inputs or {}).get("materials"))
        demos = await extract_gene_knowledge(gene_id, job.user_id)
        result["source_examples"] = demos.get("demos_available", 0)
        result["editing_examples"] = demos.get("teaching_demos_rendered", 0) + demos.get("teaching_demos_existing", 0)
        result['pending_examples'] = demos.get('teaching_demo_pending', [])
        if demos.get("demo_failures") or demos.get("teaching_demo_failures") or result["editing_examples"] + len(result['pending_examples']) < result["knowledge_count"]:
            raise RuntimeError("部分视频示例尚未生成，将自动重试")
        await _update(job_id, step=current, state="partial" if result['pending_examples'] else "done", result=result)
        current = "insights"
        await _update(job_id, step=current, state="running")
        from insight_cache import refresh_user_insights
        result["insights"] = await asyncio.to_thread(refresh_user_insights, job.user_id)
        await _update(job_id, step=current, state="done", status="completed", result=result, error=None)
    except asyncio.CancelledError:
        await _update(job_id, status="pending")
        raise
    except Exception as exc:
        logger.exception("asset generation failed: job=%s stage=%s", job_id, current)
        await _update(job_id, step=current, state="failed", status="retrying" if attempts < 3 else "failed",
                      error=f"{LABELS[current]}：{str(exc)[:500]}", result=result,
                      next_retry_at=time.time() + 5 * 2 ** (attempts - 1))


async def _worker_loop():
    while True:
        try:
            with Session(engine) as session:
                candidates = session.exec(select(LearningJob).where(LearningJob.status.in_(["pending", "retrying"])).order_by(LearningJob.id)).all()
                job_id = next((job.id for job in candidates if job.next_retry_at <= time.time()), None)
            if job_id:
                await process_learning_job(job_id)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("asset generation worker error")
            await asyncio.sleep(2)


def start_learning_worker():
    global _worker
    if _worker and not _worker.done():
        return
    with Session(engine) as session:
        for job in session.exec(select(LearningJob).where(LearningJob.status == "running")).all():
            job.status = "pending"
            session.add(job)
        session.commit()
    _worker = asyncio.create_task(_worker_loop())


async def stop_learning_worker():
    global _worker
    if _worker:
        _worker.cancel()
        await asyncio.gather(_worker, return_exceptions=True)
        _worker = None
