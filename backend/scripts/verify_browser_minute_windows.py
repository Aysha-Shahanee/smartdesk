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
        db.query(db_models.BrowserMinuteWindowRecord).filter(
            db_models.BrowserMinuteWindowRecord.user_id == user_id,
            db_models.BrowserMinuteWindowRecord.window_start >= to_colombo_iso(window_start),
            db_models.BrowserMinuteWindowRecord.window_end <= to_colombo_iso(window_end),
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def build_payload(user_id: str, window_start: datetime, window_end: datetime, active_sec: int, tab_switches: int):
    now_iso = to_colombo_iso(datetime.now(COLOMBO_TZ))
    return db_models.BrowserMinuteWindowRecord(
        user_id=user_id,
        window_start=to_colombo_iso(window_start),
        window_end=to_colombo_iso(window_end),
        timezone="Asia/Colombo",
        browser_name="Chrome",
        active_tab_domain="example.com",
        active_tab_url="https://example.com",
        active_tab_title="Example",
        active_tab_category="Focused",
        browser_active_time_sec=active_sec,
        browser_idle_time_sec=60 - active_sec,
        productive_time_sec=active_sec,
        neutral_time_sec=0,
        distracting_time_sec=0,
        communication_time_sec=0,
        tab_switch_count=tab_switches,
        unique_domains_count=1,
        source="browser_extension",
        schema_version="1.0",
        created_at=now_iso,
        updated_at=now_iso,
    )


def upsert_row(db, payload: db_models.BrowserMinuteWindowRecord):
    record = (
        db.query(db_models.BrowserMinuteWindowRecord)
        .filter(
            db_models.BrowserMinuteWindowRecord.user_id == payload.user_id,
            db_models.BrowserMinuteWindowRecord.window_start == payload.window_start,
            db_models.BrowserMinuteWindowRecord.window_end == payload.window_end,
        )
        .one_or_none()
    )
    if record:
        record.browser_name = payload.browser_name
        record.active_tab_domain = payload.active_tab_domain
        record.active_tab_url = payload.active_tab_url
        record.active_tab_title = payload.active_tab_title
        record.active_tab_category = payload.active_tab_category
        record.browser_active_time_sec = payload.browser_active_time_sec
        record.browser_idle_time_sec = payload.browser_idle_time_sec
        record.productive_time_sec = payload.productive_time_sec
        record.neutral_time_sec = payload.neutral_time_sec
        record.distracting_time_sec = payload.distracting_time_sec
        record.communication_time_sec = payload.communication_time_sec
        record.tab_switch_count = payload.tab_switch_count
        record.unique_domains_count = payload.unique_domains_count
        record.source = payload.source
        record.schema_version = payload.schema_version
        record.updated_at = payload.updated_at
    else:
        db.add(payload)


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    window_start = datetime(2026, 5, 4, 10, 10, 0, tzinfo=COLOMBO_TZ)
    window_end = window_start + timedelta(minutes=1)

    cleanup_demo_data(user_id, window_start, window_end)

    db = SessionLocal()
    try:
        row = build_payload(user_id, window_start, window_end, active_sec=40, tab_switches=2)
        upsert_row(db, row)
        db.commit()

        row_update = build_payload(user_id, window_start, window_end, active_sec=45, tab_switches=3)
        upsert_row(db, row_update)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.BrowserMinuteWindowRecord)
            .filter(
                db_models.BrowserMinuteWindowRecord.user_id == user_id,
                db_models.BrowserMinuteWindowRecord.window_start == to_colombo_iso(window_start),
                db_models.BrowserMinuteWindowRecord.window_end == to_colombo_iso(window_end),
            )
            .all()
        )
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        result = rows[0]
        assert result.window_start.endswith("+05:30"), "window_start missing +05:30"
        assert result.window_end.endswith("+05:30"), "window_end missing +05:30"
        assert result.browser_active_time_sec == 45, "browser_active_time_sec should update"
        assert result.tab_switch_count == 3, "tab_switch_count should update"
        print("Verification passed:")
        print(json.dumps({
            "id": result.id,
            "window_start": result.window_start,
            "window_end": result.window_end,
            "browser_active_time_sec": result.browser_active_time_sec,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
