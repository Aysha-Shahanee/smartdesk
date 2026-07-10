from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./smartdesk.db"
    DEFAULT_USER_ID: str = "local_user"
    LOG_LEVEL: str = "INFO"
    GOOGLE_CALENDAR_CREDENTIALS_FILE: str = "../calendar/credentials.json"
    GOOGLE_CALENDAR_TOKEN_FILE: str = "../calendar/token.json"
    GOOGLE_CALENDAR_SYNC_STATE_FILE: str = "../calendar/sync_state.json"
    GOOGLE_CALENDAR_OAUTH_STATE_FILE: str = "../calendar/oauth_state.json"
    GOOGLE_CALENDAR_SCOPES: List[str] = ["https://www.googleapis.com/auth/calendar.readonly"]
    GOOGLE_CALENDAR_REDIRECT_URI: str = "http://127.0.0.1:8000/api/v1/calendar/auth/callback"
    GITHUB_CONFIG_FILE: str = "../github_config.json"
    GITHUB_SYNC_INTERVAL_SEC: int = 120

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:1420",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:1420",
        "chrome-extension://*",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
