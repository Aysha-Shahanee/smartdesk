from sqlalchemy import Column, Integer, String, DateTime, JSON, Float
from app.core.database import Base


class OSSignalRecord(Base):
    __tablename__ = "os_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)  # Stores the raw dictionary natively


class BrowserRecord(Base):
    __tablename__ = "browser_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class VSCodeRecord(Base):
    __tablename__ = "vscode_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class VSCodeSession(Base):
    __tablename__ = "vscode_sessions"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True)  # Unique per session
    user_id = Column(String, nullable=True)
    file_path = Column(String)
    file_name = Column(String, nullable=True)
    language = Column(String, nullable=True)
    project_path = Column(String)
    project_name = Column(String, nullable=True)
    workspace_name = Column(String, nullable=True)
    repo_id = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)
    start_time = Column(DateTime(timezone=True), index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_sec = Column(Integer, nullable=True)
    active_sec = Column(Integer, default=0)
    idle_sec = Column(Integer, default=0)
    edit_count = Column(Integer, default=0)
    save_count = Column(Integer, default=0)
    debug_run_count = Column(Integer, default=0)
    terminal_command_count = Column(Integer, default=0)
    approx_lines_added = Column(Integer, default=0)
    approx_lines_removed = Column(Integer, default=0)
    approx_chars_added = Column(Integer, default=0)
    approx_chars_removed = Column(Integer, default=0)
    is_final = Column(Integer, default=0)  # 0 or 1 (boolean flag)
    created_at = Column(DateTime(timezone=True), index=True)
    updated_at = Column(DateTime(timezone=True), index=True)


class VSCodeSessionSnapshot(Base):
    __tablename__ = "vscode_session_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, index=True)  # References VSCodeSession.event_id (not strict FK)
    user_id = Column(String, nullable=True)
    snapshot_time = Column(DateTime(timezone=True), index=True)
    file_path = Column(String, nullable=True)
    language = Column(String, nullable=True)
    active_sec = Column(Integer, default=0)
    idle_sec = Column(Integer, default=0)
    edit_count = Column(Integer, default=0)
    save_count = Column(Integer, default=0)
    debug_run_count = Column(Integer, default=0)
    terminal_command_count = Column(Integer, default=0)
    approx_lines_added = Column(Integer, default=0)
    approx_lines_removed = Column(Integer, default=0)
    approx_chars_added = Column(Integer, default=0)
    approx_chars_removed = Column(Integer, default=0)
    is_final = Column(Integer, default=0)  # 0 or 1 (boolean flag)
    created_at = Column(DateTime(timezone=True), index=True)


class CalendarRecord(Base):
    __tablename__ = "calendar_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class ActivitySession(Base):
    __tablename__ = "activity_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, default="default_user", index=True)

    start_time_utc = Column(String, nullable=False, index=True)
    end_time_utc = Column(String, nullable=False, index=True)
    duration_seconds = Column(Float, nullable=False)

    activity_label = Column(String, nullable=False, index=True)
    label_source = Column(String, nullable=True)
    confidence = Column(Float, default=0)

    primary_app = Column(String, nullable=True)
    primary_project = Column(String, nullable=True)
    primary_domain = Column(String, nullable=True)

    total_active_time_sec = Column(Float, default=0)
    total_idle_time_sec = Column(Float, default=0)
    total_locked_time_sec = Column(Float, default=0)

    vscode_total_duration_sec = Column(Float, default=0)
    vscode_active_seconds = Column(Float, default=0)
    vscode_idle_seconds = Column(Float, default=0)
    vscode_edit_count = Column(Integer, default=0)
    vscode_save_count = Column(Integer, default=0)
    vscode_terminal_commands = Column(Integer, default=0)

    browser_active_time_sec = Column(Float, default=0)
    browser_productive_time_sec = Column(Float, default=0)
    browser_distracting_time_sec = Column(Float, default=0)

    os_context_switch_count = Column(Integer, default=0)
    multitask_score = Column(Float, default=0)
    distraction_score = Column(Float, default=0)
    focus_score = Column(Float, default=0)

    source_window_ids_json = Column(String, nullable=True)
    source_refs_json = Column(String, nullable=True)
    metrics_json = Column(String, nullable=True)

    data_quality_score = Column(Float, default=0)
    quality_warning = Column(String, nullable=True)

    sync_status = Column(String, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), index=True)
    updated_at = Column(DateTime(timezone=True), index=True)
