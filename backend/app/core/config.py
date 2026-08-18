import socket
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings

# Stamped on every collected row. Bump when the row shape changes so
# training/aggregation pipelines can tell schema generations apart.
SCHEMA_VERSION = "3"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite:///{(BACKEND_ROOT / 'smartdesk.db').as_posix()}"
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

    # ── Embedding model location ───────────────────────────────────
    # Point EMBEDDING_MODEL_PATH at an unpacked model directory to load the
    # encoder from disk instead of huggingface.co — required for a packaged
    # build, which otherwise needs ~88 MB of network on first run and fails
    # offline. EMBEDDING_CACHE_DIR only redirects where a hub download lands.
    EMBEDDING_MODEL_PATH: str = ""
    EMBEDDING_CACHE_DIR: str = ""

    # ── Supervised model store ─────────────────────────────────────
    # The trained classifier used to live only in process memory, so every
    # restart silently reverted categorisation to rules + embedding
    # similarity until something retrained it. It is persisted here instead.
    MODEL_STORE_DIR: str = "./model_store"

    # Daily deep-work goal in minutes, for DY-16. Zero means "not set", which
    # is the default on purpose: a target nobody chose is a stick to beat
    # yourself with, and the rule stays silent until someone opts in.
    DAILY_DEEP_WORK_TARGET_MIN: int = 0

    # ── Recommendation exploration ─────────────────────────────────
    # How often the surfacing policy shows a card that did not earn its slot,
    # so that the learned ranker can be evaluated rather than merely trusted.
    #
    # Off by default. Exploration is a deliberate, visible trade: the panel
    # gets slightly worse on purpose, in exchange for the only data that makes
    # any off-policy estimate valid. That is a decision to take knowingly at
    # the start of an evaluation period, not a default to inherit.
    #
    # 0.1 is the usual starting point — one card in ten in the marginal slot.
    # Raise it for a shorter evaluation, lower it if dismissals climb. Only
    # the lowest-ranked slot of a section is ever at stake, and a high-severity
    # card is never displaced, so the worst case is one weaker suggestion.
    RECOMMENDATION_EPSILON: float = 0.0

    # False-discovery rate the daily battery of statistical claims is held to.
    #
    # The engine re-evaluates every rule each day, and a good fraction of them
    # end in a significance test. Publishing each one that clears 0.05 on its
    # own would mean publishing noise regularly and confidently: twenty true
    # nulls give about a 64% chance that one of them looks real. Benjamini-
    # Hochberg holds the *proportion* of published claims that are false to
    # this level instead.
    #
    # 0.1 rather than 0.05 on purpose. These are nudges, not diagnoses; the
    # cost of one wrong suggestion is a dismissed card, and being too strict
    # here shows the user nothing at all, which is its own failure.
    RECOMMENDATION_FDR_Q: float = 0.10

    # ── Shared label sheet ─────────────────────────────────────────
    # Mirrors every typed label correction to a Google Sheet so a team can
    # pool training data. The database is always written first and remains
    # the source of truth; the sheet is best-effort. Requires a one-time
    # `python -c "import gspread; gspread.oauth()"` to cache credentials.
    ENABLE_GSHEET_SYNC: bool = False
    GSHEET_KEY: str = "1G_oudT83kv-JSugqzbVE-nbLyjmQ0c7YY5EGpbLUaG8"
    GSHEET_WORKSHEET: str = "Labels"

    # ── Embedding / Categorization Settings ────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_VERSION: str = "1.0"
    EMBEDDING_DIM: int = 384
    # Applies to the rule and supervised classifiers, whose confidences are
    # genuine probabilities/scores in [0, 1].
    CATEGORIZATION_THRESHOLD: float = 0.30

    # The zero-shot embedding classifier is held to its own bar, expressed in
    # raw cosine similarity. It used to report (cosine + 1) / 2, which turns a
    # cosine of 0.28 into a "confidence" of 0.64 — nothing could ever fall
    # below CATEGORIZATION_THRESHOLD, so the step was an unconditional argmax
    # over eight labels and filed 3,797 browser-chrome segments as "meetings"
    # on similarities no higher than 0.3. Both bars must now be cleared: the
    # winning label has to actually resemble the segment, and it has to beat
    # the runner-up by more than embedding noise.
    EMBEDDING_MIN_SIMILARITY: float = 0.30
    EMBEDDING_MIN_MARGIN: float = 0.04

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:1420",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:1420",
        "http://127.0.0.1:5173",
        "chrome-extension://*",
    ]

    # GitHub App / Projects v2 integration
    SMARTDESK_GITHUB_APP_ID: str = ""
    SMARTDESK_GITHUB_APP_SLUG: str = ""
    SMARTDESK_GITHUB_APP_PRIVATE_KEY: str = ""
    SMARTDESK_GITHUB_CALLBACK_URL: str = ""
    SMARTDESK_FRONTEND_URL: str = ""
    SMARTDESK_GITHUB_WEBHOOK_SECRET: str = ""
    SMARTDESK_GITHUB_MONITOR_MODE: str = "webhook"
    SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR: str = str(
        BACKEND_ROOT / "model_artifacts" / "github_effort"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

if not settings.DEVICE_ID:
    settings.DEVICE_ID = socket.gethostname().lower()
