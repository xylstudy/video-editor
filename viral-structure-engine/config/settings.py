import os
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"
SAMPLES_DIR = DATA_DIR / "samples"
ASSETS_DIR = DATA_DIR / "assets"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"
KNOWLEDGE_DB_DIR = DATA_DIR / "knowledge_db"

RUNS_DIR = DATA_DIR / "runs"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DB_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

DOMAIN = "vlog"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

# Web 端按账号选择的模型。未配置时继续兼容原有的智谱 / DeepSeek 环境变量。
VISION_API_KEY = os.getenv("VISION_API_KEY", ZHIPU_API_KEY)
VISION_BASE_URL = os.getenv("VISION_BASE_URL", ZHIPU_BASE_URL)
VISION_MODEL_ID = os.getenv("VISION_MODEL_ID", "glm-4.6v-flash")

TEXT_API_KEY = os.getenv("TEXT_API_KEY", DEEPSEEK_API_KEY)
TEXT_BASE_URL = os.getenv("TEXT_BASE_URL", DEEPSEEK_BASE_URL)
TEXT_MODEL_ID = os.getenv("TEXT_MODEL_ID", "deepseek-chat")

LLM_MAX_RETRIES = 3
LLM_TIMEOUT = 180

SCENE_CHANGE_THRESHOLD = 0.3
KEYFRAME_INTERVAL = 2.0

DEFAULT_VLOG_DURATION = 60
MAX_ITERATIONS = 3

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

# Dynamic TSX generation is useful for experiments but expensive and less
# deterministic than the built-in Remotion component library. Batch runners
# may disable it per child process without changing interactive defaults.
ENABLE_DYNAMIC_COMPONENTS = os.getenv("ENABLE_DYNAMIC_COMPONENTS", "true").strip().lower() in {
    "1", "true", "yes", "on",
}

# Reuse expensive media understanding by content hash. Cache records contain
# structured genes/analysis only; original media and absolute paths are not copied.
ENABLE_ANALYSIS_CACHE = os.getenv("ENABLE_ANALYSIS_CACHE", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
