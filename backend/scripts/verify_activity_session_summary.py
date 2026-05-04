import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import Base, engine, SessionLocal
from app.models import db_models
from app.services.activity_session_summary_service import ActivitySessionSummaryService


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


def to_colombo_iso(dt: datetime) -> str:
    return dt.astimezone(COLOMBO_TZ).replace(microsecond=0).isoformat()


def cleanup_demo_data(user_id: str, start_dt: datetime, end_dt: datetime):
    db = SessionLocal()
    start_iso = to_colombo_iso(start_dt)
    end_iso = to_colombo_iso(end_dt)
    try:
        db.query(db_models.ActivitySessionSummaryRecord).filter(
            db_models.ActivitySessionSummaryRecord.user_id == user_id,
            db_models.ActivitySessionSummaryRecord.session_start >= start_iso,
            db_models.ActivitySessionSummaryRecord.session_end <= end_iso,
        ).delete(synchronize_session=False)

        db.query(db_models.OSMinuteWindowRecord).filter(
            db_models.OSMinuteWindowRecord.user_id == user_id,
            db_models.OSMinuteWindowRecord.window_start >= start_iso,
            db_models.OSMinuteWindowRecord.window_end <= end_iso,
        ).delete(synchronize_session=False)

        db.query(db_models.BrowserMinuteWindowRecord).filter(
            db_models.BrowserMinuteWindowRecord.user_id == user_id,
            db_models.BrowserMinuteWindowRecord.window_start >= start_iso,
            db_models.BrowserMinuteWindowRecord.window_end <= end_iso,
        ).delete(synchronize_session=False)

        db.query(db_models.VSCodeMinuteWindowRecord).filter(
            db_models.VSCodeMinuteWindowRecord.user_id == user_id,
            db_models.VSCodeMinuteWindowRecord.window_start >= start_iso,
            db_models.VSCodeMinuteWindowRecord.window_end <= end_iso,
        ).delete(synchronize_session=False)

        db.query(db_models.CalendarEventRecord).filter(
            db_models.CalendarEventRecord.user_id == user_id,
            db_models.CalendarEventRecord.event_id == "event-verify-1",
        ).delete(synchronize_session=False)

        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def seed_sources(user_id: str, start_dt: datetime):
    db = SessionLocal()
    try:
        # Session 1: Coding in Code.exe (two continuous OS windows)
        os_rows = [
            db_models.OSMinuteWindowRecord(
                user_id=user_id,
                window_start=to_colombo_iso(start_dt),
                window_end=to_colombo_iso(start_dt + timedelta(minutes=1)),
                timezone="Asia/Colombo",
                active_time_sec=55,
                idle_time_sec=5,
                locked_time_sec=0,
                context_switch_count=2,
                top_app="Code.exe",
                top_app_sec=40,
                dominant_app_category="ide",
                dominant_app_category_sec=40,
                active_app_durations_json="{}",
                category_durations_json="{}",
                source="os_collector",
                schema_version="1.0",
                created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            ),
            db_models.OSMinuteWindowRecord(
                user_id=user_id,
                window_start=to_colombo_iso(start_dt + timedelta(minutes=1)),
                window_end=to_colombo_iso(start_dt + timedelta(minutes=2)),
                timezone="Asia/Colombo",
                active_time_sec=50,
                idle_time_sec=10,
                locked_time_sec=0,
                context_switch_count=1,
                top_app="Code.exe",
                top_app_sec=35,
                dominant_app_category="ide",
                dominant_app_category_sec=35,
                active_app_durations_json="{}",
                category_durations_json="{}",
                source="os_collector",
                schema_version="1.0",
                created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            ),
        ]

        # Session 2: Browser activity (gap + app change)
        os_rows.append(
            db_models.OSMinuteWindowRecord(
                user_id=user_id,
                window_start=to_colombo_iso(start_dt + timedelta(minutes=3)),
                window_end=to_colombo_iso(start_dt + timedelta(minutes=4)),
                timezone="Asia/Colombo",
                active_time_sec=40,
                idle_time_sec=20,
                locked_time_sec=0,
                context_switch_count=1,
                top_app="chrome.exe",
                top_app_sec=35,
                dominant_app_category="browser",
                dominant_app_category_sec=35,
                active_app_durations_json="{}",
                category_durations_json="{}",
                source="os_collector",
                schema_version="1.0",
                created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            )
        )

        vscode_row = db_models.VSCodeMinuteWindowRecord(
            user_id=user_id,
            window_start=to_colombo_iso(start_dt),
            window_end=to_colombo_iso(start_dt + timedelta(minutes=1)),
            timezone="Asia/Colombo",
            workspace_name="demo-workspace",
            project_path="/tmp/demo",
            repo_id="demo-repo",
            git_branch="main",
            active_file_path="src/app.py",
            active_file_name="app.py",
            active_language="python",
            vscode_foreground_sec=50,
            active_editor_sec=40,
            idle_sec=10,
            edit_count=5,
            save_count=2,
            file_switch_count=1,
            terminal_command_count=1,
            debug_run_count=0,
            source="vscode_extension",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )

        browser_row = db_models.BrowserMinuteWindowRecord(
            user_id=user_id,
            window_start=to_colombo_iso(start_dt + timedelta(minutes=3)),
            window_end=to_colombo_iso(start_dt + timedelta(minutes=4)),
            timezone="Asia/Colombo",
            browser_name="Chrome",
            active_tab_domain="chatgpt.com",
            active_tab_url="https://chatgpt.com",
            active_tab_title="ChatGPT",
            active_tab_category="Focused",
            browser_active_time_sec=45,
            browser_idle_time_sec=15,
            productive_time_sec=30,
            neutral_time_sec=10,
            distracting_time_sec=5,
            communication_time_sec=0,
            tab_switch_count=3,
            unique_domains_count=1,
            source="browser_extension",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )

        calendar_row = db_models.CalendarEventRecord(
            user_id=user_id,
            event_id="event-verify-1",
            title="Project Sync",
            start_time=to_colombo_iso(start_dt + timedelta(minutes=3, seconds=10)),
            end_time=to_colombo_iso(start_dt + timedelta(minutes=3, seconds=50)),
            timezone="Asia/Colombo",
            attendees_count=3,
            is_recurring=0,
            source="google_calendar",
            schema_version="1.0",
            created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
            updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
        )

        db.add_all(os_rows + [vscode_row, browser_row, calendar_row])
        db.commit()
    finally:
        db.close()


