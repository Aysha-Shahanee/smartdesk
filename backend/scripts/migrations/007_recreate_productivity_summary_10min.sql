-- Migration: Recreate productivity_summary_10min with lean schema
-- Old table had ~30 columns with duplicated data from source tables.
-- New table is a lightweight roll-up index only; dashboard fetches
-- details from os_minute_windows, browser_minute_windows, vscode_minute_windows,
-- calendar_events directly.

DROP TABLE IF EXISTS productivity_summary_10min;

CREATE TABLE productivity_summary_10min (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,

    total_active_time_sec   INTEGER,
    total_idle_time_sec     INTEGER,
    total_locked_time_sec   INTEGER,

    browser_time_sec        INTEGER,
    vscode_time_sec         INTEGER,
    calendar_meeting_time_sec INTEGER,

    context_switch_count    INTEGER,

    created_at TEXT NOT NULL,

    UNIQUE(user_id, window_start, window_end)
);
