from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    github_webhook_secret: str
    client_auth_secret: str
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    max_webhook_bytes: int = 1_048_576
    registration_timeout_seconds: float = 10.0
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            value.strip()
            for value in os.getenv("SMARTDESK_RELAY_ALLOWED_ORIGINS", "").split(",")
            if value.strip()
        )
        return cls(
            github_webhook_secret=os.getenv("SMARTDESK_RELAY_GITHUB_WEBHOOK_SECRET", ""),
            client_auth_secret=os.getenv("SMARTDESK_RELAY_CLIENT_AUTH_SECRET", ""),
            host=os.getenv("SMARTDESK_RELAY_HOST", "0.0.0.0"),
            port=int(os.getenv("SMARTDESK_RELAY_PORT", "8080")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            max_webhook_bytes=int(os.getenv("SMARTDESK_RELAY_MAX_WEBHOOK_BYTES", "1048576")),
            registration_timeout_seconds=float(
                os.getenv("SMARTDESK_RELAY_REGISTRATION_TIMEOUT_SECONDS", "10")
            ),
            allowed_origins=origins,
        )

