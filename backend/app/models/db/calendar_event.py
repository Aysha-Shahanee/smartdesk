from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint

from app.core.database import Base


class CalendarEventRecord(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_calendar_events_user_event"),
        Index("ix_calendar_events_user_start", "user_id", "start_time"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    event_id = Column(String, nullable=False, index=True)

    title = Column(String, nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    status = Column(String, nullable=True)

    extra_data = Column(String, nullable=True)
    source = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
