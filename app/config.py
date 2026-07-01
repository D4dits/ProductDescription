import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Model Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL") or os.environ.get("LLM_MODEL")
ZAI_API_KEY = os.getenv("ZAI_API_KEY") or os.getenv("Z_AI_API_KEY") or os.environ.get("ZAI_API_KEY") or os.environ.get("Z_AI_API_KEY")
ZAI_BASE_URL = os.getenv("ZAI_BASE_URL") or os.getenv("Z_AI_BASE_URL") or os.environ.get("ZAI_BASE_URL") or os.environ.get("Z_AI_BASE_URL") or "https://api.z.ai/api/paas/v4/"
ZAI_MODEL = os.getenv("ZAI_MODEL") or os.getenv("Z_AI_MODEL") or os.environ.get("ZAI_MODEL") or os.environ.get("Z_AI_MODEL") or "glm-5.2"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"

# HTML Style Configuration
# Convert string to boolean
USE_LEGACY_INLINE_STYLES = os.getenv("USE_LEGACY_INLINE_STYLES", "false").lower() in ("true", "1", "yes")

# Scraping & Search Configuration
try:
    SCRAPE_PAGES_LIMIT = int(os.getenv("SCRAPE_PAGES_LIMIT", "5"))
except ValueError:
    SCRAPE_PAGES_LIMIT = 5

try:
    SCRAPE_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_TIMEOUT_SECONDS", "10"))
except ValueError:
    SCRAPE_TIMEOUT_SECONDS = 10

# Web Server Configuration
HOST = os.getenv("HOST", "127.0.0.1")
try:
    PORT = int(os.getenv("PORT", "8000"))
except ValueError:
    PORT = 8000

# Output, Cache, and Logs directories
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
