"""
Centralized configuration for SmartDesk backend.
All environment variables and settings are defined here.
"""

from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./smartdesk.db"

    # Identity
    DEFAULT_USER_ID: str = "local_user"

    # Background task intervals
    CALENDAR_SYNC_INTERVAL_SEC: int = 900  # 15 minutes
    SESSION_SCHEDULER_INTERVAL_SEC: int = 60
    SESSION_SCHEDULER_WINDOW_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:1420",
        "chrome-extension://*",
    ]

    # Logging
    LOG_LEVEL: str = "INFO"

    # Google Calendar OAuth
    SMARTDESK_GOOGLE_CLIENT_ID: str = ""
    SMARTDESK_GOOGLE_CLIENT_SECRET: str = ""
    SMARTDESK_GOOGLE_PROJECT_ID: str = ""

    # GitHub App installation integration.
    SMARTDESK_GITHUB_APP_ID: str = ""
    SMARTDESK_GITHUB_APP_SLUG: str = ""
    SMARTDESK_GITHUB_APP_PRIVATE_KEY: str = ""
    SMARTDESK_GITHUB_CALLBACK_URL: str = "http://127.0.0.1:8000/api/v1/integrations/github/callback"
    SMARTDESK_GITHUB_WEBHOOK_SECRET: str = ""
    SMARTDESK_GITHUB_MONITOR_MODE: str = "webhook"
    SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR: str = str(BACKEND_DIR / "model_artifacts" / "github_effort")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
