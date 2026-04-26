"""
Build dashboard-ready activity sessions by merging labeled 10-minute feature windows.

Pipeline:
model1_features_10min -> merge consecutive same-label windows -> activity_sessions
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


CREATE_ACTIVITY_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS activity_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default_user',

    start_time_utc TEXT NOT NULL,
    end_time_utc TEXT NOT NULL,
    duration_seconds REAL NOT NULL,

    activity_label TEXT NOT NULL,
    label_source TEXT,
    confidence REAL DEFAULT 0,

    primary_app TEXT,
    primary_project TEXT,
    primary_domain TEXT,

    total_active_time_sec REAL DEFAULT 0,
    total_idle_time_sec REAL DEFAULT 0,
    total_locked_time_sec REAL DEFAULT 0,

    vscode_total_duration_sec REAL DEFAULT 0,
    vscode_active_seconds REAL DEFAULT 0,
    vscode_idle_seconds REAL DEFAULT 0,
    vscode_edit_count INTEGER DEFAULT 0,
    vscode_save_count INTEGER DEFAULT 0,
    vscode_terminal_commands INTEGER DEFAULT 0,

    browser_active_time_sec REAL DEFAULT 0,
    browser_productive_time_sec REAL DEFAULT 0,
    browser_distracting_time_sec REAL DEFAULT 0,

    os_context_switch_count INTEGER DEFAULT 0,
    multitask_score REAL DEFAULT 0,
    distraction_score REAL DEFAULT 0,
    focus_score REAL DEFAULT 0,

    source_window_ids_json TEXT,
    source_refs_json TEXT,
    metrics_json TEXT,

    data_quality_score REAL DEFAULT 0,
    quality_warning TEXT,

    sync_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_id, start_time_utc, end_time_utc, activity_label)
)
"""


def parse_iso_datetime(value: Any) -> Optional[datetime]:
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


