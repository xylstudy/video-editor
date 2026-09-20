import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from database import engine
from db_models import Project, Task, TaskStatus
from pipeline_runner import record_agent_failure, run_pipeline
from websocket_manager import ws_manager

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    task_id: int
    project_id: int
    user_id: int


@dataclass
class ProgressMessage:
    task_id: int
    step: str
    message: str
    percent: int


class TaskQueue:
    def __init__(self):
        self.queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self.progress_queue: asyncio.Queue[ProgressMessage] = asyncio.Queue()
        self.current_task_id: Optional[int] = None
        self.worker_task: Optional[asyncio.Task] = None
        self.broadcaster_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self):
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Task queue worker started")
        if self.broadcaster_task is None or self.broadcaster_task.done():
            self.broadcaster_task = asyncio.create_task(self._broadcaster_loop())
            logger.info("Progress broadcaster started")

    async def _broadcaster_loop(self):
        while True:
            msg = await self.progress_queue.get()
            try:
                await ws_manager.broadcast(
                    str(msg.task_id),
                    {
                        "type": "progress",
                        "data": {"step": msg.step, "message": msg.message, "percent": msg.percent},
                    },
                )
            except Exception as e:
                logger.warning(f"Broadcast failed: {e}")
            finally:
                self.progress_queue.task_done()

    async def _worker_loop(self):
        while True:
            item = await self.queue.get()
            self.current_task_id = item.task_id
            try:
                await self._execute_item(item)
            except Exception as e:
                logger.exception(f"Task {item.task_id} execution failed: {e}")
                with Session(engine) as session:
                    task = session.get(Task, item.task_id)
                    if task:
                        task.status = TaskStatus.FAILED
                        task.error_message = str(e)
                        task.updated_at = datetime.utcnow()
                        session.add(task)
                        session.commit()
                        await ws_manager.broadcast(
                            str(task.id),
                            {"type": "status", "data": {"status": "failed", "error": str(e)}},
                        )
            finally:
                self.current_task_id = None
                self.queue.task_done()

    async def _execute_item(self, item: QueueItem):
        with Session(engine) as session:
            task = session.get(Task, item.task_id)
            if not task:
                logger.warning(f"Task {item.task_id} not found")
                return

            task.status = TaskStatus.RUNNING
            task.error_message = None
            if task.workflow_stage == "render":
                task.progress = max(task.progress, 70)
                task.logs = list(task.logs or [])
            else:
                task.progress = 0
                task.logs = []
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()

            await ws_manager.broadcast(
                str(task.id),
                {"type": "status", "data": {"status": "running", "progress": task.progress}},
            )

        def emit_progress(step: str, message: str, percent: int):
            with Session(engine) as session:
                task = session.get(Task, item.task_id)
                if task:
                    task.progress = min(100, max(0, percent))
                    new_logs = list(task.logs or [])
                    new_logs.append({"time": datetime.utcnow().isoformat(), "step": step, "message": message})
                    task.logs = new_logs
                    task.updated_at = datetime.utcnow()
                    session.add(task)
                    session.commit()
            try:
                self.progress_queue.put_nowait(
                    ProgressMessage(task_id=item.task_id, step=step, message=message, percent=percent)
                )
            except Exception:
                pass

        try:
            result_path = await run_pipeline(
                task_id=item.task_id,
                project_id=item.project_id,
                user_id=item.user_id,
                emit_progress=emit_progress,
            )
            with Session(engine) as session:
                task = session.get(Task, item.task_id)
                if task.type.value == "end_to_end" and task.workflow_stage == "prepare":
                    task.status = TaskStatus.AWAITING_CONFIRMATION
                    task.progress = 70
                    task.scheme_path = result_path
                    status_payload = {
                        "status": TaskStatus.AWAITING_CONFIRMATION.value,
                        "progress": 70,
                        "scheme_path": result_path,
                    }
                else:
                    task.status = TaskStatus.SUCCESS
                    task.progress = 100
                    task.result_path = result_path
                    status_payload = {
                        "status": TaskStatus.SUCCESS.value,
                        "progress": 100,
                        "result_path": result_path,
                    }
                task.error_message = None
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
            await ws_manager.broadcast(
                str(item.task_id),
                {"type": "status", "data": status_payload},
            )
        except Exception as e:
            logger.exception(f"Pipeline failed for task {item.task_id}: {e}")
            with Session(engine) as session:
                task = session.get(Task, item.task_id)
                project = session.get(Project, item.project_id)
                is_agent_task = bool(
                    task and task.type.value == "end_to_end"
                    and project and project.pipeline_mode.value == "agent_pipeline"
                )
                target_topic = project.topic if project else ""
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()
            if is_agent_task:
                try:
                    record_agent_failure(item.task_id, str(e), target_topic or "")
                except Exception:
                    logger.exception("Failed to persist Agent evaluation for task %s", item.task_id)
            await ws_manager.broadcast(
                str(item.task_id),
                {"type": "status", "data": {"status": "failed", "error": str(e)}},
            )

    def enqueue(self, task_id: int, project_id: int, user_id: int):
        self.queue.put_nowait(QueueItem(task_id=task_id, project_id=project_id, user_id=user_id))
        logger.info(f"Enqueued task {task_id}")


queue = TaskQueue()
