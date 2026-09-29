import enum
import json
from datetime import datetime
from typing import Optional

from pydantic import field_validator
from sqlmodel import Field, Relationship, SQLModel, Column
from sqlalchemy import String, DateTime, Text, JSON


class PipelineMode(str, enum.Enum):
    EDITING_TRANSFER = "editing_transfer"
    AGENT_PIPELINE = "agent_pipeline"


class TaskType(str, enum.Enum):
    END_TO_END = "end_to_end"
    ANALYZE_VIDEO = "analyze_video"
    MATERIAL_ANALYSIS = "material_analysis"
    GENERATE_SCHEME = "generate_scheme"
    RENDER = "render"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Provider(str, enum.Enum):
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    MOONSHOT = "moonshot"
    ALIYUN = "aliyun"


class ApiFormat(str, enum.Enum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"


class EndpointMode(str, enum.Enum):
    BASE_URL = "base_url"
    FULL_URL = "full_url"


class ModelPurpose(str, enum.Enum):
    VISION = "vision"
    TEXT = "text"


class UserBase(SQLModel):
    username: str = Field(index=True, unique=True)
    email: Optional[str] = Field(default=None, index=True)


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    projects: list["Project"] = Relationship(back_populates="user")
    api_keys: list["ApiKey"] = Relationship(back_populates="user")
    model_configs: list["ModelConfiguration"] = Relationship(back_populates="user")


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    created_at: datetime


class ApiKey(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: Provider
    key_value: str
    is_user_provided: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: User = Relationship(back_populates="api_keys")


class ApiKeyCreate(SQLModel):
    provider: Provider
    key_value: str


class ApiKeyRead(SQLModel):
    id: int
    provider: Provider
    is_user_provided: bool
    created_at: datetime


class ModelConfiguration(SQLModel, table=True):
    """A user-owned OpenAI-compatible model endpoint.

    API keys are intentionally omitted from all read schemas and encrypted
    before persistence. They are decrypted only for the local worker process.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str = Field(default="custom", index=True)
    display_name: str
    model_id: str
    endpoint_url: str
    endpoint_mode: EndpointMode = Field(default=EndpointMode.BASE_URL)
    api_format: ApiFormat = Field(default=ApiFormat.OPENAI_CHAT_COMPLETIONS)
    api_key: str = ""
    supports_vision: bool = Field(default=False)
    enabled: bool = Field(default=True)
    is_default_vision: bool = Field(default=False)
    is_default_text: bool = Field(default=False)
    last_test_status: Optional[str] = Field(default=None)
    last_test_message: Optional[str] = Field(default=None)
    last_tested_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    user: User = Relationship(back_populates="model_configs")


class ModelConfigurationCreate(SQLModel):
    provider: str = "custom"
    display_name: str
    model_id: str
    endpoint_url: str
    endpoint_mode: EndpointMode = EndpointMode.BASE_URL
    api_format: ApiFormat = ApiFormat.OPENAI_CHAT_COMPLETIONS
    api_key: str = ""
    supports_vision: bool = False
    enabled: bool = True
    use_for_vision: bool = False
    use_for_text: bool = False


class ModelConfigurationUpdate(SQLModel):
    provider: Optional[str] = None
    display_name: Optional[str] = None
    model_id: Optional[str] = None
    endpoint_url: Optional[str] = None
    endpoint_mode: Optional[EndpointMode] = None
    api_format: Optional[ApiFormat] = None
    api_key: Optional[str] = None
    supports_vision: Optional[bool] = None
    enabled: Optional[bool] = None


class ModelConfigurationRead(SQLModel):
    id: int
    provider: str
    display_name: str
    model_id: str
    endpoint_url: str
    endpoint_mode: EndpointMode
    api_format: ApiFormat
    has_api_key: bool
    masked_api_key: str
    supports_vision: bool
    enabled: bool
    is_default_vision: bool
    is_default_text: bool
    last_test_status: Optional[str]
    last_test_message: Optional[str]
    last_tested_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ModelConnectionTest(SQLModel):
    provider: str = "custom"
    model_id: str
    endpoint_url: str
    endpoint_mode: EndpointMode = EndpointMode.BASE_URL
    api_format: ApiFormat = ApiFormat.OPENAI_CHAT_COMPLETIONS
    api_key: Optional[str] = None
    model_config_id: Optional[int] = None


class ChatSession(SQLModel, table=True):
    """A user-owned assistant conversation."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(default="新对话")
    context_json: str = Field(default="{}", sa_column=Column(Text))
    # A bounded, compact record of turns that have rolled out of the model's
    # short-term history window. It is data for the planner, never instructions.
    memory_summary: str = Field(default="", sa_column=Column(Text))
    memory_cursor_id: int = Field(default=0)
    # Structured workflow memory is kept separately from the archived text so
    # the assistant can retain goals and verified workflow state across turns.
    memory_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatSessionCreate(SQLModel):
    title: str = "新对话"
    context: dict = Field(default_factory=dict)


class ChatSessionRead(SQLModel):
    id: int
    title: str
    context: dict
    created_at: datetime
    updated_at: datetime


class ChatContextUpdate(SQLModel):
    """Explicitly switch the workspace a conversation is operating in."""

    context: dict = Field(default_factory=dict)


class ChatAttachment(SQLModel, table=True):
    """A media file temporarily uploaded through the assistant."""

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    filename: str
    media_type: str
    storage_path: str
    status: str = Field(default="pending", index=True)
    material_id: Optional[int] = Field(default=None, foreign_key="material.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(SQLModel, table=True):
    """Persisted chat messages; metadata contains safe UI/action details."""

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: str = Field(index=True)  # user / assistant / system
    content: str = Field(sa_column=Column(Text))
    message_type: str = Field(default="text")
    metadata_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessageCreate(SQLModel):
    content: str
    context: dict = Field(default_factory=dict)


class ChatAction(SQLModel, table=True):
    """Audit trail and confirmation state for assistant side effects."""

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    message_id: Optional[int] = Field(default=None, foreign_key="chatmessage.id", index=True)
    task_id: Optional[int] = Field(default=None, foreign_key="task.id", index=True)
    action_type: str = Field(index=True)
    status: str = Field(default="completed", index=True)
    requires_confirmation: bool = False
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    result_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed_at: Optional[datetime] = None


class ProjectBase(SQLModel):
    name: str
    topic: str = Field(default="")
    pipeline_mode: PipelineMode = Field(default=PipelineMode.EDITING_TRANSFER)


class Project(ProjectBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    gene_id: Optional[int] = Field(default=None, foreign_key="gene.id", index=True)
    status: str = Field(default="idle")  # idle / running / etc.
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: User = Relationship(back_populates="projects")
    materials: list["Material"] = Relationship(back_populates="project")
    tasks: list["Task"] = Relationship(back_populates="project")


class ProjectCreate(ProjectBase):
    gene_id: Optional[int] = None  # 从基因库选择参考视频时传入


class ProjectRead(ProjectBase):
    id: int
    user_id: int
    gene_id: Optional[int] = None
    status: str
    created_at: datetime


class MaterialType(str, enum.Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"


class Material(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    type: MaterialType
    filename: str
    storage_path: str
    metadata_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="materials")

    def get_metadata(self) -> dict:
        if self.metadata_json:
            return json.loads(self.metadata_json)
        return {}

    def set_metadata(self, data: dict):
        self.metadata_json = json.dumps(data, ensure_ascii=False)


class MaterialRead(SQLModel):
    id: int
    project_id: int
    type: MaterialType
    filename: str
    meta: dict
    created_at: datetime


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    type: TaskType
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    progress: int = Field(default=0)
    logs: list = Field(default_factory=list, sa_column=Column(JSON))
    workflow_stage: str = Field(default="prepare")  # prepare / render
    scheme_path: Optional[str] = Field(default=None)
    draft_revision: int = Field(default=0)
    result_path: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    project: Project = Relationship(back_populates="tasks")


class TaskCreate(SQLModel):
    type: TaskType


class TaskRead(SQLModel):
    id: int
    project_id: int
    type: TaskType
    status: TaskStatus
    progress: int
    logs: list
    workflow_stage: str
    scheme_path: Optional[str]
    draft_revision: int
    result_path: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class TaskProgressEvent(SQLModel):
    type: str  # "log" | "progress" | "status"
    data: dict


class GeneStatus(str, enum.Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


class Gene(SQLModel, table=True):
    """视频基因：一条爆款参考视频 + 它的完整结构分析报告。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str
    status: GeneStatus = Field(default=GeneStatus.PENDING)
    source_filename: str = ""
    video_path: str = ""  # 存储的参考视频副本
    report_path: str = ""  # analysis_result.json 路径
    error_message: Optional[str] = None
    progress: int = Field(default=0)  # 提取进度 0-100
    progress_logs: list = Field(default_factory=list, sa_column=Column(JSON))  # 提取过程事件日志

    # 摘要字段（报告解析后填充，供列表卡片展示）
    duration: float = 0.0
    shot_count: int = 0
    structure_type: str = ""
    narrative_type: str = ""
    overall_emotion: str = ""
    hook_method: str = ""

    created_at: datetime = Field(default_factory=datetime.utcnow)


class GeneRead(SQLModel):
    id: int
    title: str
    status: GeneStatus
    source_filename: str
    duration: float
    shot_count: int
    structure_type: str
    narrative_type: str
    overall_emotion: str
    hook_method: str
    error_message: Optional[str]
    progress: int
    progress_logs: list
    created_at: datetime

    @field_validator("progress", "progress_logs", mode="before")
    @classmethod
    def _none_to_default(cls, v, info):
        # 历史行新列可能是 NULL，兜底为默认值，避免整列序列化 500
        if v is None:
            return [] if info.field_name == "progress_logs" else 0
        return v


class KnowledgeOwnership(SQLModel, table=True):
    """知识条目归属：把 knowledge.json 里的个人知识关联到用户。

    知识内容仍以引擎 knowledge.json 为单一事实源（07-18 决策 5），
    本表只记录"哪条知识是谁提炼的"；无归属记录的条目 = 公共种子，全员可见。
    """

    entry_id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
