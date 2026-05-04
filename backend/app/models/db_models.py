from sqlalchemy import Column, Integer, String, DateTime, JSON, UniqueConstraint
from app.core.database import Base


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

    # OS-level time totals
    total_active_time_sec = Column(Integer, nullable=True)
    total_idle_time_sec = Column(Integer, nullable=True)
    total_locked_time_sec = Column(Integer, nullable=True)

    # Per-source active time
    browser_time_sec = Column(Integer, nullable=True)
    vscode_time_sec = Column(Integer, nullable=True)
    calendar_meeting_time_sec = Column(Integer, nullable=True)

    # Context switching
    context_switch_count = Column(Integer, nullable=True)

    created_at = Column(String, nullable=False)

