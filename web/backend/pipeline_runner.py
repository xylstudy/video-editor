import asyncio
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlmodel import Session, select

# 把 viral-structure-engine 加入路径，以便读取 .env 和调用模块
VSE_DIR = Path(__file__).resolve().parent.parent.parent / "viral-structure-engine"
sys.path.insert(0, str(VSE_DIR))

from app_config import STORAGE_ROOT
from database import engine
from db_models import Gene, GeneStatus, KnowledgeOwnership, Material, MaterialType, Project, Task, User
from gene_sync import sync_task_reference_gene
from knowledge_sync import extract_gene_knowledge
from model_runtime import get_user_model_env

logger = logging.getLogger(__name__)

VSE_DATA_DIR = VSE_DIR / "data"
VSE_KNOWLEDGE_DB = VSE_DATA_DIR / "knowledge_db" / "knowledge.json"

# 正在运行的子进程注册表：proc_key -> Popen，用于外部取消（如基因删除时终止提取）
_active_procs: dict[str, "object"] = {}


def _personal_knowledge_entries(
    session: Session,
    user_id: int,
    db_path: Path | None = None,
) -> list[dict]:
    """从共享存储中仅提取当前用户拥有的知识，供任务级生成上下文使用。"""
    source = db_path or VSE_KNOWLEDGE_DB
    if not source.exists():
        return []
    try:
        entries = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("个人知识上下文加载失败: %s", source)
        return []

    owned_ids = set(session.exec(
        select(KnowledgeOwnership.entry_id).where(KnowledgeOwnership.user_id == user_id)
    ).all())
    return [entry for entry in entries if entry.get("id") in owned_ids]


def kill_active_process(proc_key: str) -> bool:
    """终止指定 key 的子进程。有进程被终止返回 True。"""
    proc = _active_procs.get(proc_key)
    if proc and proc.poll() is None:
        proc.kill()
        logger.info(f"已终止子进程: {proc_key} (pid={proc.pid})")
        return True
    return False


def _run_command_sync(
    cmd: list[str],
    cwd: Path,
    emit_callback: Callable,
    step: str,
    start_percent: int,
    end_percent: int,
    proc_key: str | None = None,
    env_overrides: dict[str, str] | None = None,
):
    """同步运行子进程并流式输出日志（在 asyncio.to_thread 中执行）。

    proc_key 不为空时把 Popen 登记到 _active_procs，允许外部用
    kill_active_process(proc_key) 强制终止。
    """
    import subprocess
    emit_callback(step, f"启动: {' '.join(cmd)}", start_percent)
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            **(env_overrides or {}),
        },
    )
    if proc_key:
        _active_procs[proc_key] = process

    import threading
    emit_lock = threading.Lock()

    def emit_line(message: str, percent: int):
        # stdout/stderr are consumed by separate threads. Serializing the
        # callback prevents both readers from writing SQLite at the same time.
        with emit_lock:
            emit_callback(step, message, percent)

    def read_stream(stream, prefix: str):
        for line in stream:
            line = line.strip()
            if line:
                emit_line(f"{prefix}: {line}", start_percent)

    try:
        t_out = threading.Thread(target=read_stream, args=(process.stdout, "OUT"))
        t_err = threading.Thread(target=read_stream, args=(process.stderr, "ERR"))
        t_out.start()
        t_err.start()
        returncode = process.wait()
        t_out.join()
        t_err.join()

        emit_line(f"完成，退出码: {returncode}", end_percent)
        if returncode != 0:
            raise RuntimeError(f"步骤 {step} 执行失败，退出码 {returncode}")
    finally:
        if proc_key:
            _active_procs.pop(proc_key, None)


