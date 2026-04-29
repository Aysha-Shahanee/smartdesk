CREATE TABLE IF NOT EXISTS productivity_summary_10min (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    timezone TEXT NOT NULL,

    os_active_sec INTEGER,
    os_idle_sec INTEGER,
    os_locked_sec INTEGER,
    context_switch_count INTEGER,
    top_app TEXT,
    dominant_app_category TEXT,

    browser_active_sec INTEGER,
    productive_browser_sec INTEGER,
    neutral_browser_sec INTEGER,
    distracting_browser_sec INTEGER,
    communication_browser_sec INTEGER,
    tab_switch_count INTEGER,
    unique_domains_count INTEGER,
    top_domain TEXT,
    active_tab_category TEXT,

    vscode_foreground_sec INTEGER,
    vscode_active_sec INTEGER,
    vscode_idle_sec INTEGER,
    edit_count INTEGER,
    save_count INTEGER,
    file_switch_count INTEGER,
    terminal_command_count INTEGER,
    debug_run_count INTEGER,
    active_project TEXT,
    active_file_name TEXT,
    active_language TEXT,
    git_branch TEXT,

    calendar_meeting_sec INTEGER,
    in_meeting INTEGER,
    meeting_title TEXT,

    focus_score INTEGER,
    activity_label TEXT,
    label_source TEXT,

    data_quality_score INTEGER,
    missing_sources TEXT,

    source TEXT,
    schema_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(user_id, window_start, window_end)
);
