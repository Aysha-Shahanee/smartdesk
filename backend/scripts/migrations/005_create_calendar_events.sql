CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT,
    start_time TEXT,
    end_time TEXT,
    timezone TEXT,
    attendees_count INTEGER,
    is_recurring INTEGER,
    source TEXT,
    schema_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(user_id, event_id)
);
