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

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, window_start)
);
"""


SOURCE_TABLE_CANDIDATES = {
    "os": ["os_signals"],
    "browser": ["browser_signals", "browser"],
    "vscode": ["vscode_signals", "vscode"],
    "calendar": ["calendar_signals", "calendar"],
}


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


# ===========================
# Database Layer
# ===========================

def create_table(conn: sqlite3.Connection) -> None:
    """Create the model1_features_10min table."""
    conn.execute(CREATE_MODEL1_TABLE_SQL)
    conn.commit()
    print("[ok] table model1_features_10min ready")


def resolve_source_tables(conn: sqlite3.Connection) -> Dict[str, Optional[str]]:
    """Resolve actual table names present in DB for each source."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    available = {row[0] for row in cur.fetchall()}

    resolved: Dict[str, Optional[str]] = {}
    for source, candidates in SOURCE_TABLE_CANDIDATES.items():
        resolved[source] = next((c for c in candidates if c in available), None)

    return resolved


def load_rows(conn: sqlite3.Connection, table_name: Optional[str]) -> List[Tuple[Any, Any]]:
    """Load raw (timestamp, data) rows from a source table."""
    if not table_name:
        return []
    cur = conn.cursor()
    cur.execute(f"SELECT timestamp, data FROM {table_name}")
    return cur.fetchall()


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
    matched_payloads: List[Dict[str, Any]] = []
    sample_ranges: List[str] = []

    for ts_raw, data_raw in rows:
        data = parse_json_dict(data_raw)
        interval = extract_os_interval(ts_raw, data)
        if not interval:
            continue

        if windows_overlap(interval[0], interval[1], window_start, window_end):
            matched_payloads.append(data)
            if len(sample_ranges) < 3:
                sample_ranges.append(f"{interval[0].isoformat()} -> {interval[1].isoformat()}")

    if not matched_payloads:
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

    for data in matched_payloads:
        total_active += float(data.get("active_time_sec", 0) or 0)
        total_idle += float(data.get("idle_time_sec", 0) or 0)
        total_locked += float(data.get("locked_time_sec", 0) or 0)
        total_switches += int(data.get("context_switch_count", 0) or 0)

        app_map = data.get("active_app_durations_sec", {})
        if isinstance(app_map, dict):
            for app, duration in app_map.items():
                try:
                    app_durations[str(app)] = app_durations.get(str(app), 0.0) + float(duration or 0)
                except (TypeError, ValueError):
                    continue

        cat_map = data.get("category_durations_sec", {})
        if isinstance(cat_map, dict):
            for cat, duration in cat_map.items():
                try:
                    category_durations[str(cat)] = category_durations.get(str(cat), 0.0) + float(duration or 0)
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
    }, len(matched_payloads), sample_ranges


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

            category = str(entry.get("category", "unknown")).lower()
            if category not in category_times:
                category = "unknown"
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

        total_duration += float(data.get("duration_seconds", 0) or 0)
        active_seconds += float(data.get("active_seconds", 0) or 0)
        idle_seconds += float(data.get("idle_seconds", 0) or 0)
        edit_count += int(data.get("edit_count", 0) or 0)
        save_count += int(data.get("save_count", 0) or 0)
        debug_runs += int(data.get("debug_runs", 0) or 0)
        terminal_commands += int(data.get("terminal_commands", 0) or 0)
        chars_added += int(data.get("chars_added", 0) or 0)
        chars_removed += int(data.get("chars_removed", 0) or 0)

        file_path = data.get("file_path")
        language = data.get("language")
        if file_path:
            unique_files.add(str(file_path))
        if language:
            unique_languages.add(str(language))

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

    ide_ratio = safe_divide(vscode_active, max(total_active, 1))
    browser_ratio = safe_divide(browser_active, max(total_active, 1))

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


# ===========================
# Insert Logic
# ===========================

def insert_row(conn: sqlite3.Connection, user_id: str, window_start: datetime, window_end: datetime, all_features: Dict[str, Any]) -> None:
    """Insert or replace one feature row for a 10-minute window."""
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
    ]

    values = [user_id, window_start.isoformat(), window_end.isoformat()]
    values.extend(all_features.get(col, 0) for col in feature_columns)

    cols_str = "user_id, window_start, window_end, " + ", ".join(feature_columns)
    placeholders = ", ".join(["?"] * len(values))

    sql = f"INSERT OR REPLACE INTO model1_features_10min ({cols_str}) VALUES ({placeholders})"
    conn.execute(sql, values)


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

    source_rows = {
        "os": load_rows(conn, source_tables["os"]),
        "browser": load_rows(conn, source_tables["browser"]),
        "vscode": load_rows(conn, source_tables["vscode"]),
        "calendar": load_rows(conn, source_tables["calendar"]),
    }
    print(
        "[*] Raw rows loaded:"
        f" os={len(source_rows['os'])},"
        f" browser={len(source_rows['browser'])},"
        f" vscode={len(source_rows['vscode'])},"
        f" calendar={len(source_rows['calendar'])}"
    )

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
            f"[debug] window {window_start.isoformat()} -> {window_end.isoformat()} | "
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
        all_features = {**os_features, **browser_features, **vscode_features, **calendar_features, **derived}

        insert_row(conn, user_id, window_start, window_end, all_features)
        inserted += 1

        if idx % 20 == 0:
            print(f"[*] Processed {idx}/{len(windows)} windows")

    conn.commit()
    conn.close()
    print(f"[ok] build complete: inserted/updated {inserted} rows in model1_features_10min")


if __name__ == "__main__":
    import sys

    db_file = sys.argv[1] if len(sys.argv) > 1 else "./smartdesk.db"
    build_dataset(db_file)