def seed_continuous_browser(user_id: str, start_dt: datetime):
    db = SessionLocal()
    try:
        os_rows = []
        browser_rows = []
        for idx in range(3):
            window_start = start_dt + timedelta(minutes=idx)
            window_end = start_dt + timedelta(minutes=idx + 1)
            os_rows.append(
                db_models.OSMinuteWindowRecord(
                    user_id=user_id,
                    window_start=to_colombo_iso(window_start),
                    window_end=to_colombo_iso(window_end),
                    timezone="Asia/Colombo",
                    active_time_sec=55,
                    idle_time_sec=5,
                    locked_time_sec=0,
                    context_switch_count=1,
                    top_app="chrome.exe",
                    top_app_sec=50,
                    dominant_app_category="browser",
                    dominant_app_category_sec=50,
                    active_app_durations_json="{}",
                    category_durations_json="{}",
                    source="os_collector",
                    schema_version="1.0",
                    created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                    updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                )
            )
            browser_rows.append(
                db_models.BrowserMinuteWindowRecord(
                    user_id=user_id,
                    window_start=to_colombo_iso(window_start),
                    window_end=to_colombo_iso(window_end),
                    timezone="Asia/Colombo",
                    browser_name="Chrome",
                    active_tab_domain="example.com",
                    active_tab_url="https://example.com",
                    active_tab_title="Example",
                    active_tab_category="Focused",
                    browser_active_time_sec=50,
                    browser_idle_time_sec=10,
                    productive_time_sec=40,
                    neutral_time_sec=8,
                    distracting_time_sec=2,
                    communication_time_sec=0,
                    tab_switch_count=2,
                    unique_domains_count=1,
                    source="browser_extension",
                    schema_version="1.0",
                    created_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                    updated_at=to_colombo_iso(datetime.now(COLOMBO_TZ)),
                )
            )

        db.add_all(os_rows + browser_rows)
        db.commit()
    finally:
        db.close()