async def run_command(
    cmd: list[str],
    cwd: Path,
    emit_progress: Callable,
    step: str,
    start_percent: int,
    end_percent: int,
    proc_key: str | None = None,
    env_overrides: dict[str, str] | None = None,
):
    """异步包装：在后台线程中运行子进程，避免 Windows 事件循环限制。"""
    await asyncio.to_thread(
        _run_command_sync,
        cmd,
        cwd,
        emit_progress,
        step,
        start_percent,
        end_percent,
        proc_key,
        env_overrides,
    )


def get_task_storage(user_id: int, project_id: int, task_id: int) -> Path:
    path = STORAGE_ROOT / "users" / str(user_id) / "projects" / str(project_id) / "tasks" / str(task_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_materials(session: Session, project_id: int) -> tuple[Material | None, list[Material]]:
    """返回参考视频和照片列表。"""
    materials = session.exec(select(Material).where(Material.project_id == project_id)).all()
    video = next((m for m in materials if m.type == MaterialType.VIDEO), None)
    photos = [m for m in materials if m.type == MaterialType.IMAGE]
    return video, photos


def material_inventory_matches(photos: list[Material], inventory_path: Path) -> bool:
    """Whether a task-local inventory fully represents the current photos."""
    if not inventory_path.is_file():
        return False
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("items", [])
        expected = {os.path.normcase(str(Path(photo.storage_path).resolve())) for photo in photos}
        actual = {
            os.path.normcase(str(Path(item.get("path", "")).resolve()))
            for item in items
            if item.get("path")
        }
        return len(items) == len(photos) and actual == expected
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def reference_report_matches(video: Material, report_path: Path) -> bool:
    """Whether a completed task-local video report belongs to this video."""
    if not report_path.is_file():
        return False
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        source = payload.get("source_path", "")
        shots = payload.get("raw_shot_analyses", [])
        structure = payload.get("raw_structure_analysis", {})
        return (
            os.path.normcase(str(Path(source).resolve()))
            == os.path.normcase(str(Path(video.storage_path).resolve()))
            and payload.get("source_fingerprint") == file_fingerprint(Path(video.storage_path))
            and bool(shots)
            and isinstance(structure, dict)
            and bool(structure)
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def file_fingerprint(path: Path) -> str:
    """Return a stable content fingerprint for detecting replacement uploads."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_match(first: Path, second: Path) -> bool:
    """Compare two media files by content, not just their filenames."""
    try:
        first = Path(first)
        second = Path(second)
        if not first.is_file() or not second.is_file():
            return False
        if first.stat().st_size != second.stat().st_size:
            return False
        return file_fingerprint(first) == file_fingerprint(second)
    except OSError:
        return False


@dataclass(frozen=True)
class TaskRunContext:
    """Every mutable input and output belonging to one task."""

    root: Path
    inputs_dir: Path
    analysis_dir: Path
    output_dir: Path
    materials_input: Path
    material_inventory: Path
    reference_report: Path
    shot_analyses: Path
    structure_analysis: Path
    video_structure: Path
    personal_knowledge: Path
    scheme: Path
    final_video: Path

    @classmethod
    def create(cls, root: Path) -> "TaskRunContext":
        inputs_dir = root / "inputs"
        analysis_dir = root / "analysis"
        output_dir = root / "output"
        for directory in (inputs_dir, analysis_dir, output_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            inputs_dir=inputs_dir,
            analysis_dir=analysis_dir,
            output_dir=output_dir,
            materials_input=inputs_dir / "materials.json",
            material_inventory=analysis_dir / "material_inventory.json",
            reference_report=analysis_dir / "reference_report.json",
            shot_analyses=analysis_dir / "shot_analyses.json",
            structure_analysis=analysis_dir / "structure_analysis.json",
            video_structure=analysis_dir / "video_structure.json",
            personal_knowledge=inputs_dir / "personal_knowledge.json",
            scheme=output_dir / "scheme.json",
            final_video=output_dir / "final_video.mp4",
        )


def write_materials_json(photos: list[Material], path: Path) -> Path:
    """Write a task-local manifest consumed by the material analyzer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "id": f"mat_{idx:03d}",
            "path": str(Path(photo.storage_path).resolve()),
            "type": "image",
            "description": Path(photo.filename).stem,
        }
        for idx, photo in enumerate(photos)
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record_agent_failure(task_id: int, error: str, target_topic: str = "") -> None:
    """Keep a failed Agent run visible even if it stopped before planning."""
    from config.output_manager import OutputManager
    from evaluation.run_evaluator import evaluate_run

    out = OutputManager(f"web_task_{task_id}")
    existing = out.run_dir / "pipeline_summary.json"
    try:
        if json.loads(existing.read_text(encoding="utf-8")).get("status") == "failed":
            if not (out.run_dir / "evaluation" / "report.json").is_file():
                out.save_json("evaluation", "report.json", evaluate_run(out.run_dir))
            return
    except (OSError, ValueError, AttributeError):
        pass
    if not (out.run_dir / "run_info.json").is_file():
        out.save_run_info(
            target_topic=target_topic,
            sample_videos=[],
            execution_mode="plan_render",
            expected_stages=["analyst", "material", "planner", "renderer", "assembler", "reviewer"],
        )
    out.save_pipeline_summary({
        "status": "failed",
        "target_topic": target_topic,
        "phase": "execution_failed",
        "is_complete": False,
        "errors": [error],
    })
    out.save_json("evaluation", "report.json", evaluate_run(out.run_dir))


def write_lightweight_inventory(photos: list[Material], path: Path) -> Path:
    """Create a deterministic, model-free inventory for editing transfer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "id": f"mat_{idx:03d}",
            "path": str(Path(photo.storage_path).resolve()),
            "type": "image",
            "description": Path(photo.filename).stem,
            "quality": "medium",
            "has_face": False,
        }
        for idx, photo in enumerate(photos)
    ]
    path.write_text(
        json.dumps({"items": items, "materials": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def prepare_analysis_report(source: Path, context: TaskRunContext) -> Path:
    """Copy and split a gene/video report into task-local pipeline inputs."""
    if not source.is_file():
        raise RuntimeError(f"参考视频分析报告不存在: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    context.reference_report.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shot_analyses = data.get("raw_shot_analyses", [])
    for index, shot in enumerate(shot_analyses):
        shot.setdefault("shot_index", index)
    context.shot_analyses.write_text(
        json.dumps(shot_analyses, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    context.structure_analysis.write_text(
        json.dumps(data.get("raw_structure_analysis", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    context.video_structure.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return context.reference_report


def _get_effective_model_env(user_id: int) -> dict[str, str]:
    """合并系统默认模型与当前账号选择，供本次任务子进程使用。"""
    from config import settings as vse_settings

    effective = {
        "VISION_API_KEY": vse_settings.VISION_API_KEY,
        "VISION_BASE_URL": vse_settings.VISION_BASE_URL,
        "VISION_MODEL_ID": vse_settings.VISION_MODEL_ID,
        "VISION_CONFIGURED": "1" if vse_settings.VISION_API_KEY else "",
        "TEXT_API_KEY": vse_settings.TEXT_API_KEY,
        "TEXT_BASE_URL": vse_settings.TEXT_BASE_URL,
        "TEXT_MODEL_ID": vse_settings.TEXT_MODEL_ID,
        "TEXT_CONFIGURED": "1" if vse_settings.TEXT_API_KEY else "",
    }
    effective.update(get_user_model_env(user_id))
    return {key: value for key, value in effective.items() if value is not None}


async def run_pipeline(
    task_id: int,
    project_id: int,
    user_id: int,
    emit_progress: Callable,
) -> str:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        project = session.get(Project, project_id)
        user = session.get(User, user_id)
        if not task or not project or not user:
            raise ValueError("Task/Project/User not found")
        video, photos = find_materials(session, project_id)
        gene_report = None
        active_gene_id = None
        if project.gene_id is not None:
            gene = session.get(Gene, project.gene_id)
            if (
                gene
                and gene.user_id == user_id
                and gene.status == GeneStatus.DONE
                and Path(gene.report_path).is_file()
            ):
                gene_report = Path(gene.report_path)
                active_gene_id = gene.id
        task_type = task.type.value
        workflow_stage = task.workflow_stage
        saved_scheme_path = task.scheme_path
        pipeline_mode = project.pipeline_mode.value
        project_topic = project.topic

    # A project may have an auto-created gene from an earlier run. Reusing it is
    # valid only while the current reference upload is byte-for-byte identical.
    if gene_report and video and workflow_stage != "render":
        matches = await asyncio.to_thread(
            files_match,
            Path(gene.video_path),
            Path(video.storage_path),
        )
        if not matches:
            gene_report = None
            active_gene_id = None
            project.gene_id = None
            with Session(engine) as session:
                current_project = session.get(Project, project_id)
                if current_project and current_project.user_id == user_id:
                    current_project.gene_id = None
                    session.add(current_project)
                    session.commit()
            emit_progress("video_analysis", "检测到新的参考视频，已停止复用旧基因并重新分析", 5)

    context = TaskRunContext.create(get_task_storage(user_id, project_id, task_id))
    python_exe = sys.executable
    model_env = _get_effective_model_env(user_id)

    if task_type == "material_analysis":
        if not photos:
            raise ValueError("项目缺少照片素材")
        _require_model(model_env, "VISION_CONFIGURED", "视觉分析")
        await _run_material_analysis(photos, project_topic, context, python_exe, emit_progress, model_env)
        emit_progress("done", f"素材分析完成: {context.material_inventory.name}", 100)
        return str(context.material_inventory)

    if task_type == "analyze_video":
        if not video:
            raise ValueError("项目缺少参考视频素材")
        if gene_report:
            prepare_analysis_report(gene_report, context)
            emit_progress("video_analysis", "已复用基因库分析报告，无需重复调用模型", 95)
        else:
            _require_model(model_env, "VISION_CONFIGURED", "视觉分析")
            await _run_video_analysis(video, context, python_exe, emit_progress, model_env)
            gene_id = await asyncio.to_thread(
                sync_task_reference_gene,
                task_id=task_id,
                project_id=project_id,
                user_id=user_id,
                video=video,
                report_path=context.reference_report,
                db_engine=engine,
                storage_root=STORAGE_ROOT,
            )
            if gene_id is not None:
                active_gene_id = gene_id
                emit_progress("gene_sync", f"分析结果已同步到基因库（#{gene_id}）", 98)
        await _sync_knowledge_nonfatal(active_gene_id, user_id, emit_progress, 99)
        emit_progress("done", f"视频分析完成: {context.reference_report.name}", 100)
        return str(context.reference_report)

    if task_type == "end_to_end":
        if not video or not photos:
            raise ValueError("项目缺少参考视频或照片素材")

        if workflow_stage == "render":
            scheme_path = Path(saved_scheme_path) if saved_scheme_path else context.scheme
            return await _run_storyboard_render(
                video, scheme_path, context, python_exe, emit_progress,
                evaluation_run_id=f"web_task_{task_id}" if pipeline_mode == "agent_pipeline" else None,
                model_env=model_env,
            )

        if pipeline_mode == "editing_transfer":
            write_lightweight_inventory(photos, context.material_inventory)
            if gene_report:
                prepare_analysis_report(gene_report, context)
                emit_progress("video_analysis", "已复用基因库分析报告", 25)
            await _run_editing_transfer(
                task_id, video, project_topic, context, python_exe, emit_progress
            )
            await _sync_knowledge_nonfatal(active_gene_id, user_id, emit_progress, 70)
            return str(context.scheme)

        if pipeline_mode == "agent_pipeline":
            _require_model(model_env, "VISION_CONFIGURED", "视觉分析")
            _require_model(model_env, "TEXT_CONFIGURED", "方案生成")
            if material_inventory_matches(photos, context.material_inventory):
                emit_progress("material_analysis", "已复用完整的照片素材分析结果", 30)
            else:
                await _run_material_analysis(
                    photos, project_topic, context, python_exe, emit_progress, model_env
                )
            if gene_report:
                prepare_analysis_report(gene_report, context)
                emit_progress("video_analysis", "已复用基因库分析报告", 50)
            elif reference_report_matches(video, context.reference_report):
                prepare_analysis_report(context.reference_report, context)
                emit_progress("video_analysis", "已复用完整的参考视频分析结果", 52)
            else:
                await _run_video_analysis(video, context, python_exe, emit_progress, model_env)
            if not gene_report:
                gene_id = await asyncio.to_thread(
                    sync_task_reference_gene,
                    task_id=task_id,
                    project_id=project_id,
                    user_id=user_id,
                    video=video,
                    report_path=context.reference_report,
                    db_engine=engine,
                    storage_root=STORAGE_ROOT,
                )
                if gene_id is not None:
                    active_gene_id = gene_id
                    emit_progress("gene_sync", f"参考视频已同步到基因库（#{gene_id}）", 55)
            await _run_agent_pipeline(
                task_id, project, context, python_exe, emit_progress, model_env
            )
            await _sync_knowledge_nonfatal(active_gene_id, user_id, emit_progress, 70)
            return str(context.scheme)
        raise ValueError(f"不支持的 pipeline 模式: {pipeline_mode}")

    raise ValueError(f"不支持的流水线任务类型: {task_type}")


async def _sync_knowledge_nonfatal(
    gene_id: int | None,
    user_id: int,
    emit_progress: Callable,
    percent: int,
) -> None:
    """Update personal knowledge without discarding an otherwise valid task."""
    if gene_id is None:
        return
    try:
        result = await extract_gene_knowledge(gene_id, user_id)
        if result.get("skipped"):
            emit_progress("knowledge_sync", "该基因知识已入库，无需重复提炼", percent)
        else:
            emit_progress(
                "knowledge_sync",
                f"已自动提炼 {result.get('added', 0)} 条知识并同步到知识库",
                percent,
            )
    except Exception as exc:
        logger.warning("基因知识自动同步失败: gene=%s error=%s", gene_id, exc)
        emit_progress(
            "knowledge_sync",
            f"知识库自动更新未完成，可稍后在基因详情重试：{exc}",
            percent,
        )


def _require_model(model_env: dict[str, str], configured_key: str, purpose: str) -> None:
    if model_env.get(configured_key):
        return
    raise RuntimeError(
        f"未配置{purpose}模型。请在“模型与 API”页面添加可用模型，并设为对应默认模型。"
    )


async def _run_material_analysis(
    photos: list[Material],
    topic: str,
    context: TaskRunContext,
    python_exe: str,
    emit_progress: Callable,
    model_env: dict[str, str],
):
    """执行素材分析步骤。"""
    emit_progress("material_analysis", "准备照片素材清单", 5)
    write_materials_json(photos, context.materials_input)

    emit_progress("material_analysis", "开始分析照片素材", 10)
    await run_command(
        [
            python_exe,
            "run_material_analysis.py",
            "--materials-json",
            str(context.materials_input),
            "--topic",
            topic or "短视频",
            "--run-id",
            f"task_{context.root.name}_materials",
            "--output",
            str(context.material_inventory),
        ],
        cwd=VSE_DIR,
        emit_progress=emit_progress,
        step="material_analysis",
        start_percent=10,
        end_percent=30,
        env_overrides=model_env,
    )


async def _run_video_analysis(
    video: Material,
    context: TaskRunContext,
    python_exe: str,
    emit_progress: Callable,
    model_env: dict[str, str],
) -> Path:
    """执行参考视频分析步骤，返回分析结果 JSON 路径。

    使用 analyze_video.py：其返回的 raw_shot_analyses 含 shot_index，
    正好是 run_editing_transfer.py 所要求的格式。
    """
    emit_progress("video_analysis", "开始分析参考视频结构", 32)
    analysis_output_path = context.reference_report
    await run_command(
        [
            python_exe, "analyze_video.py",
            "--video", str(Path(video.storage_path).resolve()),
            "--output", str(analysis_output_path),
        ],
        cwd=VSE_DIR,
        emit_progress=emit_progress,
        step="video_analysis",
        start_percent=32,
        end_percent=50,
        env_overrides=model_env,
    )

    prepare_analysis_report(analysis_output_path, context)
    report = json.loads(context.reference_report.read_text(encoding="utf-8"))
    report["source_fingerprint"] = await asyncio.to_thread(
        file_fingerprint,
        Path(video.storage_path),
    )
    context.reference_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Re-split after adding the fingerprint so all task-local consumers see it.
    prepare_analysis_report(context.reference_report, context)
    emit_progress("video_analysis", f"分析结果已写入 {context.analysis_dir}", 52)
    return context.reference_report


async def _run_editing_transfer(
    task_id: int,
    video: Material,
    topic: str,
    context: TaskRunContext,
    python_exe: str,
    emit_progress: Callable,
) -> str:
    """编辑迁移路线：无需 LLM，节拍驱动。"""
    emit_progress("editing_transfer", "开始生成编辑迁移分镜", 55)
    run_id = f"web_task_{task_id}"
    cmd = [
        python_exe,
        "run_editing_transfer.py",
        "--viral-video",
        str(Path(video.storage_path).resolve()),
        "--materials",
        str(context.material_inventory),
        "--topic",
        topic or "我的短视频",
        "--run-id",
        run_id,
        "--output",
        str(context.final_video),
        "--scheme-output",
        str(context.scheme),
        "--prepare-only",
    ]
    if context.shot_analyses.is_file() and context.structure_analysis.is_file():
        cmd.extend([
            "--shot-analyses",
            str(context.shot_analyses),
            "--structure-analysis",
            str(context.structure_analysis),
        ])
    await run_command(
        cmd,
        cwd=VSE_DIR,
        emit_progress=emit_progress,
        step="editing_transfer",
        start_percent=55,
        end_percent=68,
        env_overrides={
            "VISION_API_KEY": "",
            "VISION_CONFIGURED": "",
            "TEXT_API_KEY": "",
            "TEXT_CONFIGURED": "",
        },
    )
    if not context.scheme.is_file():
        raise RuntimeError(f"分镜草案不存在: {context.scheme}")
    emit_progress("storyboard", f"分镜草案已生成: {context.scheme.name}", 70)
    return str(context.scheme)


async def _run_agent_pipeline(
    task_id: int,
    project: Project,
    context: TaskRunContext,
    python_exe: str,
    emit_progress: Callable,
    model_env: dict[str, str],
) -> str:
    """多智能体路线：基于已分析的结构生成待确认方案。"""
    run_id = f"web_task_{task_id}"
    try:
        if not context.video_structure.is_file():
            raise RuntimeError(f"视频结构分析结果未生成: {context.video_structure}")

        with Session(engine) as session:
            personal_knowledge = _personal_knowledge_entries(session, project.user_id)
        context.personal_knowledge.write_text(
            json.dumps(personal_knowledge, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        emit_progress("pipeline", "开始端到端多智能体流水线", 60)
        await run_command(
            [
                python_exe, "run_pipeline_e2e.py",
                "--struct", str(context.video_structure),
                "--struct-analysis", str(context.structure_analysis),
                "--inventory", str(context.material_inventory),
                "--topic", project.topic or "旅行Vlog",
                "--run-id", run_id,
                "--knowledge-context", str(context.personal_knowledge),
                "--output", str(context.final_video),
                "--scheme-output", str(context.scheme),
                "--prepare-only",
            ],
            cwd=VSE_DIR,
            emit_progress=emit_progress,
            step="pipeline",
            start_percent=60,
            end_percent=68,
            env_overrides=model_env,
        )
        if not context.scheme.is_file():
            raise RuntimeError(f"分镜草案不存在: {context.scheme}")
    except Exception as exc:
        try:
            record_agent_failure(task_id, str(exc), project.topic or "旅行Vlog")
        except Exception:
            logger.exception("草案生成失败后的 Agent 评测报告生成失败")
        raise
    emit_progress("storyboard", f"分镜草案已生成: {context.scheme.name}", 70)
    return str(context.scheme)


async def _run_storyboard_render(
    video: Material,
    scheme_path: Path,
    context: TaskRunContext,
    python_exe: str,
    emit_progress: Callable,
    evaluation_run_id: str | None = None,
    model_env: dict[str, str] | None = None,
) -> str:
    """Render a confirmed storyboard and finalize Agent evaluation when enabled."""
    emit_progress("render", "开始渲染已确认的分镜方案", 75)
    command = [
        python_exe, "run_storyboard_render.py",
        "--scheme", str(scheme_path),
        "--materials", str(context.material_inventory),
        "--reference-video", str(Path(video.storage_path).resolve()),
        "--output", str(context.final_video),
    ]
    if evaluation_run_id:
        command.extend([
            "--run-id", evaluation_run_id,
            "--reference-structure", str(context.video_structure),
        ])
    try:
        if not scheme_path.is_file():
            raise RuntimeError(f"分镜草案不存在: {scheme_path}")
        if not context.material_inventory.is_file():
            raise RuntimeError(f"素材库存不存在: {context.material_inventory}")
        await run_command(
            command,
            cwd=VSE_DIR,
            emit_progress=emit_progress,
            step="render",
            start_percent=75,
            end_percent=98,
            env_overrides=model_env if evaluation_run_id else {
                "VISION_API_KEY": "",
                "VISION_CONFIGURED": "",
                "TEXT_API_KEY": "",
                "TEXT_CONFIGURED": "",
            },
        )
    except Exception as exc:
        if evaluation_run_id:
            report_path = VSE_DIR / "data" / "runs" / evaluation_run_id / "evaluation" / "report.json"
            try:
                report_phase = json.loads(report_path.read_text(encoding="utf-8")).get("phase")
            except (OSError, ValueError, AttributeError):
                report_phase = None
            if report_phase != "failed":
                try:
                    from evaluation.web_run import finalize_web_run
                    await finalize_web_run(
                        evaluation_run_id, scheme_path, context.material_inventory, None,
                        reference_structure_path=context.video_structure,
                        render_error=str(exc),
                        model_config=model_env,
                    )
                except Exception:
                    logger.exception("渲染失败后的 Agent 评测报告生成失败")
        raise
    if not context.final_video.is_file():
        if evaluation_run_id:
            from evaluation.web_run import finalize_web_run
            await finalize_web_run(
                evaluation_run_id, scheme_path, context.material_inventory, None,
                render_error=f"结果文件不存在: {context.final_video}",
                model_config=model_env,
            )
        raise RuntimeError(f"结果文件不存在: {context.final_video}")
    if evaluation_run_id:
        report_path = VSE_DIR / "data" / "runs" / evaluation_run_id / "evaluation" / "report.json"
        try:
            report_phase = json.loads(report_path.read_text(encoding="utf-8")).get("phase")
        except (OSError, ValueError, AttributeError):
            report_phase = None
        if report_phase != "completed":
            from evaluation.web_run import finalize_web_run
            await finalize_web_run(
                evaluation_run_id, scheme_path, context.material_inventory, context.final_video,
                reference_structure_path=context.video_structure,
                model_config=model_env,
            )
    emit_progress("done", f"渲染完成: {context.final_video.name}", 100)
    return str(context.final_video)
