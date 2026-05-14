from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String

from app.core.database import Base


class WorkPeriodRecord(Base):
    __tablename__ = "work_periods"
    __table_args__ = (
        Index("ix_work_periods_user_start", "user_id", "period_start"),
        Index("ix_work_periods_primary_source", "primary_source"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)

    period_start = Column(String, nullable=False, index=True)
    period_end = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)

    primary_source = Column(String, nullable=True)
    primary_app = Column(String, nullable=True)
    primary_project = Column(String, nullable=True)
    primary_domain = Column(String, nullable=True)

    has_os_data = Column(Integer, nullable=False, default=0)
    has_vscode_data = Column(Integer, nullable=False, default=0)
    has_browser_data = Column(Integer, nullable=False, default=0)
    has_calendar_data = Column(Integer, nullable=False, default=0)

    session_count = Column(Integer, nullable=False, default=0)
    extra_data = Column(String, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
