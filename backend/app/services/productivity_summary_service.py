import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.models.db_models import (
    BrowserMinuteWindowRecord,
    VSCodeMinuteWindowRecord,
    OSMinuteWindowRecord,
    CalendarEventRecord,
)
from app.repositories.productivity_summary_repository import ProductivitySummaryRepository


COLOMBO_TZ = ZoneInfo("Asia/Colombo")
WINDOW_MINUTES = 10
SCHEMA_VERSION = "1.0"
SOURCE_NAME = "productivity_summary_10min"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(COLOMBO_TZ)


def _to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def _align_to_10min(dt: datetime) -> datetime:
    local = dt.astimezone(COLOMBO_TZ)
    minute = (local.minute // WINDOW_MINUTES) * WINDOW_MINUTES
    return local.replace(minute=minute, second=0, microsecond=0)


def _ceil_to_10min(dt: datetime) -> datetime:
    local = dt.astimezone(COLOMBO_TZ)
    minute_bucket = (local.minute // WINDOW_MINUTES) * WINDOW_MINUTES
    aligned = local.replace(minute=minute_bucket, second=0, microsecond=0)
    if aligned < local:
        aligned += timedelta(minutes=WINDOW_MINUTES)
    return aligned


def _overlap_seconds(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> int:
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    delta = (overlap_end - overlap_start).total_seconds()
    return max(0, int(delta))


class ProductivitySummaryService:
    def __init__(self):
        self.repository = ProductivitySummaryRepository()

    def build(self, user_id: str, start_time: str, end_time: str):
        start_dt = _parse_iso_datetime(start_time)
        end_dt = _parse_iso_datetime(end_time)
        if not start_dt or not end_dt:
            raise ValueError("Invalid start_time or end_time")

        window_start = _align_to_10min(start_dt)
        window_end = _ceil_to_10min(end_dt)

        rows = self._load_source_rows(user_id, window_start, window_end)

        results = []
        current = window_start
        while current < window_end:
            next_window = current + timedelta(minutes=WINDOW_MINUTES)
            summary = self._build_window_summary(user_id, current, next_window, rows)
            result = self.repository.upsert(summary)
            results.append(result)
            current = next_window

        return {"built": len(results), "details": results}

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100):
        return self.repository.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)

    def _load_source_rows(self, user_id: str, window_start: datetime, window_end: datetime):
        session = SessionLocal()
        start_iso = _to_colombo_iso(window_start)
        end_iso = _to_colombo_iso(window_end)
        try:
            os_rows = (
                session.query(OSMinuteWindowRecord)
                .filter(
                    OSMinuteWindowRecord.user_id == user_id,
                    OSMinuteWindowRecord.window_end > start_iso,
                    OSMinuteWindowRecord.window_start < end_iso,
                )
                .all()
            )
            browser_rows = (
                session.query(BrowserMinuteWindowRecord)
                .filter(
                    BrowserMinuteWindowRecord.user_id == user_id,
                    BrowserMinuteWindowRecord.window_end > start_iso,
                    BrowserMinuteWindowRecord.window_start < end_iso,
                )
                .all()
            )
            vscode_rows = (
                session.query(VSCodeMinuteWindowRecord)
                .filter(
                    VSCodeMinuteWindowRecord.user_id == user_id,
                    VSCodeMinuteWindowRecord.window_end > start_iso,
                    VSCodeMinuteWindowRecord.window_start < end_iso,
                )
                .all()
            )
            calendar_rows = (
                session.query(CalendarEventRecord)
                .filter(
                    CalendarEventRecord.user_id == user_id,
                    CalendarEventRecord.end_time > start_iso,
                    CalendarEventRecord.start_time < end_iso,
                )
                .all()
            )
        finally:
            session.close()

        return {
            "os": os_rows,
            "browser": browser_rows,
            "vscode": vscode_rows,
            "calendar": calendar_rows,
        }

    def _build_window_summary(self, user_id: str, window_start: datetime, window_end: datetime, rows: dict):
        # --- OS totals ---
        total_active_time_sec = 0
        total_idle_time_sec = 0
        total_locked_time_sec = 0
        context_switch_count = 0

        for row in rows["os"]:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue
            if ws < window_end and we > window_start:
                total_active_time_sec += int(row.active_time_sec or 0)
                total_idle_time_sec += int(row.idle_time_sec or 0)
                total_locked_time_sec += int(row.locked_time_sec or 0)
                context_switch_count += int(row.context_switch_count or 0)

        # --- Browser time ---
        browser_time_sec = 0
        for row in rows["browser"]:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue
            if ws < window_end and we > window_start:
                browser_time_sec += int(row.browser_active_time_sec or 0)

        # --- VS Code time ---
        vscode_time_sec = 0
        for row in rows["vscode"]:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue
            if ws < window_end and we > window_start:
                vscode_time_sec += int(row.active_editor_sec or 0)

        # --- Calendar meeting time ---
        calendar_meeting_time_sec = 0
        for row in rows["calendar"]:
            start = _parse_iso_datetime(row.start_time)
            end = _parse_iso_datetime(row.end_time)
            if not start or not end:
                continue
            calendar_meeting_time_sec += _overlap_seconds(start, end, window_start, window_end)

        now_iso = _to_colombo_iso(datetime.now(COLOMBO_TZ))

        return {
            "user_id": user_id,
            "window_start": _to_colombo_iso(window_start),
            "window_end": _to_colombo_iso(window_end),
            "total_active_time_sec": total_active_time_sec,
            "total_idle_time_sec": total_idle_time_sec,
            "total_locked_time_sec": total_locked_time_sec,
            "browser_time_sec": browser_time_sec,
            "vscode_time_sec": vscode_time_sec,
            "calendar_meeting_time_sec": calendar_meeting_time_sec,
            "context_switch_count": context_switch_count,
            "created_at": now_iso,
        }
