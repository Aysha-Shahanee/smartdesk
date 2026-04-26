"""
Model 1 Features Module

Builds model-ready 10-minute feature windows for the Focus & Distraction Classifier
from raw SQLite tables.

Why this exists:
Raw signals are source-specific (OS, browser, VS Code, calendar) and not directly
usable for model training. This module creates one unified feature row per user per
fixed 10-minute window in `model1_features_10min`, with a `manual_label` field for
human labeling before supervised training.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


# ===========================
# SQL Schema
# ===========================

CREATE_MODEL1_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model1_features_10min (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default_user',
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    -- OS signal features
    total_active_time_sec REAL DEFAULT 0,
    total_idle_time_sec REAL DEFAULT 0,
    total_locked_time_sec REAL DEFAULT 0,
    idle_ratio REAL DEFAULT 0,
    os_context_switch_count INTEGER DEFAULT 0,
    os_switch_rate REAL DEFAULT 0,
    os_app_count INTEGER DEFAULT 0,
    os_top_app_ratio REAL DEFAULT 0,
    os_browser_time_sec REAL DEFAULT 0,
    os_system_time_sec REAL DEFAULT 0,
    os_other_time_sec REAL DEFAULT 0,

    -- Browser features
    browser_active_time_sec REAL DEFAULT 0,
    browser_idle_time_sec REAL DEFAULT 0,
    browser_productive_time_sec REAL DEFAULT 0,
    browser_neutral_time_sec REAL DEFAULT 0,
    browser_distracting_time_sec REAL DEFAULT 0,
    browser_communication_time_sec REAL DEFAULT 0,
    browser_meeting_time_sec REAL DEFAULT 0,
    browser_development_tool_time_sec REAL DEFAULT 0,
    browser_auth_setup_time_sec REAL DEFAULT 0,
    browser_productive_ratio REAL DEFAULT 0,
    browser_distracting_ratio REAL DEFAULT 0,
    browser_tab_switch_count INTEGER DEFAULT 0,
    browser_unique_domain_count INTEGER DEFAULT 0,

    -- VS Code features
    vscode_total_duration_sec REAL DEFAULT 0,
    vscode_active_seconds REAL DEFAULT 0,
    vscode_idle_seconds REAL DEFAULT 0,
    vscode_edit_count INTEGER DEFAULT 0,
    vscode_save_count INTEGER DEFAULT 0,
    vscode_debug_runs INTEGER DEFAULT 0,
    vscode_terminal_commands INTEGER DEFAULT 0,
    vscode_chars_added INTEGER DEFAULT 0,
    vscode_chars_removed INTEGER DEFAULT 0,
    vscode_unique_file_count INTEGER DEFAULT 0,
    vscode_unique_language_count INTEGER DEFAULT 0,
    vscode_edit_density REAL DEFAULT 0,
    vscode_save_density REAL DEFAULT 0,

    -- Calendar features
    calendar_meeting_time_sec REAL DEFAULT 0,
    calendar_meeting_count INTEGER DEFAULT 0,
    is_meeting_window INTEGER DEFAULT 0,

    -- Cross-source derived features
    ide_ratio REAL DEFAULT 0,
    browser_ratio REAL DEFAULT 0,
    multitask_score REAL DEFAULT 0,
    distraction_score REAL DEFAULT 0,

    -- Manual labeling (for future)
    manual_label TEXT DEFAULT NULL,

    -- Data quality helpers
    has_os_signal INTEGER DEFAULT 0,
    has_browser_signal INTEGER DEFAULT 0,
    has_vscode_signal INTEGER DEFAULT 0,
    has_calendar_signal INTEGER DEFAULT 0,
    has_any_signal INTEGER DEFAULT 0,
    data_quality_score REAL DEFAULT 0,
    source_refs_json TEXT DEFAULT NULL,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, window_start)
);
"""


SOURCE_TABLE_CANDIDATES = {
    "os": ["os_signals"],
    "browser": ["browser_signals", "browser"],
    # Prefer clean one-row-per-session sources first; raw snapshot table is fallback only.
    "vscode": [
        "vscode_sessions",
        "vscode_clean_sessions",
        "vscode_final_sessions",
        "vscode_file_sessions",
        "vscode_signals",
        "vscode",
    ],
    "calendar": ["calendar_signals", "calendar"],
}

MAX_VSCODE_SESSION_SECONDS = 6 * 60 * 60


# ===========================
# Helper Functions
# ===========================

def parse_iso_datetime(value: Any) -> Optional[datetime]:
    """Parse datetime safely and normalize to timezone-aware UTC."""
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt


def floor_to_10min(dt: datetime) -> datetime:
    """Round datetime down to the nearest 10-minute boundary."""
    return dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)


def get_window_boundaries(dt: datetime) -> Tuple[datetime, datetime]:
    """Return [window_start, window_end) datetimes for a given point in time."""
    start = floor_to_10min(dt)
    end = start + timedelta(minutes=10)
    return start, end


def overlap_duration(event_start: datetime, event_end: datetime, window_start: datetime, window_end: datetime) -> float:
    """Return overlap in seconds between [event_start, event_end) and [window_start, window_end)."""
    overlap_start = max(event_start, window_start)
    overlap_end = min(event_end, window_end)
    if overlap_start >= overlap_end:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


