import logging
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db_models import CalendarEventRecord
from app.models.calendar_event import CalendarEventPayload

logger = logging.getLogger("smartdesk.repo.calendar")


def _server_timestamp() -> str:
    """Generate a server-side timestamp in ISO format with timezone."""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class CalendarEventRepository:
    def __init__(self, db: Session | None = None):
        self.db = db
        self._owns_session = db is None

    def upsert(self, payload: CalendarEventPayload):
        db = self.db or SessionLocal()
        try:
            record = (
                db.query(CalendarEventRecord)
                .filter(
                    and_(
                        CalendarEventRecord.user_id == payload.user_id,
                        CalendarEventRecord.event_id == payload.event_id,
                    )
                )
                .one_or_none()
            )

            now_iso = _server_timestamp()

            if record:
                record.title = payload.title
                record.start_time = payload.start_time
                record.end_time = payload.end_time
                record.timezone = payload.timezone
                record.attendees_count = payload.attendees_count
                record.is_recurring = 1 if payload.is_recurring else 0
                record.extra_data = payload.extra_data
                record.source = payload.source or "google_calendar"
                record.schema_version = payload.schema_version
                # Always set updated_at server-side
                record.updated_at = now_iso
                db.commit()
                return {"status": "updated", "collection": "calendar_events", "id": record.id}

            record = CalendarEventRecord(
                user_id=payload.user_id,
                event_id=payload.event_id,
                title=payload.title,
                start_time=payload.start_time,
                end_time=payload.end_time,
                timezone=payload.timezone,
                attendees_count=payload.attendees_count,
                is_recurring=1 if payload.is_recurring else 0,
                extra_data=payload.extra_data,
                source=payload.source or "google_calendar",
                schema_version=payload.schema_version,
                # Always set timestamps server-side
                created_at=now_iso,
                updated_at=now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "calendar_events", "id": record.id}
        finally:
            if self._owns_session:
                db.close()

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 200):
        db = self.db or SessionLocal()
        try:
            query = db.query(CalendarEventRecord)
            if user_id:
                query = query.filter(CalendarEventRecord.user_id == user_id)
            if start_time:
                query = query.filter(CalendarEventRecord.start_time >= start_time)
            if end_time:
                query = query.filter(CalendarEventRecord.end_time <= end_time)
            query = query.order_by(CalendarEventRecord.start_time.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            if self._owns_session:
                db.close()
