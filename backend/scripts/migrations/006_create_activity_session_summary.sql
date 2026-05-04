-- Migration: Create activity_session_summary

CREATE TABLE IF NOT EXISTS activity_session_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_start TEXT NOT NULL,
    session_end TEXT NOT NULL,
    timezone TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,

    primary_app TEXT,
    primary_category TEXT,

    total_active_time_sec INTEGER,
    total_idle_time_sec INTEGER,
    total_locked_time_sec INTEGER,
    context_switch_count INTEGER,

    browser_time_sec INTEGER,
    top_domain TEXT,
    active_tab_category TEXT,

    calendar_meeting_time_sec INTEGER,
    in_meeting INTEGER,

    activity_type TEXT,
    activity_description TEXT,

    source TEXT,
    schema_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(user_id, session_start, session_end)
);
