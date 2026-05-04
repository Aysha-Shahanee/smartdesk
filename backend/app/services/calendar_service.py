from datetime import datetime, timezone, timedelta
import os
from zoneinfo import ZoneInfo
from typing import Any, Dict

from app.core.database import SessionLocal
from app.core.google_calendar_client import (
    connect_calendar,
    disconnect_calendar,
    get_calendar_connection_status,
    get_calendar_data,
)
from app.models.db_models import CalendarEventRecord
from app.models.calendar_event import CalendarEventPayload
from app.services.calendar_event_service import CalendarEventService


class CalendarService:
    def __init__(self):
        self.event_service = CalendarEventService()
        self.user_id = os.getenv("USER_ID", "demo_user")

    def get_status(self) -> Dict[str, Any]:
        session = SessionLocal()
        try:
            total = session.query(CalendarEventRecord).filter(
                CalendarEventRecord.user_id == self.user_id
            ).count()
            last = (
                session.query(CalendarEventRecord)
                .filter(CalendarEventRecord.user_id == self.user_id)
                .order_by(CalendarEventRecord.start_time.desc())
                .limit(1)
                .one_or_none()
            )
        finally:
            session.close()

        status = get_calendar_connection_status()
        status["stats"] = {
            "total_events": total,
            "last_event_start": last.start_time if last else None,
        }
        return status

    def connect(self, force_reauth: bool = False) -> Dict[str, Any]:
        result = connect_calendar(force_reauth=force_reauth)
        sync_result = self.sync_now()
        return {
            "message": "Google Calendar connected successfully.",
            "connection": result,
            "sync": sync_result,
        }

    def disconnect(self) -> Dict[str, Any]:
        result = disconnect_calendar()
        return {
            "message": "Google Calendar disconnected.",
            "connection": result,
        }

    def get_events(self, hours_ahead: int = 24):
        now = datetime.now(ZoneInfo("Asia/Colombo"))
        end = now + timedelta(hours=hours_ahead)
        rows = self.event_service.list(
            user_id=self.user_id,
            start_time=now.replace(microsecond=0).isoformat(),
            end_time=end.replace(microsecond=0).isoformat(),
            limit=500,
        )
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows]

    def sync_now(self, hours_ahead: int = 24) -> Dict[str, Any]:
        events = get_calendar_data(hours_ahead=hours_ahead, allow_interactive=False)
        collected_at = datetime.now(ZoneInfo("Asia/Colombo"))
        now_iso = collected_at.replace(microsecond=0).isoformat()
        inserted = 0
        updated = 0

        for event in events:
            event_id = event.get("event_id")
            if not event_id:
                continue

            event_payload = CalendarEventPayload(
                user_id=self.user_id,
                event_id=str(event_id),
                title=event.get("title"),
                start_time=event.get("start_time"),
                end_time=event.get("end_time"),
                timezone=event.get("timezone") or "Asia/Colombo",
                attendees_count=event.get("attendees_count"),
                is_recurring=bool(event.get("is_recurring")),
                source="google_calendar",
                schema_version="1.0",
                created_at=now_iso,
                updated_at=now_iso,
            )
            result = self.event_service.process_and_save(event_payload)
            if result["status"] == "updated":
                updated += 1
            else:
                inserted += 1

        return {
            "fetched_events": len(events),
            "inserted": inserted,
            "updated": updated,
            "hours_ahead": hours_ahead,
        }
