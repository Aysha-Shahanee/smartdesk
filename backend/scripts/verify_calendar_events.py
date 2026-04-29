import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import Base, engine, SessionLocal
from app.models import db_models
from app.models.calendar_event import CalendarEventPayload
from app.services.calendar_event_service import CalendarEventService


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def cleanup(user_id: str, event_id: str):
    db = SessionLocal()
    try:
        db.query(db_models.CalendarEventRecord).filter(
            db_models.CalendarEventRecord.user_id == user_id,
            db_models.CalendarEventRecord.event_id == event_id,
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    event_id = "event-verify-1"
    start = datetime(2026, 4, 26, 14, 30, 0, tzinfo=COLOMBO_TZ)
    end = start + timedelta(hours=1)

    cleanup(user_id, event_id)

    payload = CalendarEventPayload(
        user_id=user_id,
        event_id=event_id,
        title="Meeting WS",
        start_time=to_colombo_iso(start),
        end_time=to_colombo_iso(end),
        timezone="Asia/Colombo",
        attendees_count=0,
        is_recurring=False,
        source="google_calendar",
        schema_version="1.0",
        created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
    )

    service = CalendarEventService()
    result_1 = service.process_and_save(payload)
    result_2 = service.process_and_save(payload)

    db = SessionLocal()
    try:
        row = (
            db.query(db_models.CalendarEventRecord)
            .filter(
                db_models.CalendarEventRecord.user_id == user_id,
                db_models.CalendarEventRecord.event_id == event_id,
            )
            .one_or_none()
        )
        assert row is not None, "Expected calendar_events row"
        assert row.start_time.endswith("+05:30"), "start_time missing +05:30"
        assert row.end_time.endswith("+05:30"), "end_time missing +05:30"

        print("Verification passed:")
        print(json.dumps({"result_1": result_1, "result_2": result_2}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