def windows_overlap(record_start: datetime, record_end: datetime, window_start: datetime, window_end: datetime) -> bool:
    """Window overlap rule: record_start < window_end AND record_end > window_start."""
    return record_start < window_end and record_end > window_start


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide safely, avoiding division by zero."""
    return numerator / denominator if denominator > 0 else default


def to_utc_window_string(dt: datetime) -> str:
    """Canonical UTC window format: YYYY-MM-DDTHH:MM:SS+00:00."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def parse_json_dict(raw: Any) -> Dict[str, Any]:
    """Safely parse JSON payload column to dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_hostname(url: str) -> str:
    """Extract hostname from URL using simple split fallback."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def normalize_browser_category(category: Any) -> str:
    """Normalize raw browser categories into the model's canonical set."""
    raw = str(category or "unknown").strip().lower()
    mapping = {
        "focused": "productive",
        "productive": "productive",
        "work": "productive",
        "learning": "productive",
        "neutral": "neutral",
        "distracting": "distracting",
        "distraction": "distracting",
        "entertainment": "distracting",
        "social": "distracting",
        "communication": "communication",
        "meeting": "meeting",
        "development_tool": "development_tool",
        "auth_setup": "auth_setup",
        "unknown": "unknown",
        "unmatched": "unknown",
    }
    return mapping.get(raw, "unknown")


# ===========================
# Database Layer
# ===========================

def create_table(conn: sqlite3.Connection) -> None:
    """Create the model1_features_10min table."""
    conn.execute(CREATE_MODEL1_TABLE_SQL)
    _ensure_optional_columns(conn)
    conn.commit()
    print("[ok] table model1_features_10min ready")


def _ensure_optional_columns(conn: sqlite3.Connection) -> None:
    """Add newer columns for existing tables created before schema updates."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(model1_features_10min)")
    existing = {row[1] for row in cur.fetchall()}

    to_add = {
        "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
        "has_os_signal": "INTEGER DEFAULT 0",
        "has_browser_signal": "INTEGER DEFAULT 0",
        "has_vscode_signal": "INTEGER DEFAULT 0",
        "has_calendar_signal": "INTEGER DEFAULT 0",
        "has_any_signal": "INTEGER DEFAULT 0",
        "os_coverage_sec": "REAL DEFAULT 0",
        "browser_coverage_sec": "REAL DEFAULT 0",
        "vscode_coverage_sec": "REAL DEFAULT 0",
        "calendar_coverage_sec": "REAL DEFAULT 0",
        "data_quality_score": "REAL DEFAULT 0",
        "is_training_eligible": "INTEGER DEFAULT 0",
        "quality_warning": "TEXT DEFAULT NULL",
        "source_refs_json": "TEXT DEFAULT NULL",
    }

    for column, col_type in to_add.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE model1_features_10min ADD COLUMN {column} {col_type}")


def resolve_source_tables(conn: sqlite3.Connection) -> Dict[str, Optional[str]]:
    """Resolve actual table names present in DB for each source."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    available = {row[0] for row in cur.fetchall()}

    resolved: Dict[str, Optional[str]] = {}
    for source, candidates in SOURCE_TABLE_CANDIDATES.items():
        resolved[source] = next((c for c in candidates if c in available), None)

    return resolved


def load_rows(conn: sqlite3.Connection, table_name: Optional[str], source_name: str) -> List[Tuple[Any, Any]]:
    """Load source rows and normalize both JSON and structured table formats."""
    if not table_name:
        return []

    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [row[1] for row in cur.fetchall()]
    colset = set(cols)

    # Case A: legacy JSON schema with timestamp + data payload.
    if "timestamp" in colset and "data" in colset:
        cur.execute(f"SELECT timestamp, data FROM {table_name}")
        return cur.fetchall()

    # Case B: structured clean VS Code session table.
    if source_name == "vscode" and "event_id" in colset and "start_time" in colset:
        where_parts: List[str] = []
        has_validity_flag = False

        if "is_final" in colset:
            where_parts.append("COALESCE(is_final, 0) = 1")
            has_validity_flag = True
        if "status" in colset:
            where_parts.append("LOWER(COALESCE(status, '')) IN ('completed', 'closed', 'final', 'done')")
            has_validity_flag = True
        if "is_closed" in colset:
            where_parts.append("COALESCE(is_closed, 0) = 1")
            has_validity_flag = True
        if "completed" in colset:
            where_parts.append("COALESCE(completed, 0) = 1")
            has_validity_flag = True
        if not has_validity_flag and "end_time" in colset:
            # If no explicit status/final column exists, only use ended sessions.
            where_parts.append("end_time IS NOT NULL")

        select_cols = [
            c
            for c in [
                "event_id",
                "start_time",
                "end_time",
                "duration_sec",
                "duration_seconds",
                "active_sec",
                "active_seconds",
                "idle_sec",
                "idle_seconds",
                "edit_count",
                "save_count",
                "debug_run_count",
                "debug_runs",
                "terminal_command_count",
                "terminal_commands",
                "approx_chars_added",
                "chars_added",
                "approx_chars_removed",
                "chars_removed",
                "file_path",
                "language",
                "timestamp",
                "updated_at",
                "created_at",
                "is_final",
                "status",
                "is_closed",
                "completed",
            ]
            if c in colset
        ]

        where_clause = f" WHERE {' OR '.join(where_parts)}" if where_parts else ""
        cur.execute(f"SELECT {', '.join(select_cols)} FROM {table_name}{where_clause}")
        rows = cur.fetchall()

        idx = {name: i for i, name in enumerate(select_cols)}

        def _get(r: Tuple[Any, ...], key: str) -> Any:
            if key not in idx:
                return None
            return r[idx[key]]

        def _num(r: Tuple[Any, ...], *keys: str) -> float:
            for k in keys:
                v = _get(r, k)
                if v is None:
                    continue
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
            return 0.0

        # Deduplicate by event_id: keep row with latest end_time (then latest updated_at/created_at).
        dedup: Dict[str, Tuple[Any, ...]] = {}
        for r in rows:
            event_id = str(_get(r, "event_id") or "").strip()
            if not event_id:
                continue

            existing = dedup.get(event_id)
            if existing is None:
                dedup[event_id] = r
                continue

            end_cur = parse_iso_datetime(_get(r, "end_time"))
            end_old = parse_iso_datetime(_get(existing, "end_time"))
            upd_cur = parse_iso_datetime(_get(r, "updated_at") or _get(r, "created_at") or _get(r, "start_time"))
            upd_old = parse_iso_datetime(_get(existing, "updated_at") or _get(existing, "created_at") or _get(existing, "start_time"))

            if end_old is None and end_cur is not None:
                dedup[event_id] = r
            elif end_old is not None and end_cur is not None and end_cur > end_old:
                dedup[event_id] = r
            elif (end_old == end_cur) and (upd_old is None or (upd_cur is not None and upd_cur > upd_old)):
                dedup[event_id] = r

        normalized: List[Tuple[Any, Any]] = []
        for event_id, r in dedup.items():
            start = parse_iso_datetime(_get(r, "start_time"))
            end = parse_iso_datetime(_get(r, "end_time"))
            if start is None:
                continue

            # Do not treat open/current sessions as final work.
            if end is None:
                continue

            payload = {
                "event_id": event_id,
                "start_time": _get(r, "start_time"),
                "end_time": _get(r, "end_time"),
                "duration_seconds": _num(r, "duration_seconds", "duration_sec"),
                "active_seconds": _num(r, "active_seconds", "active_sec"),
                "idle_seconds": _num(r, "idle_seconds", "idle_sec"),
                "edit_count": _num(r, "edit_count"),
                "save_count": _num(r, "save_count"),
                "debug_runs": _num(r, "debug_runs", "debug_run_count"),
                "terminal_commands": _num(r, "terminal_commands", "terminal_command_count"),
                "chars_added": _num(r, "chars_added", "approx_chars_added"),
                "chars_removed": _num(r, "chars_removed", "approx_chars_removed"),
                "file_path": _get(r, "file_path"),
                "language": _get(r, "language"),
            }

            normalized.append((_get(r, "end_time") or _get(r, "start_time"), payload))

        return normalized

    # Generic fallback for unknown schema: attempt timestamp-like and JSON-like columns.
    ts_col = next((c for c in ["timestamp", "created_at", "start_time"] if c in colset), None)
    data_col = next((c for c in ["data", "payload"] if c in colset), None)
    if ts_col and data_col:
        cur.execute(f"SELECT {ts_col}, {data_col} FROM {table_name}")
        return cur.fetchall()

    return []


