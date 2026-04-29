import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.models.db_models import (
    BrowserMinuteWindowRecord,
    VSCodeMinuteWindowRecord,
    OSSignalRecord,
    CalendarRecord,
    OSMinuteWindowRecord,
    CalendarEventRecord,
)
from app.repositories.productivity_summary_repository import ProductivitySummaryRepository


COLOMBO_TZ = ZoneInfo("Asia/Colombo")
WINDOW_MINUTES = 10
WINDOW_SECONDS = WINDOW_MINUTES * 60
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
        try:
            vscode_rows = (
                session.query(VSCodeMinuteWindowRecord)
                .filter(VSCodeMinuteWindowRecord.user_id == user_id)
                .all()
            )
            browser_rows = (
                session.query(BrowserMinuteWindowRecord)
                .filter(BrowserMinuteWindowRecord.user_id == user_id)
                .all()
            )
            os_structured_rows = (
                session.query(OSMinuteWindowRecord)
                .filter(OSMinuteWindowRecord.user_id == user_id)
                .all()
            )
            calendar_structured_rows = (
                session.query(CalendarEventRecord)
                .filter(CalendarEventRecord.user_id == user_id)
                .all()
            )

            os_rows = (
                session.query(OSSignalRecord)
                .filter(OSSignalRecord.event_type == "window_summary")
                .all()
            )
            calendar_rows = (
                session.query(CalendarRecord)
                .filter(CalendarRecord.event_type == "calendar_event")
                .all()
            )
        finally:
            session.close()

        return {
            "vscode": vscode_rows,
            "browser": browser_rows,
            "os_structured": os_structured_rows,
            "calendar_structured": calendar_structured_rows,
            "os_legacy": os_rows,
            "calendar_legacy": calendar_rows,
        }

    def _build_window_summary(self, user_id: str, window_start: datetime, window_end: datetime, rows: dict):
        vscode_rows = self._filter_vscode_rows(rows["vscode"], window_start, window_end)
        browser_rows = self._filter_browser_rows(rows["browser"], window_start, window_end)
        os_structured_rows = self._filter_os_minute_rows(rows["os_structured"], window_start, window_end)
        calendar_structured_rows = self._filter_calendar_event_rows(rows["calendar_structured"], window_start, window_end)

        os_legacy_rows = self._filter_os_rows(rows["os_legacy"], window_start, window_end, user_id)
        calendar_legacy_rows = self._filter_calendar_rows(rows["calendar_legacy"], window_start, window_end)

        if os_structured_rows:
            os_metrics = self._aggregate_os_minute(os_structured_rows)
        else:
            os_metrics = self._aggregate_os(os_legacy_rows)

        browser_metrics = self._aggregate_browser(browser_rows)
        vscode_metrics = self._aggregate_vscode(vscode_rows)

        if calendar_structured_rows:
            calendar_metrics = self._aggregate_calendar_events(calendar_structured_rows, window_start, window_end)
        else:
            calendar_metrics = self._aggregate_calendar(calendar_legacy_rows, window_start, window_end)

        missing_sources = []
        if not os_structured_rows and not os_legacy_rows:
            missing_sources.append("os")
        if not browser_rows:
            missing_sources.append("browser")
        if not vscode_rows:
            missing_sources.append("vscode")
        if not calendar_structured_rows and not calendar_legacy_rows:
            missing_sources.append("calendar")

        data_quality_score = int(round((4 - len(missing_sources)) / 4 * 100))

        focus_score = self._compute_focus_score(
            os_metrics,
            browser_metrics,
            vscode_metrics,
        )

        activity_label = self._compute_activity_label(
            calendar_metrics,
            os_metrics,
            browser_metrics,
            vscode_metrics,
        )

        summary = {
            "user_id": user_id,
            "window_start": _to_colombo_iso(window_start),
            "window_end": _to_colombo_iso(window_end),
            "timezone": "Asia/Colombo",

            **os_metrics,
            **browser_metrics,
            **vscode_metrics,
            **calendar_metrics,

            "focus_score": focus_score,
            "activity_label": activity_label,
            "label_source": "rule_based",

            "data_quality_score": data_quality_score,
            "missing_sources": json.dumps(missing_sources),

            "source": SOURCE_NAME,
            "schema_version": SCHEMA_VERSION,
            "created_at": _to_colombo_iso(datetime.now(COLOMBO_TZ)),
            "updated_at": _to_colombo_iso(datetime.now(COLOMBO_TZ)),
        }

        return summary

    def _filter_vscode_rows(self, rows, window_start: datetime, window_end: datetime):
        filtered = []
        for row in rows:
            start = _parse_iso_datetime(row.window_start)
            end = _parse_iso_datetime(row.window_end)
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end))
        return filtered

    def _filter_browser_rows(self, rows, window_start: datetime, window_end: datetime):
        filtered = []
        for row in rows:
            start = _parse_iso_datetime(row.window_start)
            end = _parse_iso_datetime(row.window_end)
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end))
        return filtered

    def _filter_os_rows(self, rows, window_start: datetime, window_end: datetime, user_id: str):
        filtered = []
        for row in rows:
            data = row.data or {}
            if data.get("user_id") and data.get("user_id") != user_id:
                continue
            start = _parse_iso_datetime(data.get("window_start"))
            end = _parse_iso_datetime(data.get("window_end"))
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end, data))
        return filtered

    def _filter_os_minute_rows(self, rows, window_start: datetime, window_end: datetime):
        filtered = []
        for row in rows:
            start = _parse_iso_datetime(row.window_start)
            end = _parse_iso_datetime(row.window_end)
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end))
        return filtered

    def _filter_calendar_rows(self, rows, window_start: datetime, window_end: datetime):
        filtered = []
        for row in rows:
            data = row.data or {}
            start = _parse_iso_datetime(data.get("start_time"))
            end = _parse_iso_datetime(data.get("end_time"))
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end, data))
        return filtered

    def _filter_calendar_event_rows(self, rows, window_start: datetime, window_end: datetime):
        filtered = []
        for row in rows:
            start = _parse_iso_datetime(row.start_time)
            end = _parse_iso_datetime(row.end_time)
            if not start or not end:
                continue
            if start < window_end and end > window_start:
                filtered.append((row, start, end))
        return filtered

    def _aggregate_os(self, rows):
        os_active_sec = 0
        os_idle_sec = 0
        os_locked_sec = 0
        context_switch_count = 0
        app_durations = Counter()
        category_durations = Counter()
        top_app = None
        dominant_app_category = None

        for _row, _start, _end, data in rows:
            os_active_sec += int(data.get("active_time_sec") or 0)
            os_idle_sec += int(data.get("idle_time_sec") or 0)
            os_locked_sec += int(data.get("locked_time_sec") or 0)
            context_switch_count += int(data.get("context_switch_count") or 0)

            for app, duration in (data.get("active_app_durations_sec") or {}).items():
                try:
                    app_durations[app] += float(duration)
                except (TypeError, ValueError):
                    continue

            for category, duration in (data.get("category_durations_sec") or {}).items():
                try:
                    category_durations[category] += float(duration)
                except (TypeError, ValueError):
                    continue

        if app_durations:
            top_app = app_durations.most_common(1)[0][0]
        if category_durations:
            dominant_app_category = category_durations.most_common(1)[0][0]

        return {
            "os_active_sec": int(os_active_sec),
            "os_idle_sec": int(os_idle_sec),
            "os_locked_sec": int(os_locked_sec),
            "context_switch_count": int(context_switch_count),
            "top_app": top_app,
            "dominant_app_category": dominant_app_category,
        }

    def _aggregate_os_minute(self, rows):
        os_active_sec = 0
        os_idle_sec = 0
        os_locked_sec = 0
        context_switch_count = 0
        top_app = None
        dominant_app_category = None
        app_counter = Counter()
        category_counter = Counter()

        for row, _start, _end in rows:
            os_active_sec += int(row.active_time_sec or 0)
            os_idle_sec += int(row.idle_time_sec or 0)
            os_locked_sec += int(row.locked_time_sec or 0)
            context_switch_count += int(row.context_switch_count or 0)

            if row.top_app:
                app_counter[row.top_app] += int(row.top_app_sec or 1)
            if row.dominant_app_category:
                category_counter[row.dominant_app_category] += int(row.dominant_app_category_sec or 1)

        if app_counter:
            top_app = app_counter.most_common(1)[0][0]
        if category_counter:
            dominant_app_category = category_counter.most_common(1)[0][0]

        return {
            "os_active_sec": int(os_active_sec),
            "os_idle_sec": int(os_idle_sec),
            "os_locked_sec": int(os_locked_sec),
            "context_switch_count": int(context_switch_count),
            "top_app": top_app,
            "dominant_app_category": dominant_app_category,
        }

    def _aggregate_browser(self, rows):
        browser_active_sec = 0
        productive_browser_sec = 0
        neutral_browser_sec = 0
        distracting_browser_sec = 0
        communication_browser_sec = 0
        tab_switch_count = 0
        unique_domains_count = 0
        top_domain = None
        active_tab_category = None

        domain_counter = Counter()
        category_counter = Counter()

        for row, _start, _end in rows:
            browser_active_sec += int(row.browser_active_time_sec or 0)
            productive_browser_sec += int(row.productive_time_sec or 0)
            neutral_browser_sec += int(row.neutral_time_sec or 0)
            distracting_browser_sec += int(row.distracting_time_sec or 0)
            communication_browser_sec += int(row.communication_time_sec or 0)
            tab_switch_count += int(row.tab_switch_count or 0)
            unique_domains_count += int(row.unique_domains_count or 0)

            if row.active_tab_domain:
                domain_counter[row.active_tab_domain] += 1
            if row.active_tab_category:
                category_counter[row.active_tab_category] += 1

        if domain_counter:
            top_domain = domain_counter.most_common(1)[0][0]
        if category_counter:
            active_tab_category = category_counter.most_common(1)[0][0]

        return {
            "browser_active_sec": int(browser_active_sec),
            "productive_browser_sec": int(productive_browser_sec),
            "neutral_browser_sec": int(neutral_browser_sec),
            "distracting_browser_sec": int(distracting_browser_sec),
            "communication_browser_sec": int(communication_browser_sec),
            "tab_switch_count": int(tab_switch_count),
            "unique_domains_count": int(unique_domains_count),
            "top_domain": top_domain,
            "active_tab_category": active_tab_category,
        }

    def _aggregate_vscode(self, rows):
        vscode_foreground_sec = 0
        vscode_active_sec = 0
        vscode_idle_sec = 0
        edit_count = 0
        save_count = 0
        file_switch_count = 0
        terminal_command_count = 0
        debug_run_count = 0
        active_project = None
        active_file_name = None
        active_language = None
        git_branch = None

        project_counter = Counter()
        language_counter = Counter()
        latest_row = None
        latest_end = None

        for row, _start, end in rows:
            vscode_foreground_sec += int(row.vscode_foreground_sec or 0)
            vscode_active_sec += int(row.active_editor_sec or 0)
            vscode_idle_sec += int(row.idle_sec or 0)
            edit_count += int(row.edit_count or 0)
            save_count += int(row.save_count or 0)
            file_switch_count += int(row.file_switch_count or 0)
            terminal_command_count += int(row.terminal_command_count or 0)
            debug_run_count += int(row.debug_run_count or 0)

            if row.workspace_name:
                project_counter[row.workspace_name] += 1
            elif row.project_path:
                project_counter[row.project_path] += 1

            if row.active_language:
                language_counter[row.active_language] += 1

            if latest_end is None or end > latest_end:
                latest_end = end
                latest_row = row

        if project_counter:
            active_project = project_counter.most_common(1)[0][0]
        if language_counter:
            active_language = language_counter.most_common(1)[0][0]

        if latest_row:
            active_file_name = latest_row.active_file_name
            git_branch = latest_row.git_branch

        return {
            "vscode_foreground_sec": int(vscode_foreground_sec),
            "vscode_active_sec": int(vscode_active_sec),
            "vscode_idle_sec": int(vscode_idle_sec),
            "edit_count": int(edit_count),
            "save_count": int(save_count),
            "file_switch_count": int(file_switch_count),
            "terminal_command_count": int(terminal_command_count),
            "debug_run_count": int(debug_run_count),
            "active_project": active_project,
            "active_file_name": active_file_name,
            "active_language": active_language,
            "git_branch": git_branch,
        }

    def _aggregate_calendar(self, rows, window_start: datetime, window_end: datetime):
        calendar_meeting_sec = 0
        meeting_title = None

        for _row, start, end, data in rows:
            overlap = _overlap_seconds(start, end, window_start, window_end)
            if overlap > 0:
                calendar_meeting_sec += overlap
                if not meeting_title:
                    meeting_title = data.get("title") or data.get("summary")

        return {
            "calendar_meeting_sec": int(calendar_meeting_sec),
            "in_meeting": 1 if calendar_meeting_sec > 0 else 0,
            "meeting_title": meeting_title,
        }

    def _aggregate_calendar_events(self, rows, window_start: datetime, window_end: datetime):
        calendar_meeting_sec = 0
        meeting_title = None

        for row, start, end in rows:
            overlap = _overlap_seconds(start, end, window_start, window_end)
            if overlap > 0:
                calendar_meeting_sec += overlap
                if not meeting_title:
                    meeting_title = row.title

        return {
            "calendar_meeting_sec": int(calendar_meeting_sec),
            "in_meeting": 1 if calendar_meeting_sec > 0 else 0,
            "meeting_title": meeting_title,
        }

    def _compute_focus_score(self, os_metrics, browser_metrics, vscode_metrics):
        os_active = os_metrics.get("os_active_sec") or 0
        os_idle = os_metrics.get("os_idle_sec") or 0
        productive = browser_metrics.get("productive_browser_sec") or 0
        distracting = browser_metrics.get("distracting_browser_sec") or 0
        vscode_active = vscode_metrics.get("vscode_active_sec") or 0
        context_switches = os_metrics.get("context_switch_count") or 0
        tab_switches = browser_metrics.get("tab_switch_count") or 0

        score = 50
        score += min(30, int(vscode_active / WINDOW_SECONDS * 30))
        score += min(20, int(productive / WINDOW_SECONDS * 20))
        score += min(20, int(os_active / WINDOW_SECONDS * 20))
        score -= min(30, int(distracting / WINDOW_SECONDS * 30))
        score -= min(20, int(os_idle / WINDOW_SECONDS * 20))
        score -= min(10, int((context_switches + tab_switches) / 20 * 10))

        return max(0, min(100, score))

    def _compute_activity_label(self, calendar_metrics, os_metrics, browser_metrics, vscode_metrics):
        calendar_meeting_sec = calendar_metrics.get("calendar_meeting_sec") or 0
        os_idle = os_metrics.get("os_idle_sec") or 0
        os_active = os_metrics.get("os_active_sec") or 0
        browser_active = browser_metrics.get("browser_active_sec") or 0
        vscode_active = vscode_metrics.get("vscode_active_sec") or 0
        distracting = browser_metrics.get("distracting_browser_sec") or 0
        productive = browser_metrics.get("productive_browser_sec") or 0
        tab_switches = browser_metrics.get("tab_switch_count") or 0
        context_switches = os_metrics.get("context_switch_count") or 0
        file_switches = vscode_metrics.get("file_switch_count") or 0
        edit_count = vscode_metrics.get("edit_count") or 0
        active_language = vscode_metrics.get("active_language") or ""
        active_tab_category = browser_metrics.get("active_tab_category") or ""

        if calendar_meeting_sec > 0:
            return "Meeting"

        if os_idle >= 300 or (os_active + browser_active + vscode_active) < 120:
            return "Idle"

        if vscode_active >= 300 and distracting <= 60:
            return "Focused"

        if productive >= 300 and edit_count <= 2 and active_tab_category == "Focused":
            return "Learning"

        if distracting >= 180:
            return "Distracted"

        if (context_switches + tab_switches + file_switches) >= 15:
            return "Multitasking"

        return "Unknown"
