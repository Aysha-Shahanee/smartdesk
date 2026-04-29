import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import String, cast

from app.core.database import Base, engine, SessionLocal
from app.models import db_models
from app.services.productivity_summary_service import ProductivitySummaryService


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def seed_sources(user_id: str, window_start: datetime, window_end: datetime):
    db = SessionLocal()
    try:
        vscode = db_models.VSCodeMinuteWindowRecord(
            user_id=user_id,
            window_start=to_colombo_iso(window_start),
            window_end=to_colombo_iso(window_end),
            timezone="Asia/Colombo",
            workspace_name="demo-workspace",
            project_path="/tmp/demo",
            repo_id="demo-repo",
            git_branch="main",
            active_file_path="src/index.ts",
            active_file_name="index.ts",
            active_language="typescript",
            vscode_foreground_sec=50,
            active_editor_sec=40,
            idle_sec=20,
            edit_count=3,
            save_count=1,
            file_switch_count=2,
            terminal_command_count=1,
            debug_run_count=0,
            source="vscode_extension",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )
        browser = db_models.BrowserMinuteWindowRecord(
            user_id=user_id,
            window_start=to_colombo_iso(window_start),
            window_end=to_colombo_iso(window_end),
            timezone="Asia/Colombo",
            browser_name="Chrome",
            active_tab_domain="example.com",
            active_tab_url="https://example.com",
            active_tab_title="Example",
            active_tab_category="Focused",
            browser_active_time_sec=45,
            browser_idle_time_sec=15,
            productive_time_sec=30,
            neutral_time_sec=10,
            distracting_time_sec=5,
            communication_time_sec=0,
            tab_switch_count=4,
            unique_domains_count=2,
            source="browser_extension",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )
        os_record = db_models.OSMinuteWindowRecord(
            user_id=user_id,
            window_start=to_colombo_iso(window_start),
            window_end=to_colombo_iso(window_end),
            timezone="Asia/Colombo",
            active_time_sec=55,
            idle_time_sec=5,
            locked_time_sec=0,
            context_switch_count=3,
            top_app="Code.exe",
            top_app_sec=40,
            dominant_app_category="ide",
            dominant_app_category_sec=40,
            active_app_durations_json=json.dumps({"Code.exe": 40, "chrome.exe": 15}),
            category_durations_json=json.dumps({"ide": 40, "browser": 15}),
            source="os_collector",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )
        calendar_record = db_models.CalendarEventRecord(
            user_id=user_id,
            event_id="event-1",
            title="Daily Standup",
            start_time=to_colombo_iso(window_start + timedelta(minutes=2)),
            end_time=to_colombo_iso(window_start + timedelta(minutes=7)),
            timezone="Asia/Colombo",
            attendees_count=0,
            is_recurring=0,
            source="google_calendar",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )

        db.add_all([vscode, browser, os_record, calendar_record])
        db.commit()
    finally:
        db.close()

