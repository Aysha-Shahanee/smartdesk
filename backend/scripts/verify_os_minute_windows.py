import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import Base, engine, SessionLocal
from app.models import db_models
from app.models.os_minute_window import OSMinuteWindowPayload
from app.services.os_minute_window_service import OSMinuteWindowService


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def cleanup(user_id: str, window_start: datetime, window_end: datetime):
    db = SessionLocal()
    try:
        db.query(db_models.OSMinuteWindowRecord).filter(
            db_models.OSMinuteWindowRecord.user_id == user_id,
            db_models.OSMinuteWindowRecord.window_start == to_colombo_iso(window_start),
            db_models.OSMinuteWindowRecord.window_end == to_colombo_iso(window_end),
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    window_start = datetime(2026, 4, 28, 16, 40, 0, tzinfo=COLOMBO_TZ)
    window_end = window_start + timedelta(minutes=1)

    cleanup(user_id, window_start, window_end)

    payload = OSMinuteWindowPayload(
        user_id=user_id,
        window_start=to_colombo_iso(window_start),
        window_end=to_colombo_iso(window_end),
        timezone="Asia/Colombo",
        active_time_sec=54,
        idle_time_sec=6,
        locked_time_sec=0,
        context_switch_count=3,
        top_app="Code.exe",
        top_app_sec=42,
        dominant_app_category="ide",
        dominant_app_category_sec=42,
        active_app_durations_json=json.dumps({"Code.exe": 42, "chrome.exe": 12}),
        category_durations_json=json.dumps({"ide": 42, "browser": 12}),
        source="os_collector",
        schema_version="1.0",
        created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
    )

    service = OSMinuteWindowService()
    result_1 = service.process_and_save(payload)
    result_2 = service.process_and_save(payload)

    db = SessionLocal()
    try:
        row = (
            db.query(db_models.OSMinuteWindowRecord)
            .filter(
                db_models.OSMinuteWindowRecord.user_id == user_id,
                db_models.OSMinuteWindowRecord.window_start == to_colombo_iso(window_start),
                db_models.OSMinuteWindowRecord.window_end == to_colombo_iso(window_end),
            )
            .one_or_none()
        )
        assert row is not None, "Expected os_minute_windows row"
        assert row.window_start.endswith("+05:30"), "window_start missing +05:30"
        assert row.window_end.endswith("+05:30"), "window_end missing +05:30"
        assert row.top_app == "Code.exe", "top_app mismatch"
        assert row.dominant_app_category == "ide", "dominant_app_category mismatch"

        print("Verification passed:")
        print(json.dumps({"result_1": result_1, "result_2": result_2}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
