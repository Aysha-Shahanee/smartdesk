from sqlalchemy import Column
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
    # Google event id — (user_id, event_id) is the upsert key: a re-sync
    # updates the existing row in place, never inserting a duplicate.
    event_id = Column(String, nullable=False, index=True)

    title = Column(String, nullable=True)
    description = Column(String, nullable=True)
    location = Column(String, nullable=True)

    start_time = Column(String, nullable=True)   # Asia/Colombo ISO
    end_time = Column(String, nullable=True)     # Asia/Colombo ISO
    timezone = Column(String, nullable=True)     # original event timezone
    is_all_day = Column(Integer, nullable=True, default=0)
    duration_sec = Column(Integer, nullable=True)
    status = Column(String, nullable=True)       # confirmed / tentative / cancelled

    organizer_email = Column(String, nullable=True)
    attendees_count = Column(Integer, nullable=True)
    attendees_json = Column(String, nullable=True)

    is_recurring = Column(Integer, nullable=True)
    recurring_event_id = Column(String, nullable=True)
    html_link = Column(String, nullable=True)

    # Google's own "updated" stamp — row is only rewritten when it changes.
    google_updated_at = Column(String, nullable=True)
    last_synced_at = Column(String, nullable=True)

    extra_data = Column(String, nullable=True)
    source = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
