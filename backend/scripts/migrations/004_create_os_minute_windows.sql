CREATE TABLE IF NOT EXISTS os_minute_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    timezone TEXT NOT NULL,

    active_time_sec INTEGER,
    idle_time_sec INTEGER,
    locked_time_sec INTEGER,
    context_switch_count INTEGER,

    top_app TEXT,
    top_app_sec INTEGER,
    dominant_app_category TEXT,
    dominant_app_category_sec INTEGER,

    active_app_durations_json TEXT,
    category_durations_json TEXT,

    source TEXT,
    schema_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(user_id, window_start, window_end)
);
