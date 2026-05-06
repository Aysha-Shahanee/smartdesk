"""
Activity Timeline Index Builder.
Builds a foreground activity timeline from OS minute-window data,
then merges contiguous windows into event-based sessions.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from app.core.database import SessionLocal
from app.models.db_models import (
    ActivityTimelineIndex,
    OSMinuteWindowRecord,
    BrowserMinuteWindowRecord,
    IDEMinuteWindowRecord,
)
from app.repositories.activity_session_summary_repository import ActivityTimelineRepository

logger = logging.getLogger("smartdesk.service.timeline")


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
    return parsed


def _server_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _overlap_seconds(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> float:
    return max(0.0, (min(end_a, end_b) - max(start_a, start_b)).total_seconds())


def _determine_foreground_source(top_app: str | None) -> str:
    normalized = (top_app or "").lower()
    if any(token in normalized for token in ["code", "vscode", "antigravity", "idea", "pycharm"]):
        return "ide"
    if any(token in normalized for token in ["chrome", "msedge", "edge", "firefox", "brave"]):
        return "browser"
    if any(token in normalized for token in ["terminal", "powershell", "cmd", "bash"]):
        return "terminal"
    return "os"


class ActivityTimelineService:
    def __init__(self):
        self.repository = ActivityTimelineRepository()

    def build(self, user_id: str, start_time: str, end_time: str):
        """Build event-based timeline index entries from OS minute windows."""
        self.repository.delete_overlapping(user_id, start_time, end_time)

        os_rows = self._load_os_rows(user_id, start_time, end_time)
        if not os_rows:
            return {"built": 0, "details": []}

        browser_windows = self._load_browser_windows(user_id, start_time, end_time)
        ide_windows = self._load_ide_windows(user_id, start_time, end_time)

        now_iso = _server_timestamp()
        minute_entries = []

        for row in os_rows:
            ws = row.window_start
            we = row.window_end

            os_s = _parse_iso_datetime(ws)
            os_e = _parse_iso_datetime(we)
            if not os_s or not os_e or os_e <= os_s:
                continue

            # Find best overlapping IDE window
            best_ide = None
            max_ide_overlap = 0
            for v in ide_windows:
                v_s = _parse_iso_datetime(v.window_start)
                v_e = _parse_iso_datetime(v.window_end)
                if not v_s or not v_e:
                    continue
                overlap = _overlap_seconds(os_s, os_e, v_s, v_e)
                if overlap > max_ide_overlap:
                    max_ide_overlap = overlap
                    best_ide = v

            has_ide = max_ide_overlap > 0
            ide_workspace = best_ide.workspace_name if best_ide else None

            # Find best overlapping Browser window
            best_browser = None
            max_browser_overlap = 0
            for b in browser_windows:
                b_s = _parse_iso_datetime(b.window_start)
                b_e = _parse_iso_datetime(b.window_end)
                if not b_s or not b_e:
                    continue
                overlap = _overlap_seconds(os_s, os_e, b_s, b_e)
                if overlap > max_browser_overlap:
                    max_browser_overlap = overlap
                    best_browser = b

            has_browser = max_browser_overlap > 0
            browser_domain = best_browser.active_tab_domain if best_browser else None

            foreground_source = _determine_foreground_source(row.top_app)
            duration_sec = int((os_e - os_s).total_seconds())
            active_time_sec = row.active_time_sec or 0

            minute_entries.append({
                "user_id": user_id,
                "window_start": ws,
                "window_end": we,
                "timezone": row.timezone,
                "foreground_source": foreground_source,
                "foreground_app": row.top_app,
                "foreground_window_title": None,
                "foreground_category": row.dominant_app_category,
                "has_os_data": True,
                "has_ide_data": has_ide,
                "has_browser_data": has_browser,
                "ide_workspace": ide_workspace,
                "browser_domain": browser_domain,
                "activity_confidence": min(1.0, active_time_sec / duration_sec) if duration_sec > 0 else 0.0,
                "created_at": now_iso,
                "_window_start_dt": os_s,
                "_window_end_dt": os_e,
                "_active_time_sec": active_time_sec,
                "_duration_sec": duration_sec,
            })

        merged_entries = self._merge_contiguous_entries(minute_entries)
        results = [self.repository.upsert(entry) for entry in merged_entries]

        return {"built": len(results), "details": results}

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 200):
        return self.repository.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)

    def _load_os_rows(self, user_id: str, start_time: str, end_time: str):
        session = SessionLocal()
        try:
            return (
                session.query(OSMinuteWindowRecord)
                .filter(
                    OSMinuteWindowRecord.user_id == user_id,
                    OSMinuteWindowRecord.window_end > start_time,
                    OSMinuteWindowRecord.window_start < end_time,
                )
                .order_by(OSMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _load_browser_windows(self, user_id: str, start_time: str, end_time: str):
        session = SessionLocal()
        try:
            return (
                session.query(BrowserMinuteWindowRecord)
                .filter(
                    BrowserMinuteWindowRecord.user_id == user_id,
                    BrowserMinuteWindowRecord.window_end > start_time,
                    BrowserMinuteWindowRecord.window_start < end_time,
                )
                .order_by(BrowserMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _load_ide_windows(self, user_id: str, start_time: str, end_time: str):
        session = SessionLocal()
        try:
            return (
                session.query(IDEMinuteWindowRecord)
                .filter(
                    IDEMinuteWindowRecord.user_id == user_id,
                    IDEMinuteWindowRecord.window_end > start_time,
                    IDEMinuteWindowRecord.window_start < end_time,
                )
                .order_by(IDEMinuteWindowRecord.window_start)
                .all()
            )
        finally:
            session.close()

    def _merge_contiguous_entries(self, entries: List[Dict]) -> List[Dict]:
        if not entries:
            return []

        merged: List[Dict] = []
        for entry in entries:
            if not merged:
                merged.append(entry)
                continue

            previous = merged[-1]
            if self._can_merge(previous, entry):
                previous["window_end"] = entry["window_end"]
                previous["_window_end_dt"] = entry["_window_end_dt"]
                previous["_active_time_sec"] += entry["_active_time_sec"]
                previous["_duration_sec"] += entry["_duration_sec"]
                previous["has_os_data"] = previous["has_os_data"] or entry["has_os_data"]
                previous["has_ide_data"] = previous["has_ide_data"] or entry["has_ide_data"]
                previous["has_browser_data"] = previous["has_browser_data"] or entry["has_browser_data"]
                previous["activity_confidence"] = min(
                    1.0,
                    previous["_active_time_sec"] / previous["_duration_sec"],
                ) if previous["_duration_sec"] > 0 else 0.0
                continue

            merged.append(entry)

        cleaned_entries = []
        for entry in merged:
            cleaned_entries.append({k: v for k, v in entry.items() if not k.startswith("_")})
        return cleaned_entries

    def _can_merge(self, previous: Dict, current: Dict) -> bool:
        if previous["_window_end_dt"] != current["_window_start_dt"]:
            return False

        keys_to_match = (
            "user_id",
            "timezone",
            "foreground_source",
            "foreground_app",
            "foreground_category",
            "ide_workspace",
            "browser_domain",
            "has_ide_data",
            "has_browser_data",
        )
        return all(previous.get(key) == current.get(key) for key in keys_to_match)
