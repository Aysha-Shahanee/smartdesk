"""
Centralized configuration for SmartDesk backend.
All environment variables and settings are defined here.
"""

from pydantic_settings import BaseSettings
from typing import List


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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