def to_utc_string(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def parse_json_dict(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def create_activity_sessions_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_ACTIVITY_SESSIONS_SQL)
    conn.commit()


def _model1_columns(conn: sqlite3.Connection) -> set:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(model1_features_10min)")
    return {row[1] for row in cur.fetchall()}


def _resolve_range(start_date: Optional[str], end_date: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    def _parse(v: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
        if not v:
            return None
        dt = parse_iso_datetime(v)
        if dt is not None:
            return dt
        try:
            d = datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if end_of_day:
                return d + timedelta(days=1)
            return d
        except ValueError:
            return None

    return _parse(start_date, end_of_day=False), _parse(end_date, end_of_day=True)


def _load_model1_rows(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, bool]]:
    cols = _model1_columns(conn)
    has_predicted = "predicted_label" in cols
    has_conf = "label_confidence" in cols

    selected = [
        "id",
        "user_id",
        "window_start",
        "window_end",
        "manual_label",
        "has_any_signal",
        "is_training_eligible",
        "quality_warning",
        "data_quality_score",
        "total_active_time_sec",
        "total_idle_time_sec",
        "total_locked_time_sec",
        "vscode_total_duration_sec",
        "vscode_active_seconds",
        "vscode_idle_seconds",
        "vscode_edit_count",
        "vscode_save_count",
        "vscode_terminal_commands",
        "browser_active_time_sec",
        "browser_productive_time_sec",
        "browser_distracting_time_sec",
        "os_context_switch_count",
        "multitask_score",
        "distraction_score",
        "ide_ratio",
        "browser_productive_ratio",
        "source_refs_json",
    ]
    if has_predicted:
        selected.append("predicted_label")
    if has_conf:
        selected.append("label_confidence")

    sql = f"SELECT {', '.join(selected)} FROM model1_features_10min WHERE user_id = ?"
    params: List[Any] = [user_id]

    start_dt, end_dt = _resolve_range(start_date, end_date)
    if start_dt is not None:
        sql += " AND window_end > ?"
        params.append(to_utc_string(start_dt))
    if end_dt is not None:
        sql += " AND window_start < ?"
        params.append(to_utc_string(end_dt))

    sql += " ORDER BY window_start ASC"

    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(zip(selected, r)) for r in cur.fetchall()]

    return rows, {"has_predicted": has_predicted, "has_conf": has_conf}


def _resolve_label(
    row: Dict[str, Any],
    flags: Dict[str, bool],
    fallback_enabled: bool,
) -> Tuple[Optional[str], Optional[str], float]:
    manual = str(row.get("manual_label") or "").strip()
    if manual:
        return manual, "manual", 1.0

    if flags.get("has_predicted"):
        predicted = str(row.get("predicted_label") or "").strip()
        if predicted:
            conf = float(row.get("label_confidence") or 0.0) if flags.get("has_conf") else 0.0
            return predicted, "predicted", conf

    if fallback_enabled:
        if float(row.get("distraction_score", 0) or 0) >= 0.7:
            return "distracted", "fallback", 0.4
        if float(row.get("ide_ratio", 0) or 0) >= 0.5:
            return "focused_work", "fallback", 0.4
        return "neutral", "fallback", 0.3

    return None, None, 0.0


def _row_is_valid(
    row: Dict[str, Any],
    label: Optional[str],
    label_source: Optional[str],
    predicted_conf_threshold: float,
) -> Tuple[bool, str]:
    if not label:
        return False, "unlabeled"

    manual = str(row.get("manual_label") or "").strip()
    if manual:
        return True, "ok"

    if int(row.get("has_any_signal") or 0) != 1:
        return False, "low_quality"

    if int(row.get("is_training_eligible") or 0) != 1:
        return False, "low_quality"

    qwarn = str(row.get("quality_warning") or "").strip().lower()
    if qwarn == "no_signal" or qwarn.startswith("low_evidence"):
        return False, "low_quality"

    if label_source == "predicted":
        conf = float(row.get("label_confidence") or 0.0)
        if conf < predicted_conf_threshold:
            return False, "low_quality"

    return True, "ok"


def _merge_source_refs(ref_payloads: List[str]) -> str:
    merged: Dict[str, Dict[str, Any]] = {}
    for raw in ref_payloads:
        data = parse_json_dict(raw)
        if not data:
            continue
        for source, payload in data.items():
            if source not in merged:
                merged[source] = {"count": 0, "samples": []}
            if isinstance(payload, dict):
                merged[source]["count"] += int(payload.get("count", 0) or 0)
                samples = payload.get("samples", [])
                if isinstance(samples, list):
                    for s in samples:
                        ss = str(s)
                        if ss and ss not in merged[source]["samples"]:
                            merged[source]["samples"].append(ss)
            merged[source]["samples"] = merged[source]["samples"][:10]
    return json.dumps(merged) if merged else json.dumps({})


def _primary_context(session: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    vsc = float(session["vscode_total_duration_sec"])
    brw = float(session["browser_active_time_sec"])
    osa = float(session["total_active_time_sec"])

    if vsc >= brw and vsc >= osa and vsc > 0:
        primary_app = "VS Code"
    elif brw >= vsc and brw >= osa and brw > 0:
        primary_app = "Browser"
    elif osa > 0:
        primary_app = "OS"
    else:
        primary_app = "Unknown"

    # Not enough stable project/domain fields in model1_features_10min yet.
    primary_project = None
    primary_domain = None

    return primary_app, primary_project, primary_domain


def _build_session_record(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    start_dt = parse_iso_datetime(rows[0]["window_start"])
    end_dt = parse_iso_datetime(rows[-1]["window_end"])
    if start_dt is None or end_dt is None:
        raise ValueError("Invalid window boundaries while building activity session")

    duration = max((end_dt - start_dt).total_seconds(), 0.0)
    source_ids = [int(r["id"]) for r in rows]
    label_sources = [str(r.get("_resolved_label_source") or "") for r in rows]

    if any(src == "manual" for src in label_sources):
        confidence = 1.0
        label_source = "manual"
    elif any(src == "predicted" for src in label_sources):
        conf_vals = [float(r.get("_resolved_confidence") or 0.0) for r in rows if str(r.get("_resolved_label_source")) == "predicted"]
        confidence = sum(conf_vals) / max(len(conf_vals), 1)
        label_source = "predicted"
    else:
        conf_vals = [float(r.get("_resolved_confidence") or 0.0) for r in rows]
        confidence = sum(conf_vals) / max(len(conf_vals), 1)
        label_source = "fallback"

    total_active = sum(float(r.get("total_active_time_sec") or 0) for r in rows)
    total_idle = sum(float(r.get("total_idle_time_sec") or 0) for r in rows)
    total_locked = sum(float(r.get("total_locked_time_sec") or 0) for r in rows)

    vscode_total = sum(float(r.get("vscode_total_duration_sec") or 0) for r in rows)
    vscode_active = sum(float(r.get("vscode_active_seconds") or 0) for r in rows)
    vscode_idle = sum(float(r.get("vscode_idle_seconds") or 0) for r in rows)
    vscode_edit = sum(int(r.get("vscode_edit_count") or 0) for r in rows)
    vscode_save = sum(int(r.get("vscode_save_count") or 0) for r in rows)
    vscode_term = sum(int(r.get("vscode_terminal_commands") or 0) for r in rows)

    browser_active = sum(float(r.get("browser_active_time_sec") or 0) for r in rows)
    browser_prod = sum(float(r.get("browser_productive_time_sec") or 0) for r in rows)
    browser_dist = sum(float(r.get("browser_distracting_time_sec") or 0) for r in rows)

    os_switch = sum(int(r.get("os_context_switch_count") or 0) for r in rows)
    multitask = sum(float(r.get("multitask_score") or 0) for r in rows)
    distraction = sum(float(r.get("distraction_score") or 0) for r in rows) / max(len(rows), 1)
    ide_ratio_avg = sum(float(r.get("ide_ratio") or 0) for r in rows) / max(len(rows), 1)
    browser_prod_ratio_avg = sum(float(r.get("browser_productive_ratio") or 0) for r in rows) / max(len(rows), 1)
    focus_score = clamp(0.5 * ide_ratio_avg + 0.3 * browser_prod_ratio_avg - 0.2 * distraction, 0.0, 1.0)

    data_quality = sum(float(r.get("data_quality_score") or 0) for r in rows) / max(len(rows), 1)
    quality_warns = [str(r.get("quality_warning") or "").strip() for r in rows if str(r.get("quality_warning") or "").strip()]
    quality_warning = quality_warns[0] if quality_warns else None

    source_refs_json = _merge_source_refs([str(r.get("source_refs_json") or "") for r in rows])

    source_mix = {
        "os": any(int(r.get("has_os_signal") or 0) == 1 for r in rows),
        "browser": any(int(r.get("has_browser_signal") or 0) == 1 for r in rows),
        "vscode": any(int(r.get("has_vscode_signal") or 0) == 1 for r in rows),
        "calendar": any(int(r.get("has_calendar_signal") or 0) == 1 for r in rows),
    }
    metrics_json = json.dumps(
        {
            "window_count": len(rows),
            "avg_focus_score": focus_score,
            "total_context_switches": os_switch,
            "source_mix": source_mix,
        }
    )

    session = {
        "user_id": rows[0]["user_id"],
        "start_time_utc": to_utc_string(start_dt),
        "end_time_utc": to_utc_string(end_dt),
        "duration_seconds": duration,
        "activity_label": label,
        "label_source": label_source,
        "confidence": confidence,
        "total_active_time_sec": total_active,
        "total_idle_time_sec": total_idle,
        "total_locked_time_sec": total_locked,
        "vscode_total_duration_sec": vscode_total,
        "vscode_active_seconds": vscode_active,
        "vscode_idle_seconds": vscode_idle,
        "vscode_edit_count": vscode_edit,
        "vscode_save_count": vscode_save,
        "vscode_terminal_commands": vscode_term,
        "browser_active_time_sec": browser_active,
        "browser_productive_time_sec": browser_prod,
        "browser_distracting_time_sec": browser_dist,
        "os_context_switch_count": os_switch,
        "multitask_score": multitask,
        "distraction_score": distraction,
        "focus_score": focus_score,
        "source_window_ids_json": json.dumps(source_ids),
        "source_refs_json": source_refs_json,
        "metrics_json": metrics_json,
        "data_quality_score": data_quality,
        "quality_warning": quality_warning,
        "sync_status": "pending",
    }

    primary_app, primary_project, primary_domain = _primary_context(session)
    session["primary_app"] = primary_app
    session["primary_project"] = primary_project
    session["primary_domain"] = primary_domain

    return session


def _delete_existing_sessions(
    conn: sqlite3.Connection,
    user_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> None:
    start_dt, end_dt = _resolve_range(start_date, end_date)
    cur = conn.cursor()

    if start_dt is None and end_dt is None:
        cur.execute("DELETE FROM activity_sessions WHERE user_id = ?", (user_id,))
    elif start_dt is None and end_dt is not None:
        cur.execute(
            "DELETE FROM activity_sessions WHERE user_id = ? AND start_time_utc < ?",
            (user_id, to_utc_string(end_dt)),
        )
    elif start_dt is not None and end_dt is None:
        cur.execute(
            "DELETE FROM activity_sessions WHERE user_id = ? AND end_time_utc > ?",
            (user_id, to_utc_string(start_dt)),
        )
    else:
        cur.execute(
            """
            DELETE FROM activity_sessions
            WHERE user_id = ?
              AND start_time_utc < ?
              AND end_time_utc > ?
            """,
            (user_id, to_utc_string(end_dt), to_utc_string(start_dt)),
        )


def build_activity_sessions(
    db_path: str,
    user_id: str = "default_user",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fallback_enabled: bool = False,
    predicted_conf_threshold: float = 0.5,
) -> Dict[str, int]:
    """
    Build activity_sessions from model1_features_10min.

    Returns debug counters for pipeline observability.
    """
    conn = sqlite3.connect(db_path)
    try:
        create_activity_sessions_table(conn)

        rows, flags = _load_model1_rows(conn, user_id, start_date, end_date)
        total_read = len(rows)

        valid_rows: List[Dict[str, Any]] = []
        skipped_low_quality = 0
        skipped_unlabeled = 0

        for row in rows:
            label, label_source, conf = _resolve_label(row, flags, fallback_enabled)
            is_valid, reason = _row_is_valid(row, label, label_source, predicted_conf_threshold)

            if not is_valid:
                if reason == "unlabeled":
                    skipped_unlabeled += 1
                else:
                    skipped_low_quality += 1
                continue

            row["_resolved_label"] = label
            row["_resolved_label_source"] = label_source
            row["_resolved_confidence"] = conf
            valid_rows.append(row)

        # Rebuild behavior for derived table.
        _delete_existing_sessions(conn, user_id, start_date, end_date)

        sessions: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []

        for row in valid_rows:
            row_start = parse_iso_datetime(row.get("window_start"))
            row_end = parse_iso_datetime(row.get("window_end"))
            if row_start is None or row_end is None:
                continue

            if not current:
                current = [row]
                continue

            prev = current[-1]
            prev_end = parse_iso_datetime(prev.get("window_end"))
            if prev_end is None:
                prev_end = row_start

            gap_sec = (row_start - prev_end).total_seconds()
            same_user = str(row.get("user_id")) == str(prev.get("user_id"))
            same_label = str(row.get("_resolved_label")) == str(prev.get("_resolved_label"))
            # Merge only truly consecutive windows (contiguous boundary).
            mergeable = same_user and same_label and abs(gap_sec) <= 1.0

            if mergeable:
                current.append(row)
            else:
                sessions.append(_build_session_record(current, str(current[0]["_resolved_label"])))
                current = [row]

        if current:
            sessions.append(_build_session_record(current, str(current[0]["_resolved_label"])))

        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO activity_sessions (
                user_id,
                start_time_utc,
                end_time_utc,
                duration_seconds,
                activity_label,
                label_source,
                confidence,
                primary_app,
                primary_project,
                primary_domain,
                total_active_time_sec,
                total_idle_time_sec,
                total_locked_time_sec,
                vscode_total_duration_sec,
                vscode_active_seconds,
                vscode_idle_seconds,
                vscode_edit_count,
                vscode_save_count,
                vscode_terminal_commands,
                browser_active_time_sec,
                browser_productive_time_sec,
                browser_distracting_time_sec,
                os_context_switch_count,
                multitask_score,
                distraction_score,
                focus_score,
                source_window_ids_json,
                source_refs_json,
                metrics_json,
                data_quality_score,
                quality_warning,
                sync_status,
                updated_at
            ) VALUES (
                :user_id,
                :start_time_utc,
                :end_time_utc,
                :duration_seconds,
                :activity_label,
                :label_source,
                :confidence,
                :primary_app,
                :primary_project,
                :primary_domain,
                :total_active_time_sec,
                :total_idle_time_sec,
                :total_locked_time_sec,
                :vscode_total_duration_sec,
                :vscode_active_seconds,
                :vscode_idle_seconds,
                :vscode_edit_count,
                :vscode_save_count,
                :vscode_terminal_commands,
                :browser_active_time_sec,
                :browser_productive_time_sec,
                :browser_distracting_time_sec,
                :os_context_switch_count,
                :multitask_score,
                :distraction_score,
                :focus_score,
                :source_window_ids_json,
                :source_refs_json,
                :metrics_json,
                :data_quality_score,
                :quality_warning,
                :sync_status,
                CURRENT_TIMESTAMP
            )
            """,
            sessions,
        )

        conn.commit()

        result = {
            "total_model1_windows_read": total_read,
            "labeled_windows_used": len(valid_rows),
            "sessions_created": len(sessions),
            "skipped_low_quality_rows": skipped_low_quality,
            "skipped_unlabeled_rows": skipped_unlabeled,
        }

        print(f"[*] total model1 windows read: {result['total_model1_windows_read']}")
        print(f"[*] labeled windows used: {result['labeled_windows_used']}")
        print(f"[*] sessions created: {result['sessions_created']}")
        print(f"[*] skipped low-quality rows: {result['skipped_low_quality_rows']}")
        print(f"[*] skipped unlabeled rows: {result['skipped_unlabeled_rows']}")

        return result
    finally:
        conn.close()


def get_day_timeline(db_path: str, date: str, user_id: str = "default_user") -> List[Dict[str, Any]]:
    start_dt, end_dt = _resolve_range(date, date)
    if start_dt is None or end_dt is None:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM activity_sessions
            WHERE user_id = ?
              AND start_time_utc < ?
              AND end_time_utc > ?
            ORDER BY start_time_utc ASC
            """,
            (user_id, to_utc_string(end_dt), to_utc_string(start_dt)),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_day_summary(db_path: str, date: str, user_id: str = "default_user") -> Dict[str, Any]:
    rows = get_day_timeline(db_path, date, user_id)
    if not rows:
        return {
            "session_count": 0,
            "total_duration_seconds": 0,
            "avg_focus_score": 0,
            "labels": {},
        }

    total_duration = sum(float(r.get("duration_seconds") or 0) for r in rows)
    avg_focus = sum(float(r.get("focus_score") or 0) for r in rows) / max(len(rows), 1)
    labels: Dict[str, float] = {}
    for r in rows:
        label = str(r.get("activity_label") or "unknown")
        labels[label] = labels.get(label, 0.0) + float(r.get("duration_seconds") or 0)

    return {
        "session_count": len(rows),
        "total_duration_seconds": total_duration,
        "avg_focus_score": avg_focus,
        "labels": labels,
    }


def get_activity_breakdown(db_path: str, date: str, user_id: str = "default_user") -> List[Dict[str, Any]]:
    rows = get_day_timeline(db_path, date, user_id)
    totals: Dict[str, float] = {}
    for r in rows:
        label = str(r.get("activity_label") or "unknown")
        totals[label] = totals.get(label, 0.0) + float(r.get("duration_seconds") or 0)
    return [{"activity_label": k, "duration_seconds": v} for k, v in sorted(totals.items(), key=lambda x: x[1], reverse=True)]


def get_app_usage(db_path: str, date: str, user_id: str = "default_user") -> List[Dict[str, Any]]:
    rows = get_day_timeline(db_path, date, user_id)
    totals: Dict[str, float] = {}
    for r in rows:
        app = str(r.get("primary_app") or "Unknown")
        totals[app] = totals.get(app, 0.0) + float(r.get("duration_seconds") or 0)
    return [{"primary_app": k, "duration_seconds": v} for k, v in sorted(totals.items(), key=lambda x: x[1], reverse=True)]


def get_project_usage(db_path: str, date: str, user_id: str = "default_user") -> List[Dict[str, Any]]:
    rows = get_day_timeline(db_path, date, user_id)
    totals: Dict[str, float] = {}
    for r in rows:
        project = str(r.get("primary_project") or "Unknown")
        totals[project] = totals.get(project, 0.0) + float(r.get("duration_seconds") or 0)
    return [{"primary_project": k, "duration_seconds": v} for k, v in sorted(totals.items(), key=lambda x: x[1], reverse=True)]
