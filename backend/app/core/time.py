"""Time utilities.

All timestamps in SmartDesk are stored and returned as ISO 8601 strings
pinned to the application timezone (Asia/Colombo by default, configurable
via the TIMEZONE setting) — regardless of the machine's OS timezone.
"""

from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

APP_TZ = ZoneInfo(settings.TIMEZONE)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(APP_TZ)


def local_now_iso() -> str:
    return local_now().isoformat()


def to_local_iso(value: datetime) -> str:
    return ensure_aware(value).astimezone(APP_TZ).isoformat()


def local_day_start_iso() -> str:
    return local_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00"))).astimezone(APP_TZ)


def is_between_iso(value: str, start: str, end: str) -> bool:
    dt = parse_iso(value)
    return parse_iso(start) <= dt <= parse_iso(end)


def is_at_or_after_iso(value: str, start: str) -> bool:
    return parse_iso(value) >= parse_iso(start)
