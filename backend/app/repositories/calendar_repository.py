from app.models.calendar import CalendarPayload
from app.core.database import SessionLocal
from app.models.db_models import CalendarRecord


class CalendarRepository:
    def save(self, payload: CalendarPayload):
        db = SessionLocal()
        try:
            record = CalendarRecord(
                timestamp=payload.timestamp,
                event_type=payload.event_type,
                data=payload.data,
            )
            db.add(record)
            db.commit()
            return {"status": "saved", "collection": "calendar"}
        finally:
            db.close()