def assert_no_overlaps(rows):
    for i, row_a in enumerate(rows):
        for row_b in rows[i + 1 :]:
            if row_a.user_id != row_b.user_id:
                continue
            if row_a.session_start < row_b.session_end and row_b.session_start < row_a.session_end:
                raise AssertionError(
                    f"Overlapping sessions detected: {row_a.session_start}-{row_a.session_end} and {row_b.session_start}-{row_b.session_end}"
                )


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "verify_user"
    start_dt = datetime(2026, 4, 29, 10, 40, 0, tzinfo=COLOMBO_TZ)
    end_dt = start_dt + timedelta(minutes=5)

    cleanup_demo_data(user_id, start_dt, end_dt)
    seed_sources(user_id, start_dt)

    service = ActivitySessionSummaryService()
    start_iso = to_colombo_iso(start_dt)
    end_iso = to_colombo_iso(end_dt)

    result_1 = service.build(user_id, start_iso, end_iso)
    result_2 = service.build(user_id, start_iso, end_iso)

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.ActivitySessionSummaryRecord)
            .filter(
                db_models.ActivitySessionSummaryRecord.user_id == user_id,
                db_models.ActivitySessionSummaryRecord.session_start >= start_iso,
                db_models.ActivitySessionSummaryRecord.session_end <= end_iso,
            )
            .order_by(db_models.ActivitySessionSummaryRecord.session_start)
            .all()
        )
        assert len(rows) == 2, f"Expected 2 sessions, got {len(rows)}"

        first = rows[0]
        second = rows[1]

        assert first.session_start.endswith("+05:30"), "session_start missing +05:30"
        assert first.session_end.endswith("+05:30"), "session_end missing +05:30"
        assert first.vscode_time_sec >= 40, "VS Code time should map to first session"
        assert first.activity_type in {"Coding", "Other"}, "Activity type should be Coding or Other"
        assert first.activity_description, "Activity description should be set"

        assert second.browser_time_sec >= 45, "Browser time should map to second session"
        assert second.tab_switch_count == 3, "Tab switch count should map to second session"
        assert second.calendar_meeting_time_sec > 0, "Calendar overlap should map to second session"
        assert second.activity_type == "Meeting", "Activity type should be Meeting"

        assert result_1["built"] >= 1, "Expected at least one session row"
        assert result_2["built"] >= 1, "Expected build to run twice"

        assert_no_overlaps(rows)

        print("Verification passed:")
        print(
            json.dumps(
                {
                    "sessions": len(rows),
                    "first_session": {
                        "start": first.session_start,
                        "end": first.session_end,
                        "activity_type": first.activity_type,
                    },
                    "second_session": {
                        "start": second.session_start,
                        "end": second.session_end,
                        "activity_type": second.activity_type,
                    },
                },
                indent=2,
            )
        )
    finally:
        db.close()

    # Idempotent rebuild test: continuous browser for 3 minutes
    browser_user = "verify_user_browser"
    browser_start = datetime(2026, 4, 29, 12, 0, 0, tzinfo=COLOMBO_TZ)
    browser_end = browser_start + timedelta(minutes=3)
    cleanup_demo_data(browser_user, browser_start, browser_end)
    seed_continuous_browser(browser_user, browser_start)

    browser_start_iso = to_colombo_iso(browser_start)
    browser_end_iso = to_colombo_iso(browser_end)

    service.build(browser_user, browser_start_iso, browser_end_iso)
    service.build(browser_user, browser_start_iso, browser_end_iso)

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.ActivitySessionSummaryRecord)
            .filter(
                db_models.ActivitySessionSummaryRecord.user_id == browser_user,
                db_models.ActivitySessionSummaryRecord.session_start >= browser_start_iso,
                db_models.ActivitySessionSummaryRecord.session_end <= browser_end_iso,
            )
            .order_by(db_models.ActivitySessionSummaryRecord.session_start)
            .all()
        )
        assert len(rows) == 1, f"Expected 1 session, got {len(rows)}"
        assert rows[0].duration_sec >= 180, "Expected a single 3-minute session"
        assert_no_overlaps(rows)
        print("Verification passed: idempotent rebuild for continuous browser session")
    finally:
        db.close()


if __name__ == "__main__":
    main()
