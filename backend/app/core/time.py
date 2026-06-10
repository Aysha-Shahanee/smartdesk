from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

_COLOMBO = ZoneInfo("Asia/Colombo")


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def to_utc(value: datetime) -> datetime:
    """Return a UTC-aware datetime, converting from any timezone or naive (assumed UTC)."""
    return ensure_aware(value).astimezone(timezone.utc)


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def local_now_iso() -> str:
    return local_now().isoformat()


def to_local_iso(value: datetime) -> str:
    return ensure_aware(value).astimezone().isoformat()


def local_day_start_iso() -> str:
    return local_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00"))).astimezone()


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 string and return a UTC-aware datetime.

    Use this for SQLite DateTime comparisons — stored values are UTC.
    """
    return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def to_colombo_iso(dt: datetime | None) -> str | None:
    """Return an ISO 8601 string in Asia/Colombo (+05:30).

    Naive datetimes are treated as UTC (SQLite stores UTC but returns naive values).
    """
    if dt is None:
        return None
    return ensure_aware(dt).astimezone(_COLOMBO).isoformat()


def is_between_iso(value: str, start: str, end: str) -> bool:
    dt = parse_iso(value)
    return parse_iso(start) <= dt <= parse_iso(end)


def is_at_or_after_iso(value: str, start: str) -> bool:
    return parse_iso(value) >= parse_iso(start)