def cleanup_demo_data(user_id: str, window_start: datetime, window_end: datetime):
    """
    Delete only demo verification data for this fixed test window.
    This makes the verification script safe to run multiple times.
    """
    db = SessionLocal()

    test_window_start = to_colombo_iso(window_start)
    test_window_end = to_colombo_iso(window_end)

    summary_start = to_colombo_iso(
        datetime(2026, 4, 28, 16, 40, 0, tzinfo=COLOMBO_TZ)
    )
    summary_end = to_colombo_iso(
        datetime(2026, 4, 28, 16, 50, 0, tzinfo=COLOMBO_TZ)
    )

    try:
        # Clean VS Code demo minute windows in the summary range
        db.query(db_models.VSCodeMinuteWindowRecord).filter(
            db_models.VSCodeMinuteWindowRecord.user_id == user_id,
            db_models.VSCodeMinuteWindowRecord.window_start >= summary_start,
            db_models.VSCodeMinuteWindowRecord.window_end <= summary_end,
        ).delete(synchronize_session=False)

        # Clean browser demo minute windows in the summary range
        db.query(db_models.BrowserMinuteWindowRecord).filter(
            db_models.BrowserMinuteWindowRecord.user_id == user_id,
            db_models.BrowserMinuteWindowRecord.window_start >= summary_start,
            db_models.BrowserMinuteWindowRecord.window_end <= summary_end,
        ).delete(synchronize_session=False)

        # Clean generated 10-minute summary
        db.query(db_models.ProductivitySummary10MinRecord).filter(
            db_models.ProductivitySummary10MinRecord.user_id == user_id,
            db_models.ProductivitySummary10MinRecord.window_start == summary_start,
            db_models.ProductivitySummary10MinRecord.window_end == summary_end,
        ).delete(synchronize_session=False)

        # Clean structured OS demo rows in the summary range
        db.query(db_models.OSMinuteWindowRecord).filter(
            db_models.OSMinuteWindowRecord.user_id == user_id,
            db_models.OSMinuteWindowRecord.window_start >= summary_start,
            db_models.OSMinuteWindowRecord.window_end <= summary_end,
        ).delete(synchronize_session=False)

        # Clean structured calendar demo rows
        db.query(db_models.CalendarEventRecord).filter(
            db_models.CalendarEventRecord.user_id == user_id,
            db_models.CalendarEventRecord.event_id == "event-1",
        ).delete(synchronize_session=False)

        # Clean raw OS demo rows.
        # os_signals has no user_id column, so we match inside JSON text.
        db.query(db_models.OSSignalRecord).filter(
            db_models.OSSignalRecord.event_type == "window_summary",
            cast(db_models.OSSignalRecord.data, String).like(f"%{user_id}%"),
            cast(db_models.OSSignalRecord.data, String).like(f"%{test_window_start}%"),
        ).delete(synchronize_session=False)

        # Clean raw calendar demo rows.
        db.query(db_models.CalendarRecord).filter(
            db_models.CalendarRecord.event_type == "calendar_event",
            cast(db_models.CalendarRecord.data, String).like("%event-1%"),
            cast(db_models.CalendarRecord.data, String).like("%Daily Standup%"),
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

    cleanup_demo_data(user_id, window_start, window_end)
    seed_sources(user_id, window_start, window_end)

    service = ProductivitySummaryService()
    start = to_colombo_iso(datetime(2026, 4, 28, 16, 40, 0, tzinfo=COLOMBO_TZ))
    end = to_colombo_iso(datetime(2026, 4, 28, 16, 50, 0, tzinfo=COLOMBO_TZ))

    result_1 = service.build(user_id, start, end)
    result_2 = service.build(user_id, start, end)

    db = SessionLocal()
    try:
        row = (
            db.query(db_models.ProductivitySummary10MinRecord)
            .filter(
                db_models.ProductivitySummary10MinRecord.user_id == user_id,
                db_models.ProductivitySummary10MinRecord.window_start == start,
                db_models.ProductivitySummary10MinRecord.window_end == end,
            )
            .one_or_none()
        )
        assert row is not None, "No productivity_summary_10min row found"
        assert row.window_start.endswith("+05:30"), "window_start missing +05:30"
        assert row.window_end.endswith("+05:30"), "window_end missing +05:30"
        assert row.vscode_active_sec == 40, "VS Code active seconds should sum to 40"
        assert row.browser_active_sec == 45, "Browser active seconds should sum to 45"
        assert row.os_active_sec == 55, "OS active seconds should sum to 55"
        assert row.calendar_meeting_sec == 300, "Calendar overlap should be 300 seconds"
        assert row.missing_sources is not None, "missing_sources should be set"
        assert row.focus_score is not None, "focus_score should be set"
        assert row.activity_label is not None, "activity_label should be set"

        first_id = row.id
        assert result_1["built"] >= 1, "Expected at least one summary row"
        assert result_2["built"] >= 1, "Expected build to run twice"

        print("Verification passed:")
        print(json.dumps({
            "last_row_id": first_id,
            "window_start": row.window_start,
            "window_end": row.window_end,
            "focus_score": row.focus_score,
            "activity_label": row.activity_label,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
