import json
from datetime import datetime
from datetime import timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.db import CalendarEventRecord


class CalendarEventRepository:
    def get_event(self, db: Session, user_id: str, event_id: str) -> CalendarEventRecord | None:
        return (
            db.query(CalendarEventRecord)
            .filter(
                CalendarEventRecord.user_id == user_id,
                CalendarEventRecord.event_id == event_id,
            )
            .first()
        )

    def list_events(
        self,
        db: Session,
        user_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        include_cancelled: bool = False,
    ) -> list[CalendarEventRecord]:
        query = db.query(CalendarEventRecord).filter(CalendarEventRecord.user_id == user_id)
        if not include_cancelled:
            query = query.filter(
                or_(
                    CalendarEventRecord.status != "cancelled",
                    CalendarEventRecord.status.is_(None),
                )
            )
        if time_min is not None:
            query = query.filter(CalendarEventRecord.start_time >= time_min)
        if time_max is not None:
            query = query.filter(CalendarEventRecord.start_time <= time_max)
        return query.order_by(CalendarEventRecord.start_time.asc(), CalendarEventRecord.event_id.asc()).all()

    def delete_events_outside_window(
        self,
        db: Session,
        user_id: str,
        time_min: str,
        time_max: str,
    ) -> int:
        return (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == user_id)
            .filter(
                or_(
                    CalendarEventRecord.start_time < time_min,
                    CalendarEventRecord.start_time > time_max,
                    CalendarEventRecord.start_time.is_(None),
                )
            )
            .delete(synchronize_session=False)
        )

    def upsert_event(self, db: Session, user_id: str, event_id: str, data: dict) -> CalendarEventRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        row = self.get_event(db, user_id, event_id)
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
        row.extra_data = json.dumps(data.get("extra_data") or {})
        row.source = data.get("source") or "google_calendar"
        row.updated_at = now_iso
        return row
