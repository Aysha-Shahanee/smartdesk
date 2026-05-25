import json
from datetime import datetime
from datetime import timezone

from sqlalchemy.orm import Session

from app.models.db import CalendarEventRecord


class CalendarEventRepository:
    def upsert_event(self, db: Session, user_id: str, event_id: str, data: dict) -> CalendarEventRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        row = (
            db.query(CalendarEventRecord)
            .filter(
                CalendarEventRecord.user_id == user_id,
                CalendarEventRecord.event_id == event_id,
            )
            .first()
        )
        if row is None:
            row = CalendarEventRecord(
                user_id=user_id,
                event_id=event_id,
                created_at=now_iso,
                updated_at=now_iso,
            )
            db.add(row)

        row.title = data.get("title")
        row.start_time = data.get("start_time")
        row.end_time = data.get("end_time")
        row.timezone = data.get("timezone")
        row.duration_sec = data.get("duration_sec")
        row.status = data.get("status")
        row.attendees_count = data.get("attendees_count")
        row.is_recurring = data.get("is_recurring")
        row.extra_data = json.dumps(data.get("extra_data") or {})
        row.source = data.get("source") or "google_calendar"
        row.schema_version = data.get("schema_version") or "v1"
        row.updated_at = now_iso
        return row
