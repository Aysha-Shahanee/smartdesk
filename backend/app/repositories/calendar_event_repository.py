import json
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import parse_iso_utc, to_utc
from app.models.db import CalendarEventRecord


def _parse_dt(value: str | datetime | None) -> datetime | None:
    """Accept either an ISO string or a datetime; return a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    return parse_iso_utc(value)


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
            query = query.filter(CalendarEventRecord.start_time >= _parse_dt(time_min))
        if time_max is not None:
            query = query.filter(CalendarEventRecord.start_time <= _parse_dt(time_max))
        return query.order_by(CalendarEventRecord.start_time.asc(), CalendarEventRecord.event_id.asc()).all()

    def delete_events_outside_window(
        self,
        db: Session,
        user_id: str,
        time_min: str,
        time_max: str,
    ) -> int:
        min_dt = _parse_dt(time_min)
        max_dt = _parse_dt(time_max)
        return (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == user_id)
            .filter(
                or_(
                    CalendarEventRecord.start_time < min_dt,
                    CalendarEventRecord.start_time > max_dt,
                    CalendarEventRecord.start_time.is_(None),
                )
            )
            .delete(synchronize_session=False)
        )

    def upsert_event(self, db: Session, user_id: str, event_id: str, data: dict) -> CalendarEventRecord:
        now = datetime.now(timezone.utc)
        row = self.get_event(db, user_id, event_id)
        if row is None:
            row = CalendarEventRecord(
                user_id=user_id,
                event_id=event_id,
                created_at=now,
                updated_at=now,
            )
            db.add(row)

        row.title = data.get("title")
        row.start_time = _parse_dt(data.get("start_time"))
        row.end_time = _parse_dt(data.get("end_time"))
        row.timezone = data.get("timezone")
        row.duration_sec = data.get("duration_sec")
        row.status = data.get("status")
        row.extra_data = json.dumps(data.get("extra_data") or {})
        row.source = data.get("source") or "google_calendar"
        row.updated_at = now
        return row
