import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_config import ALLOWED_ORIGINS
from database import create_db_and_tables
from gene_sync import reconcile_completed_task_genes
from learning_service import start_learning_worker, stop_learning_worker
from queue_manager import queue
from routers import auth, api_keys, chat, genes, insights, knowledge, materials, models, projects, stats, tasks, works

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    synced = await asyncio.to_thread(reconcile_completed_task_genes)
    if synced:
        logging.getLogger(__name__).info("已回填 %s 个历史任务到基因库", synced)
    queue.start()
    start_learning_worker()
    try:
        yield
    finally:
        await stop_learning_worker()


app = FastAPI(
    title="Video Claw Web API",
    description="爆款 Vlog 结构迁移引擎 Web 化 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(chat.router)
app.include_router(models.router)
app.include_router(projects.router)
app.include_router(materials.router)
app.include_router(tasks.router)
app.include_router(genes.router)
app.include_router(knowledge.router)
app.include_router(works.router)
app.include_router(stats.router)
app.include_router(insights.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
