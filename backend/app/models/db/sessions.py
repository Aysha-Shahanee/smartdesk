from sqlalchemy import Column, Index, Integer, String
from app.core.database import Base


class OSSessionRecord(Base):
    __tablename__ = "os_sessions"
    __table_args__ = (
        Index("ix_os_sessions_user_start", "user_id", "session_start"),
        Index("ix_os_sessions_process_id", "process_id"),
        Index("ix_os_sessions_app_name", "app_name"),
        Index("ix_os_sessions_device_id", "device_id"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)

    app_name = Column(String, nullable=False)
    app_category = Column(String, nullable=True)
    window_title = Column(String, nullable=True)
    process_id = Column(Integer, nullable=True)

    state = Column(String, nullable=False, default="active")
    idle_time = Column(Integer, nullable=False, default=0)  # Total seconds system was idle during session

    session_start = Column(String, nullable=False)
    session_end = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)

    trigger = Column(String, nullable=True)
    closed_by = Column(String, nullable=True)
    extra_data = Column(String, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class IDESessionRecord(Base):
    __tablename__ = "ide_sessions"
    __table_args__ = (
        Index("ix_ide_sessions_user_start", "user_id", "session_start"),
        Index("ix_ide_sessions_instance_id", "instance_id"),
        Index("ix_ide_sessions_process_id", "process_id"),
        Index("ix_ide_sessions_is_foreground", "is_foreground"),
        Index("ix_ide_sessions_device_id", "device_id"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    ide_name = Column(String, nullable=True)
    instance_id = Column(String, nullable=False)
    process_id = Column(Integer, nullable=True)
    parent_process_id = Column(Integer, nullable=True)

    workspace_name = Column(String, nullable=True)
    project_path = Column(String, nullable=True)
    repo_id = Column(String, nullable=True)
    repository = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)
    active_file_path = Column(String, nullable=True)
    active_file_name = Column(String, nullable=True)
    active_language = Column(String, nullable=True)

    session_start = Column(String, nullable=False)
    session_end = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    idle_sec = Column(Integer, nullable=True, default=0)

    is_foreground = Column(Integer, nullable=False, default=0)
    confirmed_by_os = Column(Integer, nullable=False, default=0)
    # "foreground" — IDE was the OS foreground app
    # "background_ai" — IDE blurred but edits kept arriving (AI agent working)
    collection_reason = Column(String, nullable=True)

    trigger = Column(String, nullable=True)
    closed_by = Column(String, nullable=True)

    edit_count = Column(Integer, nullable=False, default=0)
    save_count = Column(Integer, nullable=False, default=0)
    lines_added = Column(Integer, nullable=False, default=0)
    lines_deleted = Column(Integer, nullable=False, default=0)
    file_switch_count = Column(Integer, nullable=False, default=0)

    edited_file_count = Column(Integer, nullable=True, default=0)
    changed_file_count = Column(Integer, nullable=True, default=0)
    dominant_language = Column(String, nullable=True)
    languages_json = Column(String, nullable=True)
    edited_files_json = Column(String, nullable=True)

    extra_data = Column(String, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        Index("ix_browser_sessions_user_start", "user_id", "session_start"),
        Index("ix_browser_sessions_window_id", "browser_window_id"),
        Index("ix_browser_sessions_domain", "domain"),
        Index("ix_browser_sessions_is_foreground", "is_foreground"),
        Index("ix_browser_sessions_device_id", "device_id"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    browser_name = Column(String, nullable=False)
    browser_window_id = Column(Integer, nullable=True)
    tab_id = Column(Integer, nullable=True)
    process_id = Column(Integer, nullable=True)

    domain = Column(String, nullable=True)
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    category = Column(String, nullable=True)

    session_start = Column(String, nullable=False)
    session_end = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)

    is_foreground = Column(Integer, nullable=False, default=0)
    confirmed_by_os = Column(Integer, nullable=False, default=0)

    trigger = Column(String, nullable=True)
    closed_by = Column(String, nullable=True)

    extra_data = Column(String, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
