import os
from pathlib import Path
# Base directory
BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

# Gemini API Keys (loaded from .env)
GEMINI_API_KEY_PRIMARY = os.getenv("GEMINI_API_KEY_PRIMARY", "") or os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY_BACKUP = os.getenv("GEMINI_API_KEY_BACKUP", "")


# Preferred Gemini models in priority order
GEMINI_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest"
]

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Google Sheets Integration
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "")
GOOGLE_SHEETS_URL = os.getenv("GOOGLE_SHEETS_URL", "")

# Optional allowed Telegram user IDs (comma separated string)
ALLOWED_TELEGRAM_USERS = [
    int(uid.strip()) for uid in os.getenv("ALLOWED_TELEGRAM_USERS", "").split(",") if uid.strip().isdigit()
]


# Optional default bank statement zip password
BANK_STATEMENT_PASSWORD = os.getenv("BANK_STATEMENT_PASSWORD", "").strip()

# Paths
# On Vercel serverless, root filesystem is read-only, only /tmp is writable
IS_VERCEL = bool(os.environ.get("VERCEL"))
DATA_DIR = Path("/tmp/data") if IS_VERCEL else (BASE_DIR / "data")
REPORTS_DIR = Path("/tmp/reports") if IS_VERCEL else (BASE_DIR / "reports")
RULES_PATH = DATA_DIR / "skills_and_rules.json"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

try:
    REPORTS_DIR.mkdir(exist_ok=True)
except Exception:
    pass

