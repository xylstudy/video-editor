"""视频基因提取后台执行器。

与任务队列解耦：基因提取是独立动作，直接在后台 asyncio 任务中执行，
状态写回 Gene 记录（pending → analyzing → done / failed），前端轮询状态即可。

提取过程中，子进程 analyze_video.py 通过 stdout 的 `__GENE_EVENT__{json}`
结构化事件行上报进度；本模块解析这些事件并持久化到 Gene.progress /
Gene.progress_logs，让前端可以实时展示分析阶段、逐镜头中间结果和原始日志。

任务登记在 _extraction_tasks 中，删除基因时可通过 cancel_gene_extraction
杀子进程 + 取消 asyncio 任务，避免孤儿进程继续烧 API 额度。
"""
import asyncio
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from database import engine
from db_models import Gene, GeneStatus
from pipeline_runner import (
    _get_effective_model_env,
    kill_active_process,
    run_command,
)
from vse import VSE_DIR

logger = logging.getLogger(__name__)

# gene_id -> 正在运行的提取任务
_extraction_tasks: dict[int, asyncio.Task] = {}

EVENT_PREFIX = "__GENE_EVENT__"
# 进度日志上限，防止长视频产生超大 JSON 列
MAX_PROGRESS_LOGS = 300


def start_gene_extraction(gene_id: int, user_id: int):
    """启动基因提取并登记任务，供取消时使用。"""
    task = asyncio.create_task(run_gene_extraction(gene_id, user_id))
    _extraction_tasks[gene_id] = task
    task.add_done_callback(lambda _: _extraction_tasks.pop(gene_id, None))


def cancel_gene_extraction(gene_id: int):
    """取消正在进行的基因提取：先杀子进程，再取消 asyncio 任务。"""
    kill_active_process(f"gene_{gene_id}")
    task = _extraction_tasks.pop(gene_id, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"已取消基因提取任务: gene_id={gene_id}")