# ===========================
# Window Discovery
# ===========================

def extract_os_interval(ts_raw: Any, data: Dict[str, Any]) -> Optional[Tuple[datetime, datetime]]:
    """OS uses inner JSON window_start/window_end when available."""
    record_start = parse_iso_datetime(data.get("window_start"))
    record_end = parse_iso_datetime(data.get("window_end"))

    if record_start is None:
        record_start = parse_iso_datetime(ts_raw)
    if record_end is None:
        record_end = record_start

    if record_start is None or record_end is None:
        return None

    if record_end < record_start:
        record_end = record_start

    return record_start, record_end


def extract_browser_intervals(_ts_raw: Any, data: Dict[str, Any]) -> List[Tuple[datetime, datetime]]:
    """Browser intervals come from each history entry timestamp/startTime -> endTime."""
    intervals: List[Tuple[datetime, datetime]] = []
    history = data.get("history", [])
    if not isinstance(history, list):
        return intervals

    for entry in history:
        if not isinstance(entry, dict):
            continue
        start = parse_iso_datetime(entry.get("timestamp") or entry.get("startTime"))
        end = parse_iso_datetime(entry.get("endTime"))
        if start is None:
            continue
        if end is None or end < start:
            end = start
        intervals.append((start, end))

    return intervals


def extract_vscode_interval(ts_raw: Any, data: Dict[str, Any]) -> Optional[Tuple[datetime, datetime]]:
    """VS Code interval: best effort from payload, then timestamp + duration, then timestamp."""
    start = parse_iso_datetime(data.get("window_start") or data.get("start_time") or data.get("timestamp") or ts_raw)
    if start is None:
        return None

    end = parse_iso_datetime(data.get("window_end") or data.get("end_time"))
    if end is None:
        duration = data.get("duration_seconds") or data.get("duration_sec") or 0
        try:
            end = start + timedelta(seconds=float(duration))
        except (TypeError, ValueError):
            end = start

    if end < start:
        end = start

    # Guard against migrated/raw cumulative artifacts that can create fake hundreds of windows.
    event_duration = max((end - start).total_seconds(), 0.0)
    payload_duration = 0.0
    try:
        payload_duration = float(data.get("duration_seconds") or data.get("duration_sec") or 0)
    except (TypeError, ValueError):
        payload_duration = 0.0

    behavior_duration = 0.0
    try:
        behavior_duration = float(data.get("active_seconds", 0) or 0) + float(data.get("idle_seconds", 0) or 0)
    except (TypeError, ValueError):
        behavior_duration = 0.0

    trusted_duration = max(payload_duration, behavior_duration)
    if trusted_duration > 0 and event_duration > max(trusted_duration * 3.0, 3600.0):
        end = start + timedelta(seconds=trusted_duration)

    # Final sanity check: skip implausibly long single-file sessions.
    # This protects window discovery from stale cumulative sessions persisted as one row.
    event_duration = max((end - start).total_seconds(), 0.0)
    if event_duration > MAX_VSCODE_SESSION_SECONDS:
        if 0 < payload_duration <= MAX_VSCODE_SESSION_SECONDS:
            end = start + timedelta(seconds=payload_duration)
        elif 0 < behavior_duration <= MAX_VSCODE_SESSION_SECONDS:
            end = start + timedelta(seconds=behavior_duration)
        else:
            return None

    return start, end


def extract_calendar_interval(_ts_raw: Any, data: Dict[str, Any]) -> Optional[Tuple[datetime, datetime]]:
    """Calendar interval from event start/end in data payload."""
    start = parse_iso_datetime(data.get("start_time") or data.get("start"))
    end = parse_iso_datetime(data.get("end_time") or data.get("end"))

    if start is None:
        return None
    if end is None or end < start:
        end = start

    return start, end


