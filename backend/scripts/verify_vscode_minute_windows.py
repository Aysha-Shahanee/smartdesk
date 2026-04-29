from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.database import Base, engine, SessionLocal
from app.models import db_models
from app.models.vscode_minute_window import VSCodeMinuteWindowPayload
from app.services.vscode_minute_window_service import VSCodeMinuteWindowService


def to_colombo_iso(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()


def build_payload(window_start, window_end, edit_count, save_count, debug_count=0):
    now = datetime.now(ZoneInfo("Asia/Colombo"))
    return VSCodeMinuteWindowPayload(
        user_id="demo_user",
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
        vscode_foreground_sec=55,
        active_editor_sec=40,
        idle_sec=20,
        edit_count=edit_count,
        save_count=save_count,
        file_switch_count=1,
        terminal_command_count=2,
        debug_run_count=debug_count,
        source="vscode_extension",
        schema_version="1.0",
        created_at=to_colombo_iso(now),
        updated_at=to_colombo_iso(now),
    )


def main():
    Base.metadata.create_all(bind=engine)
    service = VSCodeMinuteWindowService()

    start_1 = datetime(2026, 4, 26, 10, 0, 0, tzinfo=ZoneInfo("Asia/Colombo"))
    end_1 = start_1 + timedelta(minutes=1)
    start_2 = end_1
    end_2 = start_2 + timedelta(minutes=1)

    db = SessionLocal()
    try:
        db.query(db_models.VSCodeMinuteWindowRecord).filter(
            db_models.VSCodeMinuteWindowRecord.user_id == "demo_user",
            db_models.VSCodeMinuteWindowRecord.window_start >= to_colombo_iso(start_1),
            db_models.VSCodeMinuteWindowRecord.window_end <= to_colombo_iso(end_2),
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()

    payload_1 = build_payload(start_1, end_1, edit_count=3, save_count=1)
    result_1 = service.process_and_save(payload_1)

    payload_1_update = build_payload(start_1, end_1, edit_count=7, save_count=2)
    result_1_update = service.process_and_save(payload_1_update)

    payload_2 = build_payload(start_2, end_2, edit_count=1, save_count=0, debug_count=1)
    result_2 = service.process_and_save(payload_2)

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.VSCodeMinuteWindowRecord)
            .filter(
                db_models.VSCodeMinuteWindowRecord.user_id == "demo_user",
                db_models.VSCodeMinuteWindowRecord.window_start >= to_colombo_iso(start_1),
                db_models.VSCodeMinuteWindowRecord.window_end <= to_colombo_iso(end_2),
            )
            .order_by(db_models.VSCodeMinuteWindowRecord.window_start)
            .all()
        )

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert rows[0].edit_count == 7, "Update should overwrite edit_count for the same window"
        assert rows[0].save_count == 2, "Update should overwrite save_count for the same window"
        assert rows[1].debug_run_count == 1, "Second window should be a separate row"
    finally:
        db.close()

    print("Verification passed:")
    print(f"- First insert: {result_1}")
    print(f"- Update same window: {result_1_update}")
    print(f"- Second window insert: {result_2}")
    print("- Counters reset between windows (validated by separate rows).")


if __name__ == "__main__":
    main()