def _parse_event_line(message: str) -> dict | None:
    """从 'OUT: __GENE_EVENT__{...}' 行解析事件；非事件行返回 None。"""
    text = message
    for prefix in ("OUT: ", "ERR: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if not text.startswith(EVENT_PREFIX):
        return None
    try:
        return json.loads(text[len(EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None


def _event_percent(event: dict) -> int | None:
    """按事件类型推导整体进度百分比。"""
    t = event.get("type")
    if t == "video_info":
        return 5
    if t == "scenes":
        return 10
    if t == "audio":
        return 15
    if t in ("shot_start", "shot_result", "shot_failed"):
        total = max(event.get("total") or 1, 1)
        idx = event.get("index") or 0
        done_shots = idx if t == "shot_start" else idx + 1
        return 15 + int(75 * done_shots / total)  # 逐镜头段占 15 → 90
    if t == "structure_start":
        return 92
    if t == "structure_done":
        return 96
    if t == "done":
        return 100
    return None


def _event_message(event: dict) -> str:
    """为事件生成一条人类可读的日志消息。"""
    t = event.get("type")
    if t == "video_info":
        return (f"视频信息: {event.get('width')}x{event.get('height')} · "
                f"{event.get('fps')}fps · {event.get('duration')}s")
    if t == "scenes":
        return f"镜头切分完成: 检测到 {event.get('count')} 个镜头"
    if t == "audio":
        if event.get("status") == "ok":
            return f"音频处理完成（转写 {event.get('transcript_chars', 0)} 字）"
        return event.get("message") or "音频处理跳过"
    if t == "shot_start":
        return f"分析镜头 {(event.get('index') or 0) + 1}/{event.get('total')} ({event.get('start')}s-{event.get('end')}s)..."
    if t == "shot_result":
        return f"镜头 {(event.get('index') or 0) + 1}: {event.get('function') or '?'} | 情绪: {event.get('emotion') or '?'}"
    if t == "shot_failed":
        return f"镜头 {(event.get('index') or 0) + 1} 分析失败: {event.get('message')}"
    if t == "structure_start":
        return "全局结构分析中..."
    if t == "structure_done":
        return f"结构分析完成: {event.get('category') or '未分类'}"
    if t == "done":
        return "分析完成"
    if t == "error":
        return f"分析出错: {event.get('message')}"
    return str(event)


def _make_progress_handler(gene_id: int):
    """构造基因提取的进度回调：解析事件行并持久化到 Gene 记录。

    会被子进程 stdout/stderr 读取线程并发调用，用锁保护读改写序列。
    普通输出行保留为 log 条目（含 ERR 前缀的重试/警告，便于排查限流）。
    """
    lock = threading.Lock()

    def handle(step: str, message: str, percent: int):
        event = _parse_event_line(message)
        if event:
            entry = {
                "time": datetime.utcnow().isoformat(),
                "type": event.get("type", "event"),
                "message": _event_message(event),
                "percent": _event_percent(event),
                "data": event,
            }
        else:
            entry = {
                "time": datetime.utcnow().isoformat(),
                "type": "log",
                "message": message,
                "percent": None,
            }

        with lock, Session(engine) as session:
            gene = session.get(Gene, gene_id)
            if not gene:
                return  # 基因已被删除，子进程随即会被终止，直接丢弃
            logs = list(gene.progress_logs or [])
            logs.append(entry)
            gene.progress_logs = logs[-MAX_PROGRESS_LOGS:]
            if entry["percent"] is not None:
                gene.progress = min(100, max(gene.progress, entry["percent"]))
            session.add(gene)
            session.commit()

    return handle


async def run_gene_extraction(gene_id: int, user_id: int):
    with Session(engine) as session:
        gene = session.get(Gene, gene_id)
        if not gene:
            logger.warning(f"Gene {gene_id} 不存在，取消提取")
            return
        gene.status = GeneStatus.ANALYZING
        gene.error_message = None
        gene.progress = 0
        gene.progress_logs = []
        session.add(gene)
        session.commit()
        video_path = gene.video_path
        report_path = Path(gene.video_path).parent / "report.json"

    try:
        # 用户 API Key 覆盖 + 预检
        model_env = _get_effective_model_env(user_id)
        if not model_env.get("VISION_CONFIGURED"):
            raise RuntimeError(
                "未配置视觉分析模型。请在「模型与 API」页面添加支持图片输入的模型，"
                "并将它设为视觉分析默认模型。"
            )

        await run_command(
            [
                sys.executable,
                "analyze_video.py",
                "--video",
                str(Path(video_path).resolve()),
                "--output",
                str(report_path),
            ],
            cwd=VSE_DIR,
            emit_progress=_make_progress_handler(gene_id),
            step="gene_extraction",
            start_percent=0,
            end_percent=100,
            proc_key=f"gene_{gene_id}",
            env_overrides=model_env,
        )

        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        vlog_meta = report.get("vlog_meta") or {}

        with Session(engine) as session:
            gene = session.get(Gene, gene_id)
            gene.status = GeneStatus.DONE
            gene.report_path = str(report_path)
            gene.duration = report.get("duration") or 0.0
            gene.shot_count = report.get("shot_count") or 0
            gene.structure_type = vlog_meta.get("structure_type") or ""
            gene.narrative_type = vlog_meta.get("narrative_type") or ""
            gene.overall_emotion = vlog_meta.get("overall_emotion") or ""
            gene.hook_method = vlog_meta.get("hook_method") or ""
            gene.progress = 100
            session.add(gene)
            from learning_service import ensure_gene_learning
            ensure_gene_learning(session, gene, user_id)
            session.commit()
            shot_count = gene.shot_count
        logger.info(f"Gene {gene_id} 提取完成: {shot_count} 个镜头")

    except Exception as e:
        logger.exception(f"Gene {gene_id} 提取失败: {e}")
        with Session(engine) as session:
            gene = session.get(Gene, gene_id)
            if gene:
                gene.status = GeneStatus.FAILED
                gene.error_message = str(e)
                session.add(gene)
                session.commit()