def windows_for_interval(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    """Return all 10-min windows overlapped by an interval."""
    win_list: List[Tuple[datetime, datetime]] = []
    cursor = floor_to_10min(start)
    last = floor_to_10min(end)

    while cursor <= last:
        win_start = cursor
        win_end = cursor + timedelta(minutes=10)
        if windows_overlap(start, end, win_start, win_end):
            win_list.append((win_start, win_end))
        cursor += timedelta(minutes=10)

    return win_list


def get_windows(source_rows: Dict[str, List[Tuple[Any, Any]]]) -> List[Tuple[datetime, datetime]]:
    """Find all unique 10-minute windows across all sources using Python datetime parsing."""
    windows = set()

    # OS
    for ts_raw, data_raw in source_rows["os"]:
        data = parse_json_dict(data_raw)
        interval = extract_os_interval(ts_raw, data)
        if not interval:
            continue
        for w in windows_for_interval(interval[0], interval[1]):
            windows.add(w)

    # Browser
    for ts_raw, data_raw in source_rows["browser"]:
        data = parse_json_dict(data_raw)
        for interval in extract_browser_intervals(ts_raw, data):
            for w in windows_for_interval(interval[0], interval[1]):
                windows.add(w)

    # VS Code
    for ts_raw, data_raw in source_rows["vscode"]:
        data = parse_json_dict(data_raw)
        interval = extract_vscode_interval(ts_raw, data)
        if not interval:
            continue
        for w in windows_for_interval(interval[0], interval[1]):
            windows.add(w)

    # Calendar
    for ts_raw, data_raw in source_rows["calendar"]:
        data = parse_json_dict(data_raw)
        interval = extract_calendar_interval(ts_raw, data)
        if not interval:
            continue
        for w in windows_for_interval(interval[0], interval[1]):
            windows.add(w)

    return sorted(windows)


# ===========================
# Aggregation Functions
# ===========================

def aggregate_os(rows: List[Tuple[Any, Any]], window_start: datetime, window_end: datetime) -> Tuple[Dict[str, Any], int, List[str]]:
    """Aggregate OS features using JSON window_start/window_end overlap matching."""
    matched_items: List[Tuple[Dict[str, Any], float]] = []
    sample_ranges: List[str] = []

    for ts_raw, data_raw in rows:
        data = parse_json_dict(data_raw)
        interval = extract_os_interval(ts_raw, data)
        if not interval:
            continue

        if windows_overlap(interval[0], interval[1], window_start, window_end):
            overlap_sec = overlap_duration(interval[0], interval[1], window_start, window_end)
            record_duration = max((interval[1] - interval[0]).total_seconds(), 1.0)
            overlap_ratio = safe_divide(overlap_sec, record_duration)
            if overlap_sec <= 0:
                continue
            matched_items.append((data, overlap_ratio))
            if len(sample_ranges) < 3:
                sample_ranges.append(f"{interval[0].isoformat()} -> {interval[1].isoformat()}")

    if not matched_items:
        return {
            "total_active_time_sec": 0,
            "total_idle_time_sec": 0,
            "total_locked_time_sec": 0,
            "idle_ratio": 0,
            "os_context_switch_count": 0,
            "os_switch_rate": 0,
            "os_app_count": 0,
            "os_top_app_ratio": 0,
            "os_browser_time_sec": 0,
            "os_system_time_sec": 0,
            "os_other_time_sec": 0,
        }, 0, sample_ranges

    total_active = 0.0
    total_idle = 0.0
    total_locked = 0.0
    total_switches = 0
    app_durations: Dict[str, float] = {}
    category_durations: Dict[str, float] = {}

    for data, ratio in matched_items:
        total_active += float(data.get("active_time_sec", 0) or 0) * ratio
        total_idle += float(data.get("idle_time_sec", 0) or 0) * ratio
        total_locked += float(data.get("locked_time_sec", 0) or 0) * ratio
        total_switches += int(round(float(data.get("context_switch_count", 0) or 0) * ratio))

        app_map = data.get("active_app_durations_sec", {})
        if isinstance(app_map, dict):
            for app, duration in app_map.items():
                try:
                    app_durations[str(app)] = app_durations.get(str(app), 0.0) + float(duration or 0) * ratio
                except (TypeError, ValueError):
                    continue

        cat_map = data.get("category_durations_sec", {})
        if isinstance(cat_map, dict):
            for cat, duration in cat_map.items():
                try:
                    category_durations[str(cat)] = category_durations.get(str(cat), 0.0) + float(duration or 0) * ratio
                except (TypeError, ValueError):
                    continue

    total_time = total_active + total_idle + total_locked
    idle_ratio = safe_divide(total_idle, max(total_time, 1))
    os_switch_rate = safe_divide(float(total_switches), max(total_active, 1))

    os_app_count = len(app_durations)
    top_app_time = max(app_durations.values()) if app_durations else 0.0
    os_top_app_ratio = safe_divide(top_app_time, max(total_active, 1))

    os_browser_time = float(category_durations.get("browser", 0.0))
    os_system_time = float(category_durations.get("system", 0.0))
    os_other_time = max(total_active - os_browser_time - os_system_time, 0.0)

    return {
        "total_active_time_sec": total_active,
        "total_idle_time_sec": total_idle,
        "total_locked_time_sec": total_locked,
        "idle_ratio": idle_ratio,
        "os_context_switch_count": total_switches,
        "os_switch_rate": os_switch_rate,
        "os_app_count": os_app_count,
        "os_top_app_ratio": os_top_app_ratio,
        "os_browser_time_sec": os_browser_time,
        "os_system_time_sec": os_system_time,
        "os_other_time_sec": os_other_time,
    }, len(matched_items), sample_ranges


def aggregate_browser(rows: List[Tuple[Any, Any]], window_start: datetime, window_end: datetime) -> Tuple[Dict[str, Any], int, List[str]]:
    """Aggregate browser features using per-entry interval overlap within each sync payload."""
    category_times = {
        "productive": 0.0,
        "neutral": 0.0,
        "distracting": 0.0,
        "communication": 0.0,
        "meeting": 0.0,
        "development_tool": 0.0,
        "auth_setup": 0.0,
        "unknown": 0.0,
    }

    unique_domains = set()
    tab_switch_count = 0
    matched_entry_count = 0
    sample_ranges: List[str] = []

    for ts_raw, data_raw in rows:
        data = parse_json_dict(data_raw)
        history = data.get("history", [])
        if not isinstance(history, list):
            continue

        payload_matched_entries = 0
        for entry in history:
            if not isinstance(entry, dict):
                continue

            start = parse_iso_datetime(entry.get("timestamp") or entry.get("startTime"))
            end = parse_iso_datetime(entry.get("endTime"))
            if start is None:
                continue
            if end is None or end < start:
                end = start

            if not windows_overlap(start, end, window_start, window_end):
                continue

            payload_matched_entries += 1
            matched_entry_count += 1

            if len(sample_ranges) < 3:
                sample_ranges.append(f"{start.isoformat()} -> {end.isoformat()}")

            overlap_sec = overlap_duration(start, end, window_start, window_end)

            category = normalize_browser_category(entry.get("category", "unknown"))
            category_times[category] += overlap_sec

            domain = get_hostname(str(entry.get("url", "")))
            if domain:
                unique_domains.add(domain)

        if payload_matched_entries > 0:
            tab_switch_count += max(payload_matched_entries - 1, 0)

    total_browser_time = sum(category_times.values())
    productive_ratio = safe_divide(category_times["productive"], max(total_browser_time, 1))
    distracting_ratio = safe_divide(category_times["distracting"], max(total_browser_time, 1))

    return {
        "browser_active_time_sec": total_browser_time,
        "browser_idle_time_sec": 0.0,
        "browser_productive_time_sec": category_times["productive"],
        "browser_neutral_time_sec": category_times["neutral"],
        "browser_distracting_time_sec": category_times["distracting"],
        "browser_communication_time_sec": category_times["communication"],
        "browser_meeting_time_sec": category_times["meeting"],
        "browser_development_tool_time_sec": category_times["development_tool"],
        "browser_auth_setup_time_sec": category_times["auth_setup"],
        "browser_productive_ratio": productive_ratio,
        "browser_distracting_ratio": distracting_ratio,
        "browser_tab_switch_count": tab_switch_count,
        "browser_unique_domain_count": len(unique_domains),
    }, matched_entry_count, sample_ranges


def aggregate_vscode(rows: List[Tuple[Any, Any]], window_start: datetime, window_end: datetime) -> Tuple[Dict[str, Any], int, List[str]]:
    """Aggregate VS Code features with Python overlap filtering."""
    total_duration = 0.0
    active_seconds = 0.0
    idle_seconds = 0.0
    edit_count = 0
    save_count = 0
    debug_runs = 0
    terminal_commands = 0
    chars_added = 0
    chars_removed = 0
    unique_files = set()
    unique_languages = set()

    matched_rows = 0
    sample_ranges: List[str] = []

    for ts_raw, data_raw in rows:
        data = parse_json_dict(data_raw)
        interval = extract_vscode_interval(ts_raw, data)
        if not interval:
            continue

        if not windows_overlap(interval[0], interval[1], window_start, window_end):
            continue

        matched_rows += 1
        if len(sample_ranges) < 3:
            sample_ranges.append(f"{interval[0].isoformat()} -> {interval[1].isoformat()}")

        overlap_sec = overlap_duration(interval[0], interval[1], window_start, window_end)
        event_duration = max((interval[1] - interval[0]).total_seconds(), 1.0)
        overlap_ratio = safe_divide(overlap_sec, event_duration)

        total_duration += overlap_sec
        active_seconds += float(data.get("active_seconds", 0) or 0) * overlap_ratio
        idle_seconds += float(data.get("idle_seconds", 0) or 0) * overlap_ratio
        edit_count += int(round(float(data.get("edit_count", 0) or 0) * overlap_ratio))
        save_count += int(round(float(data.get("save_count", 0) or 0) * overlap_ratio))
        debug_runs += int(round(float(data.get("debug_runs", 0) or 0) * overlap_ratio))
        terminal_commands += int(round(float(data.get("terminal_commands", 0) or 0) * overlap_ratio))
        chars_added += int(round(float(data.get("chars_added", 0) or 0) * overlap_ratio))
        chars_removed += int(round(float(data.get("chars_removed", 0) or 0) * overlap_ratio))

        file_path = data.get("file_path")
        language = data.get("language")
        if file_path:
            unique_files.add(str(file_path))
        if language:
            unique_languages.add(str(language))

    # A fixed window is 600s. Cap to avoid spillover from malformed overlapping logs.
    total_duration = min(total_duration, 600.0)
    active_seconds = min(active_seconds, 600.0)
    idle_seconds = min(idle_seconds, 600.0)

    # Keep behavior components physically consistent with overlapped duration.
    total_behavior = active_seconds + idle_seconds
    if total_duration > 0 and total_behavior > total_duration:
        scale = safe_divide(total_duration, total_behavior, default=1.0)
        active_seconds *= scale
        idle_seconds *= scale

    edit_density = safe_divide(edit_count, max(active_seconds, 1))
    save_density = safe_divide(save_count, max(active_seconds, 1))

    return {
        "vscode_total_duration_sec": total_duration,
        "vscode_active_seconds": active_seconds,
        "vscode_idle_seconds": idle_seconds,
        "vscode_edit_count": edit_count,
        "vscode_save_count": save_count,
        "vscode_debug_runs": debug_runs,
        "vscode_terminal_commands": terminal_commands,
        "vscode_chars_added": chars_added,
        "vscode_chars_removed": chars_removed,
        "vscode_unique_file_count": len(unique_files),
        "vscode_unique_language_count": len(unique_languages),
        "vscode_edit_density": edit_density,
        "vscode_save_density": save_density,
    }, matched_rows, sample_ranges


def aggregate_calendar(rows: List[Tuple[Any, Any]], window_start: datetime, window_end: datetime) -> Tuple[Dict[str, Any], int, List[str]]:
    """Aggregate calendar overlap duration and meeting count per window."""
    meeting_time = 0.0
    meeting_count = 0
    matched_rows = 0
    sample_ranges: List[str] = []

    for ts_raw, data_raw in rows:
        data = parse_json_dict(data_raw)
        interval = extract_calendar_interval(ts_raw, data)
        if not interval:
            continue

        if not windows_overlap(interval[0], interval[1], window_start, window_end):
            continue

        matched_rows += 1
        if len(sample_ranges) < 3:
            sample_ranges.append(f"{interval[0].isoformat()} -> {interval[1].isoformat()}")

        overlap_sec = overlap_duration(interval[0], interval[1], window_start, window_end)
        if overlap_sec > 0:
            meeting_time += overlap_sec
            meeting_count += 1

    return {
        "calendar_meeting_time_sec": meeting_time,
        "calendar_meeting_count": meeting_count,
        "is_meeting_window": 1 if meeting_time > 0 else 0,
    }, matched_rows, sample_ranges


# ===========================
# Derived Features
# ===========================

def compute_features(os_features: Dict[str, Any], browser_features: Dict[str, Any], vscode_features: Dict[str, Any], calendar_features: Dict[str, Any]) -> Dict[str, Any]:
    """Compute cross-source derived features for model input."""
    total_active = float(os_features.get("total_active_time_sec", 0) or 0)
    vscode_active = float(vscode_features.get("vscode_active_seconds", 0) or 0)
    browser_active = float(browser_features.get("browser_active_time_sec", 0) or 0)

    denominator = total_active if total_active > 0 else 600.0
    ide_ratio = min(safe_divide(vscode_active, denominator), 1.0)
    browser_ratio = min(safe_divide(browser_active, denominator), 1.0)

    multitask_score = float(os_features.get("os_context_switch_count", 0) or 0) + float(
        browser_features.get("browser_tab_switch_count", 0) or 0
    )

    distraction_score = (
        float(browser_features.get("browser_distracting_ratio", 0) or 0)
        + float(os_features.get("idle_ratio", 0) or 0)
        + float(os_features.get("os_switch_rate", 0) or 0)
    )

    return {
        "ide_ratio": ide_ratio,
        "browser_ratio": browser_ratio,
        "multitask_score": multitask_score,
        "distraction_score": distraction_score,
    }


def compute_data_quality_flags(
    os_count: int,
    browser_count: int,
    vscode_count: int,
    calendar_count: int,
    os_features: Dict[str, Any],
    browser_features: Dict[str, Any],
    vscode_features: Dict[str, Any],
    calendar_features: Dict[str, Any],
) -> Dict[str, Any]:
    """Simple source-presence flags and data quality score."""
    os_cov = min(
        float(os_features.get("total_active_time_sec", 0) or 0)
        + float(os_features.get("total_idle_time_sec", 0) or 0)
        + float(os_features.get("total_locked_time_sec", 0) or 0),
        600.0,
    )
    browser_cov = min(float(browser_features.get("browser_active_time_sec", 0) or 0), 600.0)
    vscode_cov = min(float(vscode_features.get("vscode_total_duration_sec", 0) or 0), 600.0)
    calendar_cov = min(float(calendar_features.get("calendar_meeting_time_sec", 0) or 0), 600.0)

    has_os = 1 if os_cov > 0 else 0
    # Only flag browser signal when there is real overlap contribution.
    has_browser = 1 if (browser_cov > 0 and float(browser_features.get("browser_active_time_sec", 0) or 0) > 0) else 0
    has_vscode = 1 if (vscode_cov > 0 and vscode_count > 0) else 0
    has_calendar = 1 if calendar_cov > 0 else 0
    has_any = 1 if (has_os or has_browser or has_vscode or has_calendar) else 0

    # Coverage-driven quality score in [0, 1].
    quality = min((os_cov + browser_cov + vscode_cov + calendar_cov) / (4.0 * 600.0), 1.0)

    vscode_has_evidence = (
        float(vscode_features.get("vscode_active_seconds", 0) or 0) >= 30
        or int(vscode_features.get("vscode_edit_count", 0) or 0) > 0
        or int(vscode_features.get("vscode_save_count", 0) or 0) > 0
        or int(vscode_features.get("vscode_terminal_commands", 0) or 0) > 0
        or int(vscode_features.get("vscode_chars_added", 0) or 0) > 0
        or int(vscode_features.get("vscode_chars_removed", 0) or 0) > 0
    )

    is_vscode_only = (has_os == 0 and has_browser == 0 and has_calendar == 0 and has_vscode == 1)
    low_evidence_vscode_only = is_vscode_only and (not vscode_has_evidence)

    is_training_eligible = 1 if (
        has_os
        or has_browser
        or vscode_has_evidence
    ) else 0

    if low_evidence_vscode_only:
        is_training_eligible = 0

    quality_warning: Optional[str] = None
    if not has_any:
        quality_warning = "no_signal"
    elif low_evidence_vscode_only:
        quality_warning = "low_evidence_vscode_only"
    elif not is_training_eligible:
        quality_warning = "low_evidence"

    return {
        "has_os_signal": has_os,
        "has_browser_signal": has_browser,
        "has_vscode_signal": has_vscode,
        "has_calendar_signal": has_calendar,
        "has_any_signal": has_any,
        "os_coverage_sec": os_cov,
        "browser_coverage_sec": browser_cov,
        "vscode_coverage_sec": vscode_cov,
        "calendar_coverage_sec": calendar_cov,
        "data_quality_score": quality,
        "is_training_eligible": is_training_eligible,
        "quality_warning": quality_warning,
    }


# ===========================
# Insert Logic
# ===========================

def insert_row(conn: sqlite3.Connection, user_id: str, window_start: datetime, window_end: datetime, all_features: Dict[str, Any]) -> None:
    """Upsert one feature row for a 10-minute window without overwriting manual_label."""
    feature_columns = [
        "total_active_time_sec",
        "total_idle_time_sec",
        "total_locked_time_sec",
        "idle_ratio",
        "os_context_switch_count",
        "os_switch_rate",
        "os_app_count",
        "os_top_app_ratio",
        "os_browser_time_sec",
        "os_system_time_sec",
        "os_other_time_sec",
        "browser_active_time_sec",
        "browser_idle_time_sec",
        "browser_productive_time_sec",
        "browser_neutral_time_sec",
        "browser_distracting_time_sec",
        "browser_communication_time_sec",
        "browser_meeting_time_sec",
        "browser_development_tool_time_sec",
        "browser_auth_setup_time_sec",
        "browser_productive_ratio",
        "browser_distracting_ratio",
        "browser_tab_switch_count",
        "browser_unique_domain_count",
        "vscode_total_duration_sec",
        "vscode_active_seconds",
        "vscode_idle_seconds",
        "vscode_edit_count",
        "vscode_save_count",
        "vscode_debug_runs",
        "vscode_terminal_commands",
        "vscode_chars_added",
        "vscode_chars_removed",
        "vscode_unique_file_count",
        "vscode_unique_language_count",
        "vscode_edit_density",
        "vscode_save_density",
        "calendar_meeting_time_sec",
        "calendar_meeting_count",
        "is_meeting_window",
        "ide_ratio",
        "browser_ratio",
        "multitask_score",
        "distraction_score",
        "has_os_signal",
        "has_browser_signal",
        "has_vscode_signal",
        "has_calendar_signal",
        "has_any_signal",
        "os_coverage_sec",
        "browser_coverage_sec",
        "vscode_coverage_sec",
        "calendar_coverage_sec",
        "data_quality_score",
        "is_training_eligible",
        "quality_warning",
        "source_refs_json",
    ]

    values = [user_id, to_utc_window_string(window_start), to_utc_window_string(window_end)]
    values.extend(all_features.get(col, 0) for col in feature_columns)

    cols_str = "user_id, window_start, window_end, " + ", ".join(feature_columns)
    placeholders = ", ".join(["?"] * len(values))

    update_assignments = ", ".join([f"{col}=excluded.{col}" for col in feature_columns])
    sql = (
        f"INSERT INTO model1_features_10min ({cols_str}) VALUES ({placeholders}) "
        f"ON CONFLICT(user_id, window_start) DO UPDATE SET {update_assignments}, updated_at=CURRENT_TIMESTAMP"
    )
    conn.execute(sql, values)


def warn_on_window_anomalies(window_start: datetime, all_features: Dict[str, Any]) -> None:
    """Print non-fatal data-quality warnings for suspicious window values."""
    ws = to_utc_window_string(window_start)

    vs_total = float(all_features.get("vscode_total_duration_sec", 0) or 0)
    vs_active = float(all_features.get("vscode_active_seconds", 0) or 0)
    vs_idle = float(all_features.get("vscode_idle_seconds", 0) or 0)
    os_sum = (
        float(all_features.get("total_active_time_sec", 0) or 0)
        + float(all_features.get("total_idle_time_sec", 0) or 0)
        + float(all_features.get("total_locked_time_sec", 0) or 0)
    )
    ide_ratio = float(all_features.get("ide_ratio", 0) or 0)
    browser_ratio = float(all_features.get("browser_ratio", 0) or 0)

    if vs_total > 600:
        print(f"[warn] {ws} vscode_total_duration_sec > 600 ({vs_total:.2f})")
    if vs_active > 600:
        print(f"[warn] {ws} vscode_active_seconds > 600 ({vs_active:.2f})")
    if vs_idle > 600:
        print(f"[warn] {ws} vscode_idle_seconds > 600 ({vs_idle:.2f})")
    if (vs_active + vs_idle) > max(vs_total, 1e-9) and vs_total > 0:
        print(f"[warn] {ws} vscode_active_seconds + vscode_idle_seconds > vscode_total_duration_sec ({vs_active + vs_idle:.2f} > {vs_total:.2f})")
    if os_sum > 650:
        print(f"[warn] {ws} os total time unusually high ({os_sum:.2f})")
    if ide_ratio > 1:
        print(f"[warn] {ws} ide_ratio > 1 ({ide_ratio:.4f})")
    if browser_ratio > 1:
        print(f"[warn] {ws} browser_ratio > 1 ({browser_ratio:.4f})")


def normalize_quality_flags_for_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Recompute quality flags on existing rows so older rows follow current rules too."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            total_active_time_sec,
            total_idle_time_sec,
            total_locked_time_sec,
            browser_active_time_sec,
            vscode_total_duration_sec,
            calendar_meeting_time_sec,
            vscode_active_seconds,
            vscode_edit_count,
            vscode_save_count,
            vscode_terminal_commands,
            vscode_chars_added,
            vscode_chars_removed
        FROM model1_features_10min
        WHERE user_id = ?
        """,
        (user_id,),
    )
    rows = cur.fetchall()

    updates: List[Tuple[Any, ...]] = []
    for r in rows:
        row_id = r[0]
        os_cov = min(float((r[1] or 0) + (r[2] or 0) + (r[3] or 0)), 600.0)
        browser_cov = min(float(r[4] or 0), 600.0)
        vscode_cov = min(float(r[5] or 0), 600.0)
        calendar_cov = min(float(r[6] or 0), 600.0)

        has_os = 1 if os_cov > 0 else 0
        has_browser = 1 if (browser_cov > 0 and float(r[4] or 0) > 0) else 0
        has_vscode = 1 if vscode_cov > 0 else 0
        has_calendar = 1 if calendar_cov > 0 else 0
        has_any = 1 if (has_os or has_browser or has_vscode or has_calendar) else 0

        vscode_has_evidence = (
            float(r[7] or 0) >= 30
            or int(r[8] or 0) > 0
            or int(r[9] or 0) > 0
            or int(r[10] or 0) > 0
            or int(r[11] or 0) > 0
            or int(r[12] or 0) > 0
        )

        is_vscode_only = (has_os == 0 and has_browser == 0 and has_calendar == 0 and has_vscode == 1)
        low_evidence_vscode_only = is_vscode_only and (not vscode_has_evidence)

        is_training_eligible = 1 if (has_os or has_browser or vscode_has_evidence) else 0
        if low_evidence_vscode_only:
            is_training_eligible = 0

        quality_warning: Optional[str] = None
        if not has_any:
            quality_warning = "no_signal"
        elif low_evidence_vscode_only:
            quality_warning = "low_evidence_vscode_only"
        elif not is_training_eligible:
            quality_warning = "low_evidence"

        quality = min((os_cov + browser_cov + vscode_cov + calendar_cov) / (4.0 * 600.0), 1.0)

        updates.append(
            (
                has_os,
                has_browser,
                has_vscode,
                has_calendar,
                has_any,
                os_cov,
                browser_cov,
                vscode_cov,
                calendar_cov,
                quality,
                is_training_eligible,
                quality_warning,
                row_id,
            )
        )

    cur.executemany(
        """
        UPDATE model1_features_10min
        SET
            has_os_signal = ?,
            has_browser_signal = ?,
            has_vscode_signal = ?,
            has_calendar_signal = ?,
            has_any_signal = ?,
            os_coverage_sec = ?,
            browser_coverage_sec = ?,
            vscode_coverage_sec = ?,
            calendar_coverage_sec = ?,
            data_quality_score = ?,
            is_training_eligible = ?,
            quality_warning = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        updates,
    )


