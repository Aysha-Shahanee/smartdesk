from sqlalchemy import Column, Index, Integer, String, CheckConstraint
from app.core.database import Base


class OSBrowserSummaryRecord(Base):
    __tablename__ = "os_browser_summary"
    __table_args__ = (
        Index("ix_os_browser_summary_user_start", "user_id", "segment_start"),
        Index("ix_os_browser_summary_parent_os", "parent_os_session_id"),
        Index("ix_os_browser_summary_browser_session", "browser_session_id"),
        Index("ux_os_browser_summary_os_only", "parent_os_session_id", "segment_start", "segment_end",
              unique=True,
              postgresql_where="browser_session_id IS NULL",
              sqlite_where="browser_session_id IS NULL"),
        Index("ux_os_browser_summary_with_browser", "parent_os_session_id", "segment_start", "segment_end", "browser_session_id",
              unique=True,
              postgresql_where="browser_session_id IS NOT NULL",
              sqlite_where="browser_session_id IS NOT NULL"),
        CheckConstraint("duration_sec >= 0", name="ck_os_browser_summary_duration_nonneg"),
        CheckConstraint("category_status IN ('pending', 'completed', 'failed')", name="ck_os_browser_summary_category_status"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)

    parent_os_session_id = Column(String, nullable=False)
    browser_session_id = Column(String, nullable=True)

    segment_start = Column(String, nullable=False)
    segment_end = Column(String, nullable=False)
    duration_sec = Column(Integer, nullable=False)

    os_app_name = Column(String, nullable=False)
    os_app_category = Column(String, nullable=True)
    os_window_title = Column(String, nullable=True)
    os_process_id = Column(Integer, nullable=True)
    os_state = Column(String, nullable=False)
    os_idle_time = Column(Integer, nullable=False, server_default="0", default=0)
    os_trigger = Column(String, nullable=True)
    os_closed_by = Column(String, nullable=True)

    browser_name = Column(String, nullable=True)
    browser_window_id = Column(Integer, nullable=True)
    browser_board_id = Column(Integer, nullable=True)
    browser_process_id = Column(Integer, nullable=True)
    browser_domain = Column(String, nullable=True)
    browser_url = Column(String, nullable=True)
    browser_title = Column(String, nullable=True)

    category = Column(String, nullable=True)
    category_status = Column(String, nullable=False, server_default="pending")
    category_model = Column(String, nullable=True)

    summary_created_at = Column(String, nullable=False)
    summary_updated_at = Column(String, nullable=False)