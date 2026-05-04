import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import Base, engine, SessionLocal
from app.models import db_models


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def cleanup_demo_data(user_id: str, event_id: str):
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


def build_payload(user_id: str, event_id: str, start_dt: datetime, end_dt: datetime, title: str):
    now_iso = to_colombo_iso(datetime.now(COLOMBO_TZ))
    return db_models.CalendarEventRecord(
        user_id=user_id,
        event_id=event_id,
        title=title,
        start_time=to_colombo_iso(start_dt),
        end_time=to_colombo_iso(end_dt),
        timezone="Asia/Colombo",
        attendees_count=2,
        is_recurring=0,
        source="google_calendar",
        schema_version="1.0",
        created_at=now_iso,
        updated_at=now_iso,
    )


def upsert_row(db, payload: db_models.CalendarEventRecord):
    record = (
        db.query(db_models.CalendarEventRecord)
        .filter(
            db_models.CalendarEventRecord.user_id == payload.user_id,
            db_models.CalendarEventRecord.event_id == payload.event_id,
        )
        .one_or_none()
    )
    if record:
        record.title = payload.title
        record.start_time = payload.start_time
        record.end_time = payload.end_time
        record.timezone = payload.timezone
        record.attendees_count = payload.attendees_count
        record.is_recurring = payload.is_recurring
        record.source = payload.source
        record.schema_version = payload.schema_version
        record.updated_at = payload.updated_at
    else:
        db.add(payload)


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    event_id = "event-verify-calendar"
    start_dt = datetime(2026, 5, 4, 10, 30, 0, tzinfo=COLOMBO_TZ)
    end_dt = start_dt + timedelta(minutes=30)

    cleanup_demo_data(user_id, event_id)

    db = SessionLocal()
    try:
        row = build_payload(user_id, event_id, start_dt, end_dt, title="Calendar Verify")
        upsert_row(db, row)
        db.commit()

        row_update = build_payload(user_id, event_id, start_dt, end_dt, title="Calendar Verify Updated")
        upsert_row(db, row_update)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.CalendarEventRecord)
            .filter(
                db_models.CalendarEventRecord.user_id == user_id,
                db_models.CalendarEventRecord.event_id == event_id,
            )
            .all()
        )
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        result = rows[0]
        assert result.start_time.endswith("+05:30"), "start_time missing +05:30"
        assert result.end_time.endswith("+05:30"), "end_time missing +05:30"
        assert result.title == "Calendar Verify Updated", "title should update"
        print("Verification passed:")
        print(json.dumps({
            "id": result.id,
            "event_id": result.event_id,
            "start_time": result.start_time,
            "end_time": result.end_time,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
