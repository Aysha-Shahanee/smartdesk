"""Independent configuration for the SmartDesk GitHub collector."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


MODULE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Load GitHub settings using the same settings pattern as SmartDesk."""

    GITHUB_TOKEN: str = ""
    GITHUB_OWNER: str = ""
    PROJECT_NUMBER: int = 4
    POLL_INTERVAL_SECONDS: int = 30
    GITHUB_DATABASE_URL: str = f"sqlite:///{(MODULE_DIR / 'storage' / 'github_data.db').as_posix()}"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=MODULE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("PROJECT_NUMBER", "POLL_INTERVAL_SECONDS")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be a positive integer")
        return value

    def validate_github_access(self) -> None:
        """Fail only when an operation actually requires GitHub access."""
        missing = []
        if not self.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if not self.GITHUB_OWNER:
            missing.append("GITHUB_OWNER")
        if missing:
            raise RuntimeError(
                f"Missing GitHub configuration: {', '.join(missing)}. "
                f"Set it in {MODULE_DIR / '.env'} or in the environment."
            )


settings = Settings()

# Backward-compatible aliases for the existing collector functions.
GITHUB_TOKEN = settings.GITHUB_TOKEN
GITHUB_OWNER = settings.GITHUB_OWNER
PROJECT_NUMBER = settings.PROJECT_NUMBER
POLL_INTERVAL_SECONDS = settings.POLL_INTERVAL_SECONDS
