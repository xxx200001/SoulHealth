"""全局配置：路径、环境变量、运行模式判定。

融合说明
--------
本文件是全系统唯一的配置入口。原 bio 侧的 app/config.py 与原 TongueDiag 侧
散落在 pipeline.py / auth_module.py 里的常量（API Key、JWT 密钥、知识库路径、
端口号）全部收拢到这里，不再有第二处硬编码。

运行模式语义（真实优先）
- LLM_MODE:
    real          配置了 ANTHROPIC_API_KEY → 图片抽取 / 健康问答 / AI 解读走真实模型；
    mock          显式 SOULHEALTH_MOCK=1 → 使用离线演示样例（且默认连带 biocompute=mock）；
    unconfigured  两者皆无 → 相关接口返回明确的配置指引，绝不悄悄给假答案。
- BIOCOMPUTE_MODE 默认 real：AlphaFold DB / UniProt / Ensembl 均为免密钥公开接口；
    EVO2 打分需自建服务或 NVIDIA_API_KEY，未配置时如实标记 skipped（不出假分）。

中医链路不依赖任何外部服务：辨证、组方、毒理、解释全部离线运行，
只依赖本地 data/tcm_kb.sqlite。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLE_DIR = DATA_DIR / "samples"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "soulhealth.db"
WEB_DIST = BASE_DIR / "web" / "dist"

for _d in (DATA_DIR, UPLOAD_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """极简 .env 加载（不覆盖已有环境变量）。"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# ---------------------------------------------------------------- 服务端口
HOST: str = os.getenv("SOULHEALTH_HOST", "0.0.0.0").strip()
PORT: int = int(os.getenv("SOULHEALTH_PORT", "8001"))

# ---------------------------------------------------------------- 大模型
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL",
                                    "https://api.anthropic.com").strip()
LLM_MODEL: str = os.getenv("SOULHEALTH_LLM_MODEL", "claude-sonnet-4-6").strip()

MOCK_MODE: bool = os.getenv("SOULHEALTH_MOCK", "").strip() == "1"
LLM_MODE: str = "mock" if MOCK_MODE else ("real" if ANTHROPIC_API_KEY else "unconfigured")

OCR_ENGINE: str = os.getenv("SOULHEALTH_OCR_ENGINE", "vision_llm").strip() or "vision_llm"

# ---------------------------------------------------------------- 生物计算
_bio_env = os.getenv("SOULHEALTH_BIOCOMPUTE", "").strip()
BIOCOMPUTE_MODE: str = _bio_env or ("mock" if MOCK_MODE else "real")

NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "").strip()
AFDB_API: str = os.getenv("SOULHEALTH_AFDB_API",
                          "https://alphafold.ebi.ac.uk/api/prediction/").strip()
UNIPROT_API: str = os.getenv("SOULHEALTH_UNIPROT_API",
                             "https://rest.uniprot.org/uniprotkb/search").strip()
ENSEMBL_API: str = os.getenv("SOULHEALTH_ENSEMBL_API",
                             "https://rest.ensembl.org").strip()
EVO2_URL: str = os.getenv("SOULHEALTH_EVO2_URL",
                          "http://localhost:8899/v1/evo2/score").strip()
BIOCOMPUTE_FIXTURES = SAMPLE_DIR / "biocompute"

# ---------------------------------------------------------------- 中医知识库
TCM_KB_PATH = Path(os.getenv("SOULHEALTH_TCM_KB", "").strip()
                   or (DATA_DIR / "tcm_kb.sqlite"))
# 缺库时是否允许用内置种子自举一个最小可用库（无方剂图谱/药典 QA，功能可跑但解释链偏短）
TCM_KB_AUTOBUILD: bool = os.getenv("SOULHEALTH_TCM_KB_AUTOBUILD", "1").strip() != "0"

# 报告中是否打印真实姓名（默认关闭：报告仅用化名，姓名只存本地库）
REPORT_REAL_NAME: bool = os.getenv("SOULHEALTH_REPORT_REAL_NAME", "").strip() == "1"

# 报告叙述段是否过一遍 LLM 润色（默认关闭：可复现性优先于文采）。
# 开启后仅润色纯叙述段落，结果仍过合规闸，违规即回退模板原文。
REPORT_POLISH: bool = os.getenv("SOULHEALTH_POLISH", "").strip() == "1"

# ---------------------------------------------------------------- 登录鉴权
_DEFAULT_DEV_SECRET = "soulhealth-demo-insecure-dev-secret-CHANGE-ME"
SECRET_KEY: str = os.getenv("SOULHEALTH_SECRET_KEY", "").strip() or _DEFAULT_DEV_SECRET
SECRET_KEY_IS_DEFAULT: bool = SECRET_KEY == _DEFAULT_DEV_SECRET
TOKEN_TTL_HOURS: float = float(os.getenv("SOULHEALTH_TOKEN_TTL_HOURS", "12"))

DEFAULT_ADMIN_USERNAME: str = os.getenv("SOULHEALTH_ADMIN_USER", "admin").strip()
DEFAULT_ADMIN_PASSWORD: str = os.getenv("SOULHEALTH_ADMIN_PASSWORD", "").strip()

VERSION = "2.0.0"


def runtime_info() -> dict:
    return {
        "version": VERSION,
        "llm_mode": LLM_MODE,
        "mock_mode": MOCK_MODE,
        "llm_model": LLM_MODEL,
        "ocr_engine": OCR_ENGINE,
        "biocompute_mode": BIOCOMPUTE_MODE,
        "evo2_url": EVO2_URL,
        "evo2_ready": ("localhost" in EVO2_URL or "127.0.0.1" in EVO2_URL
                       or bool(NVIDIA_API_KEY)),
        "db_path": str(DB_PATH),
        "report_polish": REPORT_POLISH,
        "tcm_kb_path": str(TCM_KB_PATH),
        "tcm_kb_ready": TCM_KB_PATH.exists(),
        "secret_key_is_default": SECRET_KEY_IS_DEFAULT,
    }
