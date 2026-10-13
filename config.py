import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Gemini API Keys (loaded from .env)
GEMINI_API_KEY_PRIMARY = os.getenv("GEMINI_API_KEY_PRIMARY", "")
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


# Paths
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "accounting.db"
RULES_PATH = DATA_DIR / "skills_and_rules.json"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
