"""Globale instellingen voor de indexing tool."""

import os
from pathlib import Path

# Paden
PROJECT_DIR = Path(__file__).parent.parent
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = DATA_DIR / "logs"

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Google Service Account
# In GitHub Actions: base64-encoded JSON key in env var
# Lokaal: pad naar JSON bestand
GOOGLE_SERVICE_ACCOUNT_KEY = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
SERVICE_ACCOUNT_KEY_PATH = PROJECT_DIR / "service-account-key.json"

# API limieten
INSPECTION_DAILY_LIMIT_PER_SHOP = 15
INDEXING_DAILY_LIMIT = 200  # totaal over alle shops
INSPECTION_DELAY_SECONDS = 2.0  # pauze tussen API calls
INDEXING_DELAY_SECONDS = 0.5

# Scheduling
RETRY_INTERVAL_DAYS = 3   # opnieuw inspecteren na X dagen bij failure
RESCAN_INTERVAL_DAYS = 7  # volledige rescan na X dagen
BATCH_SIZE = 100           # URLs per batch in CLI

# URL type prioriteit voor pushen (lager = hogere prioriteit)
PUSH_PRIORITY = {
    "collection": 1,
    "product": 2,
    "page": 3,
    "blog": 4,
    "faq": 5,
    "other": 6,
}