# ===========================
# Main Pipeline
# ===========================

def build_dataset(db_path: str, user_id: str = "default_user") -> None:
    """
    Build and populate model1_features_10min from raw source tables.

    Debug logging is printed per window with matched row counts and sample intervals.
    """
    print(f"[*] Opening database: {db_path}")
    conn = sqlite3.connect(db_path)

    create_table(conn)

    source_tables = resolve_source_tables(conn)
    print("[*] Source tables:", source_tables)
    if source_tables.get("vscode"):
        print(f"[info] Using VS Code source table: {source_tables['vscode']}")

    source_rows = {
        "os": load_rows(conn, source_tables["os"], "os"),
        "browser": load_rows(conn, source_tables["browser"], "browser"),
        "vscode": load_rows(conn, source_tables["vscode"], "vscode"),
        "calendar": load_rows(conn, source_tables["calendar"], "calendar"),
    }
    print(
        "[*] Raw rows loaded:"
        f" os={len(source_rows['os'])},"
        f" browser={len(source_rows['browser'])},"
        f" vscode={len(source_rows['vscode'])},"
        f" calendar={len(source_rows['calendar'])}"
    )
    print(f"[info] VS Code clean sessions loaded: {len(source_rows['vscode'])}")

    windows = get_windows(source_rows)
    print(f"[*] Found {len(windows)} windows")

    if not windows:
        print("[!] No windows found. Nothing to aggregate.")
        conn.close()
        return

    inserted = 0
    for idx, (window_start, window_end) in enumerate(windows, 1):
        os_features, os_count, os_samples = aggregate_os(source_rows["os"], window_start, window_end)
        browser_features, browser_count, browser_samples = aggregate_browser(source_rows["browser"], window_start, window_end)
        vscode_features, vscode_count, vscode_samples = aggregate_vscode(source_rows["vscode"], window_start, window_end)
        calendar_features, calendar_count, calendar_samples = aggregate_calendar(source_rows["calendar"], window_start, window_end)

        print(
            f"[debug] window {to_utc_window_string(window_start)} -> {to_utc_window_string(window_end)} | "
            f"os={os_count}, browser={browser_count}, vscode={vscode_count}, calendar={calendar_count}"
        )
        if os_samples:
            print(f"[debug]   os sample: {os_samples[0]}")
        if browser_samples:
            print(f"[debug]   browser sample: {browser_samples[0]}")
        if vscode_samples:
            print(f"[debug]   vscode sample: {vscode_samples[0]}")
        if calendar_samples:
            print(f"[debug]   calendar sample: {calendar_samples[0]}")

        derived = compute_features(os_features, browser_features, vscode_features, calendar_features)
        quality_flags = compute_data_quality_flags(
            os_count,
            browser_count,
            vscode_count,
            calendar_count,
            os_features,
            browser_features,
            vscode_features,
            calendar_features,
        )
        source_refs = {
            "os": {
                "count": os_count,
                "samples": os_samples,
            },
            "browser": {
                "count": browser_count,
                "samples": browser_samples,
            },
            "vscode": {
                "count": vscode_count,
                "samples": vscode_samples,
            },
            "calendar": {
                "count": calendar_count,
                "samples": calendar_samples,
            },
        }
        all_features = {
            **os_features,
            **browser_features,
            **vscode_features,
            **calendar_features,
            **derived,
            **quality_flags,
            "source_refs_json": json.dumps(source_refs),
        }

        warn_on_window_anomalies(window_start, all_features)

        insert_row(conn, user_id, window_start, window_end, all_features)
        inserted += 1

        if idx % 20 == 0:
            print(f"[*] Processed {idx}/{len(windows)} windows")

    normalize_quality_flags_for_user(conn, user_id)

    conn.commit()
    conn.close()
    print(f"[ok] build complete: inserted/updated {inserted} rows in model1_features_10min")


if __name__ == "__main__":
    import sys

    db_file = sys.argv[1] if len(sys.argv) > 1 else "./smartdesk.db"
    build_dataset(db_file)
