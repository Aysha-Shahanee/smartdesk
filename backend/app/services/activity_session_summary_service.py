from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.models.db_models import (
    ActivitySessionSummaryRecord,
    OSMinuteWindowRecord,
    BrowserMinuteWindowRecord,
    VSCodeMinuteWindowRecord,
    CalendarEventRecord,
)
from app.repositories.activity_session_summary_repository import ActivitySessionSummaryRepository


COLOMBO_TZ = ZoneInfo("Asia/Colombo")
SCHEMA_VERSION = "1.0"
SOURCE_NAME = "activity_session_builder"


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


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _overlap_seconds(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> int:
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    delta = (overlap_end - overlap_start).total_seconds()
    return max(0, int(delta))


def _row_state(row: OSMinuteWindowRecord) -> str:
    locked = int(row.locked_time_sec or 0)
    idle = int(row.idle_time_sec or 0)
    if locked >= 30:
        return "locked"
    if idle >= 45:
        return "idle"
    return "active"


def _activity_type(
    duration_sec: int,
    total_idle: int,
    total_locked: int,
    vscode_time: int,
    browser_time: int,
    active_tab_category: str | None,
    primary_app: str | None,
    calendar_meeting: int,
) -> str:
    if calendar_meeting > 0:
        return "Meeting"
    if duration_sec > 0 and total_locked >= int(duration_sec * 0.6):
        return "Locked"
    if duration_sec > 0 and total_idle >= int(duration_sec * 0.6):
        return "Idle"

    primary_app_l = (primary_app or "").lower()
    if vscode_time >= max(60, int(duration_sec * 0.25)) or "code" in primary_app_l:
        return "Coding"

    if browser_time >= max(60, int(duration_sec * 0.25)):
        category_l = (active_tab_category or "").lower()
        if category_l == "distracted" or category_l == "distracting":
            return "Distracted Browsing"
        return "Browser Research"

    return "Other"


def _activity_description(
    activity_type: str,
    primary_app: str | None,
    active_file_name: str | None,
    top_domain: str | None,
    meeting_title: str | None,
) -> str:
    if activity_type == "Meeting" and meeting_title:
        return f"Meeting: {meeting_title}"
    if activity_type == "Coding" and active_file_name:
        return f"Coding in VS Code - {active_file_name}"
    if activity_type in {"Browser Research", "Distracted Browsing"} and top_domain:
        return f"Browser activity on {top_domain}"
    if activity_type == "Idle":
        return "Idle period"
    if activity_type == "Locked":
        return "Device locked"
    if primary_app:
        return f"Working in {primary_app}"
    return "General activity"


class ActivitySessionSummaryService:
    def __init__(self):
        self.repository = ActivitySessionSummaryRepository()

    def build(self, user_id: str, start_time: str, end_time: str):
        start_dt = _parse_iso_datetime(start_time)
        end_dt = _parse_iso_datetime(end_time)
        if not start_dt or not end_dt:
            raise ValueError("Invalid start_time or end_time")

        start_iso = _to_colombo_iso(start_dt)
        end_iso = _to_colombo_iso(end_dt)
        self.repository.delete_overlapping(user_id, start_iso, end_iso)

        os_rows = self._load_os_rows(user_id, start_dt, end_dt)
        sessions = self._detect_sessions(os_rows)

        if not sessions:
            return {"built": 0, "details": []}

        browser_rows = self._load_browser_rows(user_id, start_dt, end_dt)
        vscode_rows = self._load_vscode_rows(user_id, start_dt, end_dt)
        calendar_rows = self._load_calendar_rows(user_id, start_dt, end_dt)

        results = []
        for session in sessions:
            summary = self._build_session_summary(
                user_id,
                session,
                browser_rows,
                vscode_rows,
                calendar_rows,
            )
            results.append(self.repository.upsert(summary))

        return {"built": len(results), "details": results}

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 200):
        return self.repository.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)

    def _load_os_rows(self, user_id: str, start_dt: datetime, end_dt: datetime):
        session = SessionLocal()
        start_iso = _to_colombo_iso(start_dt)
        end_iso = _to_colombo_iso(end_dt)
        try:
            return (
                session.query(OSMinuteWindowRecord)
                .filter(
                    OSMinuteWindowRecord.user_id == user_id,
                    OSMinuteWindowRecord.window_end > start_iso,
                    OSMinuteWindowRecord.window_start < end_iso,
                )
                .order_by(OSMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _load_browser_rows(self, user_id: str, start_dt: datetime, end_dt: datetime):
        session = SessionLocal()
        start_iso = _to_colombo_iso(start_dt)
        end_iso = _to_colombo_iso(end_dt)
        try:
            return (
                session.query(BrowserMinuteWindowRecord)
                .filter(
                    BrowserMinuteWindowRecord.user_id == user_id,
                    BrowserMinuteWindowRecord.window_end > start_iso,
                    BrowserMinuteWindowRecord.window_start < end_iso,
                )
                .order_by(BrowserMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _load_vscode_rows(self, user_id: str, start_dt: datetime, end_dt: datetime):
        session = SessionLocal()
        start_iso = _to_colombo_iso(start_dt)
        end_iso = _to_colombo_iso(end_dt)
        try:
            return (
                session.query(VSCodeMinuteWindowRecord)
                .filter(
                    VSCodeMinuteWindowRecord.user_id == user_id,
                    VSCodeMinuteWindowRecord.window_end > start_iso,
                    VSCodeMinuteWindowRecord.window_start < end_iso,
                )
                .order_by(VSCodeMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _load_calendar_rows(self, user_id: str, start_dt: datetime, end_dt: datetime):
        session = SessionLocal()
        start_iso = _to_colombo_iso(start_dt)
        end_iso = _to_colombo_iso(end_dt)
        try:
            return (
                session.query(CalendarEventRecord)
                .filter(
                    CalendarEventRecord.user_id == user_id,
                    CalendarEventRecord.end_time > start_iso,
                    CalendarEventRecord.start_time < end_iso,
                )
                .order_by(CalendarEventRecord.start_time)
                .all()
            )
        finally:
            session.close()

    def _detect_sessions(self, os_rows):
        sessions = []
        current = None

        for row in os_rows:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue

            row_state = _row_state(row)
            if current is None:
                current = {
                    "rows": [row],
                    "session_start": ws,
                    "session_end": we,
                    "last_end": we,
                    "last_app": row.top_app,
                    "last_category": row.dominant_app_category,
                    "last_state": row_state,
                }
                continue

            gap = ws - current["last_end"]
            gap_break = gap > timedelta(minutes=2)
            app_break = row.top_app != current["last_app"]
            category_break = row.dominant_app_category != current["last_category"]
            state_break = row_state != current["last_state"]

            if gap_break or app_break or category_break or state_break:
                sessions.append(current)
                current = {
                    "rows": [row],
                    "session_start": ws,
                    "session_end": we,
                    "last_end": we,
                    "last_app": row.top_app,
                    "last_category": row.dominant_app_category,
                    "last_state": row_state,
                }
                continue

            current["rows"].append(row)
            current["session_end"] = we
            current["last_end"] = we
            current["last_app"] = row.top_app
            current["last_category"] = row.dominant_app_category
            current["last_state"] = row_state

        if current:
            sessions.append(current)
        return sessions

    def _build_session_summary(
        self,
        user_id: str,
        session: dict,
        browser_rows,
        vscode_rows,
        calendar_rows,
    ):
        session_start = session["session_start"]
        session_end = session["session_end"]
        duration_sec = max(1, int((session_end - session_start).total_seconds()))

        total_active = 0
        total_idle = 0
        total_locked = 0
        context_switch_count = 0
        app_time = Counter()
        category_time = Counter()

        for row in session["rows"]:
            total_active += int(row.active_time_sec or 0)
            total_idle += int(row.idle_time_sec or 0)
            total_locked += int(row.locked_time_sec or 0)
            context_switch_count += int(row.context_switch_count or 0)
            if row.top_app:
                app_time[row.top_app] += int(row.active_time_sec or 0)
            if row.dominant_app_category:
                category_time[row.dominant_app_category] += int(row.active_time_sec or 0)

        primary_app = app_time.most_common(1)[0][0] if app_time else None
        primary_category = category_time.most_common(1)[0][0] if category_time else None

        browser_time_sec = 0
        top_domain = None
        active_tab_category = None
        latest_browser_end: datetime | None = None

        for row in browser_rows:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue
            if not _overlaps(ws, we, session_start, session_end):
                continue
            browser_time_sec += int(row.browser_active_time_sec or 0)
            if latest_browser_end is None or we > latest_browser_end:
                latest_browser_end = we
                top_domain = row.active_tab_domain
                active_tab_category = row.active_tab_category

        vscode_time_sec = 0
        active_file_name = None
        latest_vscode_end: datetime | None = None

        for row in vscode_rows:
            ws = _parse_iso_datetime(row.window_start)
            we = _parse_iso_datetime(row.window_end)
            if not ws or not we:
                continue
            if not _overlaps(ws, we, session_start, session_end):
                continue
            vscode_time_sec += int(row.active_editor_sec or 0)
            if latest_vscode_end is None or we > latest_vscode_end:
                latest_vscode_end = we
                active_file_name = row.active_file_name

        calendar_meeting_time_sec = 0
        meeting_title = None
        max_meeting_overlap = 0

        for row in calendar_rows:
            start = _parse_iso_datetime(row.start_time)
            end = _parse_iso_datetime(row.end_time)
            if not start or not end:
                continue
            overlap = _overlap_seconds(start, end, session_start, session_end)
            if overlap <= 0:
                continue
            calendar_meeting_time_sec += overlap
            if overlap > max_meeting_overlap:
                max_meeting_overlap = overlap
                meeting_title = row.title

        in_meeting = 1 if calendar_meeting_time_sec > 0 else 0

        activity_type = _activity_type(
            duration_sec,
            total_idle,
            total_locked,
            vscode_time_sec,
            browser_time_sec,
            active_tab_category,
            primary_app,
            calendar_meeting_time_sec,
        )
        activity_description = _activity_description(
            activity_type,
            primary_app,
            active_file_name,
            top_domain,
            meeting_title,
        )

        now_iso = _to_colombo_iso(datetime.now(COLOMBO_TZ))

        return {
            "user_id": user_id,
            "session_start": _to_colombo_iso(session_start),
            "session_end": _to_colombo_iso(session_end),
            "timezone": "Asia/Colombo",
            "duration_sec": duration_sec,
            "primary_app": primary_app,
            "primary_category": primary_category,
            "total_active_time_sec": total_active,
            "total_idle_time_sec": total_idle,
            "total_locked_time_sec": total_locked,
            "context_switch_count": context_switch_count,
            "browser_time_sec": browser_time_sec,
            "top_domain": top_domain,
            "active_tab_category": active_tab_category,
            "calendar_meeting_time_sec": calendar_meeting_time_sec,
            "in_meeting": in_meeting,
            "activity_type": activity_type,
            "activity_description": activity_description,
            "source": SOURCE_NAME,
            "schema_version": SCHEMA_VERSION,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
