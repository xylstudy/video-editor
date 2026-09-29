import json
import re

from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import text

from app_config import DB_PATH
from vse import VSE_KNOWLEDGE_DB

sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, echo=False, connect_args={"check_same_thread": False})


def _migrate_gene_progress_columns():
    """为已存在的 gene 表补充进度字段（create_all 不会修改已有表），并回填存量 NULL。"""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(gene)"))}
        if "progress" not in cols:
            conn.execute(text("ALTER TABLE gene ADD COLUMN progress INTEGER DEFAULT 0"))
        if "progress_logs" not in cols:
            conn.execute(text("ALTER TABLE gene ADD COLUMN progress_logs JSON"))
        # 存量行新列是 NULL，会导致 GeneRead 序列化失败，统一回填默认值
        conn.execute(text("UPDATE gene SET progress = 0 WHERE progress IS NULL"))
        conn.execute(text("UPDATE gene SET progress_logs = '[]' WHERE progress_logs IS NULL"))
        conn.commit()


def _migrate_knowledge_ownership():
    """回填存量个人知识的归属：条目 id 形如 k_u{user_id}_{uuid8}（提炼入库时的签发规则）。

    无归属记录的条目视为公共种子，无需插行。幂等：已存在的归属行跳过。
    """
    if not VSE_KNOWLEDGE_DB.exists():
        return
    try:
        entries = json.loads(VSE_KNOWLEDGE_DB.read_text(encoding="utf-8"))
    except Exception:
        return
    pairs = set()
    for e in entries:
        m = re.match(r"^k_u(\d+)_", str(e.get("id", "")))
        if m:
            pairs.add((e["id"], int(m.group(1))))
    if not pairs:
        return
    with engine.connect() as conn:
        existing = {row[0] for row in conn.execute(text("SELECT entry_id FROM knowledgeownership"))}
        for entry_id, user_id in pairs:
            if entry_id in existing:
                continue
            conn.execute(
                text("INSERT INTO knowledgeownership (entry_id, user_id, created_at) VALUES (:eid, :uid, datetime('now'))"),
                {"eid": entry_id, "uid": user_id},
            )
        conn.commit()


def _migrate_api_keys_to_models():
    """Turn records from the old key-only settings page into model configs."""
    from db_models import ApiKey, ModelConfiguration, Provider
    from secret_store import encrypt_secret

    presets = {
        Provider.ZHIPU: {
            "display_name": "智谱 GLM 视觉分析",
            "model_id": "glm-4.6v-flash",
            "endpoint_url": "https://open.bigmodel.cn/api/paas/v4",
            "supports_vision": True,
        },
        Provider.DEEPSEEK: {
            "display_name": "DeepSeek",
            "model_id": "deepseek-chat",
            "endpoint_url": "https://api.deepseek.com",
            "supports_vision": False,
        },
        Provider.MOONSHOT: {
            "display_name": "Moonshot / Kimi",
            "model_id": "kimi-2.6",
            "endpoint_url": "https://api.moonshot.cn/v1",
            "supports_vision": False,
        },
    }
    with Session(engine) as session:
        for existing_model in session.exec(select(ModelConfiguration)).all():
            encrypted = encrypt_secret(existing_model.api_key)
            if encrypted != existing_model.api_key:
                existing_model.api_key = encrypted
                session.add(existing_model)
        for old_key in session.exec(select(ApiKey)).all():
            preset = presets.get(old_key.provider)
            if not preset:
                continue
            existing = session.exec(
                select(ModelConfiguration).where(
                    ModelConfiguration.user_id == old_key.user_id,
                    ModelConfiguration.provider == old_key.provider.value,
                )
            ).first()
            if existing:
                continue
            user_models = session.exec(
                select(ModelConfiguration).where(ModelConfiguration.user_id == old_key.user_id)
            ).all()
            model = ModelConfiguration(
                user_id=old_key.user_id,
                provider=old_key.provider.value,
                api_key=encrypt_secret(old_key.key_value),
                is_default_vision=preset["supports_vision"] and not any(
                    item.is_default_vision for item in user_models
                ),
                is_default_text=(
                    old_key.provider != Provider.ZHIPU
                    and not any(item.is_default_text for item in user_models)
                ),
                **preset,
            )
            session.add(model)
            session.flush()
        session.commit()


def _migrate_project_gene_column():
    """Keep the selected gene attached to projects created by older databases."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(project)"))}
        if "gene_id" not in cols:
            conn.execute(text("ALTER TABLE project ADD COLUMN gene_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_project_gene_id ON project (gene_id)"))
        conn.commit()


def _migrate_task_storyboard_columns():
    """Add the two-stage storyboard workflow to existing task tables."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(task)"))}
        if "workflow_stage" not in cols:
            conn.execute(text("ALTER TABLE task ADD COLUMN workflow_stage VARCHAR DEFAULT 'prepare'"))
        if "scheme_path" not in cols:
            conn.execute(text("ALTER TABLE task ADD COLUMN scheme_path VARCHAR"))
        if "draft_revision" not in cols:
            conn.execute(text("ALTER TABLE task ADD COLUMN draft_revision INTEGER DEFAULT 0"))
        conn.execute(text("UPDATE task SET workflow_stage = 'prepare' WHERE workflow_stage IS NULL"))
        conn.execute(text("UPDATE task SET draft_revision = 0 WHERE draft_revision IS NULL"))
        conn.commit()


def _migrate_chat_memory_columns():
    """Add bounded conversation-memory fields to databases created before chat memory."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(chatsession)"))}
        if not cols:
            return
        if "memory_summary" not in cols:
            conn.execute(text("ALTER TABLE chatsession ADD COLUMN memory_summary TEXT DEFAULT ''"))
        if "memory_cursor_id" not in cols:
            conn.execute(text("ALTER TABLE chatsession ADD COLUMN memory_cursor_id INTEGER DEFAULT 0"))
        if "memory_json" not in cols:
            conn.execute(text("ALTER TABLE chatsession ADD COLUMN memory_json TEXT DEFAULT '{}'"))
        conn.execute(text("UPDATE chatsession SET memory_summary = '' WHERE memory_summary IS NULL"))
        conn.execute(text("UPDATE chatsession SET memory_cursor_id = 0 WHERE memory_cursor_id IS NULL"))
        conn.execute(text("UPDATE chatsession SET memory_json = '{}' WHERE memory_json IS NULL"))
        conn.commit()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _migrate_project_gene_column()
    _migrate_task_storyboard_columns()
    _migrate_chat_memory_columns()
    _migrate_gene_progress_columns()
    _migrate_knowledge_ownership()
    _migrate_api_keys_to_models()


def get_session() -> Session:
    with Session(engine) as session:
        yield session
