from sqlalchemy import Column, Integer, String, DateTime, JSON
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
