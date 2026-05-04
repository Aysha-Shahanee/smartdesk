import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import Base, engine, SessionLocal
from app.models import db_models


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def cleanup_demo_data(user_id: str, window_start: datetime, window_end: datetime):
    db = SessionLocal()
    try:
        db.query(db_models.OSMinuteWindowRecord).filter(
            db_models.OSMinuteWindowRecord.user_id == user_id,
            db_models.OSMinuteWindowRecord.window_start >= to_colombo_iso(window_start),
            db_models.OSMinuteWindowRecord.window_end <= to_colombo_iso(window_end),
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def build_payload(user_id: str, window_start: datetime, window_end: datetime, active: int, idle: int):
    now_iso = to_colombo_iso(datetime.now(COLOMBO_TZ))
    return db_models.OSMinuteWindowRecord(
        user_id=user_id,
        window_start=to_colombo_iso(window_start),
        window_end=to_colombo_iso(window_end),
        timezone="Asia/Colombo",
        active_time_sec=active,
        idle_time_sec=idle,
        locked_time_sec=0,
        context_switch_count=2,
        top_app="Code.exe",
        top_app_sec=active,
        dominant_app_category="ide",
        dominant_app_category_sec=active,
        active_app_durations_json="{}",
        category_durations_json="{}",
        source="os_collector",
        schema_version="1.0",
        created_at=now_iso,
        updated_at=now_iso,
    )


def upsert_row(db, payload: db_models.OSMinuteWindowRecord):
    record = (
        db.query(db_models.OSMinuteWindowRecord)
        .filter(
            db_models.OSMinuteWindowRecord.user_id == payload.user_id,
            db_models.OSMinuteWindowRecord.window_start == payload.window_start,
            db_models.OSMinuteWindowRecord.window_end == payload.window_end,
        )
        .one_or_none()
    )
    if record:
        record.active_time_sec = payload.active_time_sec
        record.idle_time_sec = payload.idle_time_sec
        record.locked_time_sec = payload.locked_time_sec
        record.context_switch_count = payload.context_switch_count
        record.top_app = payload.top_app
        record.top_app_sec = payload.top_app_sec
        record.dominant_app_category = payload.dominant_app_category
        record.dominant_app_category_sec = payload.dominant_app_category_sec
        record.active_app_durations_json = payload.active_app_durations_json
        record.category_durations_json = payload.category_durations_json
        record.source = payload.source
        record.schema_version = payload.schema_version
        record.updated_at = payload.updated_at
    else:
        db.add(payload)


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    window_start = datetime(2026, 5, 4, 10, 0, 0, tzinfo=COLOMBO_TZ)
    window_end = window_start + timedelta(minutes=1)

    cleanup_demo_data(user_id, window_start, window_end)

    db = SessionLocal()
    try:
        row = build_payload(user_id, window_start, window_end, active=50, idle=10)
        upsert_row(db, row)
        db.commit()

        row_update = build_payload(user_id, window_start, window_end, active=55, idle=5)
        upsert_row(db, row_update)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.OSMinuteWindowRecord)
            .filter(
                db_models.OSMinuteWindowRecord.user_id == user_id,
                db_models.OSMinuteWindowRecord.window_start == to_colombo_iso(window_start),
                db_models.OSMinuteWindowRecord.window_end == to_colombo_iso(window_end),
            )
            .all()
        )
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        result = rows[0]
        assert result.window_start.endswith("+05:30"), "window_start missing +05:30"
        assert result.window_end.endswith("+05:30"), "window_end missing +05:30"
        assert result.active_time_sec == 55, "active_time_sec should update"
        print("Verification passed:")
        print(json.dumps({
            "id": result.id,
            "window_start": result.window_start,
            "window_end": result.window_end,
            "active_time_sec": result.active_time_sec,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
