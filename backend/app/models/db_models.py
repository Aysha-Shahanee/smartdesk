from sqlalchemy import Column, Integer, String, Float, Boolean, UniqueConstraint
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

    # Timeline synchronization
    timeline_index_id = Column(Integer, nullable=True)

    # Future extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

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

    # Timeline synchronization
    timeline_index_id = Column(Integer, nullable=True)

    # Future extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class IDEMinuteWindowRecord(Base):
    """IDE-agnostic minute window record.
    Supports VS Code, Antigravity, JetBrains, or any IDE that sends data.
    The `source` field identifies which IDE sent the data.
    """
    __tablename__ = "ide_minute_windows"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", "window_end", name="uq_ide_minute_window"),
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
    ide_foreground_sec = Column(Integer, nullable=True)
    active_editor_sec = Column(Integer, nullable=True)
    idle_sec = Column(Integer, nullable=True)
    edit_count = Column(Integer, nullable=False, default=0)
    save_count = Column(Integer, nullable=False, default=0)
    file_switch_count = Column(Integer, nullable=False, default=0)
    terminal_command_count = Column(Integer, nullable=False, default=0)
    debug_run_count = Column(Integer, nullable=False, default=0)

    # Coding velocity metrics
    lines_added = Column(Integer, nullable=True, default=0)
    lines_deleted = Column(Integer, nullable=True, default=0)

    # Timeline synchronization
    timeline_index_id = Column(Integer, nullable=True)

    # Future extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

    source = Column(String, nullable=True)  # "vscode_extension", "antigravity_extension", etc.
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

    # Future extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class ActivityTimelineIndex(Base):
    """Lean session index — the canonical foreground activity timeline.
    All detailed metrics live in the raw minute-window tables.
    """
    __tablename__ = "activity_timeline_index"

    id = Column(Integer, primary_key=True)

    user_id = Column(String, index=True, nullable=False)

    window_start = Column(String, index=True, nullable=False)
    window_end = Column(String, index=True, nullable=False)

    timezone = Column(String, nullable=False)

    # Foreground authority from OS collector
    foreground_source = Column(String, nullable=False)
    # os | ide | browser | terminal

    foreground_app = Column(String, nullable=True)

    foreground_window_title = Column(String, nullable=True)

    foreground_category = Column(String, nullable=True)
    # coding | learning | distraction | communication | browsing

    # Synchronized raw data availability
    has_os_data = Column(Boolean, default=False)
    has_ide_data = Column(Boolean, default=False)
    has_browser_data = Column(Boolean, default=False)

    # Links/mapping metadata
    ide_workspace = Column(String, nullable=True)
    browser_domain = Column(String, nullable=True)

    activity_confidence = Column(Float, nullable=True)

    created_at = Column(String, nullable=False)


class GitHubConnectionRecord(Base):
    __tablename__ = "github_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, index=True, nullable=False)
    github_login = Column(String, nullable=True)
    installation_id = Column(Integer, unique=True, index=True, nullable=True)
    selected_owner = Column(String, nullable=True)
    selected_project_number = Column(Integer, nullable=True)
    selected_project_id = Column(String, unique=True, index=True, nullable=True)
    selected_project_title = Column(String, nullable=True)
    connection_status = Column(String, nullable=False, default="disconnected")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class GitHubOAuthStateRecord(Base):
    __tablename__ = "github_oauth_states"

    id = Column(Integer, primary_key=True)
    state_hash = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    expires_at = Column(String, nullable=False)
    used_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


class GitHubInitialPredictionRecord(Base):
    __tablename__ = "github_initial_predictions"

    id = Column(Integer, primary_key=True)
    collector_lifecycle_id = Column(Integer, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    project_item_id = Column(String, index=True, nullable=False)
    issue_id = Column(String, nullable=False)
    title = Column(String, nullable=True)
    description = Column(String, nullable=True)
    labels_json = Column(String, nullable=True)
    repository = Column(String, nullable=True)
    started_at = Column(String, nullable=False)
    predicted_low_hours = Column(Float, nullable=True)
    predicted_typical_hours = Column(Float, nullable=True)
    predicted_high_hours = Column(Float, nullable=True)
    model_version = Column(String, nullable=True)
    predicted_at = Column(String, nullable=False)
    prediction_status = Column(String, nullable=False)
    prediction_error = Column(String, nullable=True)
