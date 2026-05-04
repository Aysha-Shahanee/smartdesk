-- Migration: Drop unused activity_session_summary columns

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS activity_session_summary_new (
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

INSERT INTO activity_session_summary_new (
    id,
    user_id,
    session_start,
    session_end,
    timezone,
    duration_sec,
    primary_app,
    primary_category,
    total_active_time_sec,
    total_idle_time_sec,
    total_locked_time_sec,
    context_switch_count,
    browser_time_sec,
    top_domain,
    active_tab_category,
    calendar_meeting_time_sec,
    in_meeting,
    activity_type,
    activity_description,
    source,
    schema_version,
    created_at,
    updated_at
)
SELECT
    id,
    user_id,
    session_start,
    session_end,
    timezone,
    duration_sec,
    primary_app,
    primary_category,
    total_active_time_sec,
    total_idle_time_sec,
    total_locked_time_sec,
    context_switch_count,
    browser_time_sec,
    top_domain,
    active_tab_category,
    calendar_meeting_time_sec,
    in_meeting,
    activity_type,
    activity_description,
    source,
    schema_version,
    created_at,
    updated_at
FROM activity_session_summary;

DROP TABLE activity_session_summary;
ALTER TABLE activity_session_summary_new RENAME TO activity_session_summary;

COMMIT;

PRAGMA foreign_keys = ON;
