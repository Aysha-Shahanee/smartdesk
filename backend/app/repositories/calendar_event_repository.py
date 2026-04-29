from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.db_models import CalendarEventRecord
from app.models.calendar_event import CalendarEventPayload


class CalendarEventRepository:
    def upsert(self, payload: CalendarEventPayload):
        db = SessionLocal()
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

            now_iso = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            if record:
                record.title = payload.title
                record.start_time = payload.start_time
                record.end_time = payload.end_time
                record.timezone = payload.timezone
                record.attendees_count = payload.attendees_count
                record.is_recurring = 1 if payload.is_recurring else 0
                record.source = payload.source
                record.schema_version = payload.schema_version
                record.updated_at = payload.updated_at or now_iso
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
                source=payload.source,
                schema_version=payload.schema_version,
                created_at=payload.created_at or now_iso,
                updated_at=payload.updated_at or now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "calendar_events", "id": record.id}
        finally:
            db.close()

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 200):
        db = SessionLocal()
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
            db.close()
