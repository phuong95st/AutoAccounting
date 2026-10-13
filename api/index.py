import sys
from pathlib import Path

# Add project root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Export app and handler for Vercel
from api.webhook import app, handler
