from sqlalchemy import Column, Integer, String, DateTime, JSON, UniqueConstraint
from app.core.database import Base


class OSSignalRecord(Base):
    __tablename__ = "os_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)  # Stores the raw dictionary natively


class OSMinuteWindowRecord(Base):
    __tablename__ = "os_minute_windows"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", "window_end", name="uq_os_minute_window"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    window_start = Column(String, index=True, nullable=False)
    window_end = Column(String, index=True, nullable=False)
    timezone = Column(String, nullable=False)

    active_time_sec = Column(Integer, nullable=True)
    idle_time_sec = Column(Integer, nullable=True)
    locked_time_sec = Column(Integer, nullable=True)
    context_switch_count = Column(Integer, nullable=True)

    top_app = Column(String, nullable=True)
    top_app_sec = Column(Integer, nullable=True)
    dominant_app_category = Column(String, nullable=True)
    dominant_app_category_sec = Column(Integer, nullable=True)

    active_app_durations_json = Column(String, nullable=True)
    category_durations_json = Column(String, nullable=True)

    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class BrowserRecord(Base):
    # LEGACY: Session-based browser ingestion. Keep for backward compatibility.
    __tablename__ = "browser_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class BrowserMinuteWindowRecord(Base):
    __tablename__ = "browser_minute_windows"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", "window_end", name="uq_browser_minute_window"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    window_start = Column(String, index=True, nullable=False)
    window_end = Column(String, index=True, nullable=False)
    timezone = Column(String, nullable=True)
    browser_name = Column(String, nullable=True)
    active_tab_domain = Column(String, nullable=True)
    active_tab_url = Column(String, nullable=True)
    active_tab_title = Column(String, nullable=True)
    active_tab_category = Column(String, nullable=True)
    browser_active_time_sec = Column(Integer, nullable=True)
    browser_idle_time_sec = Column(Integer, nullable=True)
    productive_time_sec = Column(Integer, nullable=True)
    neutral_time_sec = Column(Integer, nullable=True)
    distracting_time_sec = Column(Integer, nullable=True)
    communication_time_sec = Column(Integer, nullable=True)
    tab_switch_count = Column(Integer, nullable=False, default=0)
    unique_domains_count = Column(Integer, nullable=False, default=0)
    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class VSCodeRecord(Base):
    # LEGACY: Session-based VS Code ingestion. Keep for backward compatibility.
    __tablename__ = "vscode_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class VSCodeMinuteWindowRecord(Base):
    __tablename__ = "vscode_minute_windows"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", "window_end", name="uq_vscode_minute_window"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    window_start = Column(String, index=True, nullable=False)
    window_end = Column(String, index=True, nullable=False)
    timezone = Column(String, nullable=True)
    workspace_name = Column(String, nullable=True)
    project_path = Column(String, nullable=True)
    repo_id = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)
    active_file_path = Column(String, nullable=True)
    active_file_name = Column(String, nullable=True)
    active_language = Column(String, nullable=True)
    vscode_foreground_sec = Column(Integer, nullable=True)
    active_editor_sec = Column(Integer, nullable=True)
    idle_sec = Column(Integer, nullable=True)
    edit_count = Column(Integer, nullable=False, default=0)
    save_count = Column(Integer, nullable=False, default=0)
    file_switch_count = Column(Integer, nullable=False, default=0)
    terminal_command_count = Column(Integer, nullable=False, default=0)
    debug_run_count = Column(Integer, nullable=False, default=0)
    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class CalendarRecord(Base):
    __tablename__ = "calendar_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class CalendarEventRecord(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_calendar_event"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    event_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=True)
    start_time = Column(String, nullable=True)
    end_time = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    attendees_count = Column(Integer, nullable=True)
    is_recurring = Column(Integer, nullable=True)
    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class ProductivitySummary10MinRecord(Base):
    __tablename__ = "productivity_summary_10min"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", "window_end", name="uq_productivity_summary_10min"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    window_start = Column(String, index=True, nullable=False)
    window_end = Column(String, index=True, nullable=False)
    timezone = Column(String, nullable=False)

    os_active_sec = Column(Integer, nullable=True)
    os_idle_sec = Column(Integer, nullable=True)
    os_locked_sec = Column(Integer, nullable=True)
    context_switch_count = Column(Integer, nullable=True)
    top_app = Column(String, nullable=True)
    dominant_app_category = Column(String, nullable=True)

    browser_active_sec = Column(Integer, nullable=True)
    productive_browser_sec = Column(Integer, nullable=True)
    neutral_browser_sec = Column(Integer, nullable=True)
    distracting_browser_sec = Column(Integer, nullable=True)
    communication_browser_sec = Column(Integer, nullable=True)
    tab_switch_count = Column(Integer, nullable=True)
    unique_domains_count = Column(Integer, nullable=True)
    top_domain = Column(String, nullable=True)
    active_tab_category = Column(String, nullable=True)

    vscode_foreground_sec = Column(Integer, nullable=True)
    vscode_active_sec = Column(Integer, nullable=True)
    vscode_idle_sec = Column(Integer, nullable=True)
    edit_count = Column(Integer, nullable=True)
    save_count = Column(Integer, nullable=True)
    file_switch_count = Column(Integer, nullable=True)
    terminal_command_count = Column(Integer, nullable=True)
    debug_run_count = Column(Integer, nullable=True)
    active_project = Column(String, nullable=True)
    active_file_name = Column(String, nullable=True)
    active_language = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)

    calendar_meeting_sec = Column(Integer, nullable=True)
    in_meeting = Column(Integer, nullable=True)
    meeting_title = Column(String, nullable=True)

    focus_score = Column(Integer, nullable=True)
    activity_label = Column(String, nullable=True)
    label_source = Column(String, nullable=True)

    data_quality_score = Column(Integer, nullable=True)
    missing_sources = Column(String, nullable=True)

    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
