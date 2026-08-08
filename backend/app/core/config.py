import socket
from typing import List

from pydantic_settings import BaseSettings

# Stamped on every collected row. Bump when the row shape changes so
# training/aggregation pipelines can tell schema generations apart.
SCHEMA_VERSION = "3"


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./smartdesk.db"
    DEFAULT_USER_ID: str = "local_user"
    LOG_LEVEL: str = "INFO"

    # All stored/returned timestamps use this timezone.
    TIMEZONE: str = "Asia/Colombo"

    # Identifies which device collected each row (multi-device aggregation).
    # Empty = auto-detect the machine hostname.
    DEVICE_ID: str = ""

    # ── Google Calendar ────────────────────────────────────────────────
    # Developers can supply credentials either via env vars (client id +
    # secret) or via a credentials.json file path. Env vars win when both
    # are set. Tokens and sync state are kept in CALENDAR_STORE_DIR.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_CREDENTIALS_FILE: str = "./calendar_store/credentials.json"
    CALENDAR_STORE_DIR: str = "./calendar_store"
    CALENDAR_SYNC_INTERVAL_MIN: int = 15
    # How far back/forward the first full sync fetches events.
    CALENDAR_SYNC_PAST_DAYS: int = 30
    CALENDAR_SYNC_FUTURE_DAYS: int = 60
    # Public URL of this backend, used to build the OAuth redirect URI.
    BACKEND_BASE_URL: str = "http://127.0.0.1:8000"

    # ── Embedding / Categorization Settings ────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_VERSION: str = "1.0"
    EMBEDDING_DIM: int = 384
    CATEGORIZATION_THRESHOLD: float = 0.30

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:1420",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:1420",
        "http://127.0.0.1:5173",
        "chrome-extension://*",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

if not settings.DEVICE_ID:
    settings.DEVICE_ID = socket.gethostname().lower()
