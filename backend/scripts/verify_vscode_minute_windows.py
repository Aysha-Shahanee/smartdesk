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
        db.query(db_models.VSCodeMinuteWindowRecord).filter(
            db_models.VSCodeMinuteWindowRecord.user_id == user_id,
            db_models.VSCodeMinuteWindowRecord.window_start >= to_colombo_iso(window_start),
            db_models.VSCodeMinuteWindowRecord.window_end <= to_colombo_iso(window_end),
        ).delete(synchronize_session=False)
        db.commit()
        print("Cleaned existing verification seed rows")
    finally:
        db.close()


def build_payload(user_id: str, window_start: datetime, window_end: datetime, edits: int, saves: int):
    now_iso = to_colombo_iso(datetime.now(COLOMBO_TZ))
    return db_models.VSCodeMinuteWindowRecord(
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
        idle_sec=10,
        edit_count=edits,
        save_count=saves,
        file_switch_count=1,
        terminal_command_count=1,
        debug_run_count=0,
        source="vscode_extension",
        schema_version="1.0",
        created_at=now_iso,
        updated_at=now_iso,
    )


def upsert_row(db, payload: db_models.VSCodeMinuteWindowRecord):
    record = (
        db.query(db_models.VSCodeMinuteWindowRecord)
        .filter(
            db_models.VSCodeMinuteWindowRecord.user_id == payload.user_id,
            db_models.VSCodeMinuteWindowRecord.window_start == payload.window_start,
            db_models.VSCodeMinuteWindowRecord.window_end == payload.window_end,
        )
        .one_or_none()
    )
    if record:
        record.workspace_name = payload.workspace_name
        record.project_path = payload.project_path
        record.repo_id = payload.repo_id
        record.git_branch = payload.git_branch
        record.active_file_path = payload.active_file_path
        record.active_file_name = payload.active_file_name
        record.active_language = payload.active_language
        record.vscode_foreground_sec = payload.vscode_foreground_sec
        record.active_editor_sec = payload.active_editor_sec
        record.idle_sec = payload.idle_sec
        record.edit_count = payload.edit_count
        record.save_count = payload.save_count
        record.file_switch_count = payload.file_switch_count
        record.terminal_command_count = payload.terminal_command_count
        record.debug_run_count = payload.debug_run_count
        record.source = payload.source
        record.schema_version = payload.schema_version
        record.updated_at = payload.updated_at
    else:
        db.add(payload)


def main():
    Base.metadata.create_all(bind=engine)

    user_id = "demo_user"
    window_start = datetime(2026, 5, 4, 10, 20, 0, tzinfo=COLOMBO_TZ)
    window_end = window_start + timedelta(minutes=1)

    cleanup_demo_data(user_id, window_start, window_end)

    db = SessionLocal()
    try:
        row = build_payload(user_id, window_start, window_end, edits=3, saves=1)
        upsert_row(db, row)
        db.commit()

        row_update = build_payload(user_id, window_start, window_end, edits=7, saves=2)
        upsert_row(db, row_update)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        rows = (
            db.query(db_models.VSCodeMinuteWindowRecord)
            .filter(
                db_models.VSCodeMinuteWindowRecord.user_id == user_id,
                db_models.VSCodeMinuteWindowRecord.window_start == to_colombo_iso(window_start),
                db_models.VSCodeMinuteWindowRecord.window_end == to_colombo_iso(window_end),
            )
            .all()
        )
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        result = rows[0]
        assert result.window_start.endswith("+05:30"), "window_start missing +05:30"
        assert result.window_end.endswith("+05:30"), "window_end missing +05:30"
        assert result.edit_count == 7, "edit_count should update"
        assert result.save_count == 2, "save_count should update"
        print("Verification passed:")
        print(json.dumps({
            "id": result.id,
            "window_start": result.window_start,
            "window_end": result.window_end,
            "edit_count": result.edit_count,
        }, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
