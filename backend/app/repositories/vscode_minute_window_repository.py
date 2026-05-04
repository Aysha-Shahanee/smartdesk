from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.db_models import VSCodeMinuteWindowRecord
from app.models.vscode_minute_window import VSCodeMinuteWindowPayload


class VSCodeMinuteWindowRepository:
    def __init__(self, db=None):
        self.db = db
        self._owns_session = db is None

    def upsert(self, payload: VSCodeMinuteWindowPayload):
        db = self.db or SessionLocal()
        try:
            record = (
                db.query(VSCodeMinuteWindowRecord)
                .filter(
                    and_(
                        VSCodeMinuteWindowRecord.user_id == payload.user_id,
                        VSCodeMinuteWindowRecord.window_start == payload.window_start,
                        VSCodeMinuteWindowRecord.window_end == payload.window_end,
                    )
                )
                .one_or_none()
            )

            if record:
                # Accumulate additive counters across multiple VS Code windows
                # sending for the same minute slot, rather than last-write-wins.
                record.edit_count = (record.edit_count or 0) + (payload.edit_count or 0)
                record.save_count = (record.save_count or 0) + (payload.save_count or 0)
                record.file_switch_count = (record.file_switch_count or 0) + (payload.file_switch_count or 0)
                record.terminal_command_count = (record.terminal_command_count or 0) + (payload.terminal_command_count or 0)
                record.debug_run_count = (record.debug_run_count or 0) + (payload.debug_run_count or 0)
                # Keep the higher time values (whichever window was more active)
                record.vscode_foreground_sec = max(record.vscode_foreground_sec or 0, payload.vscode_foreground_sec or 0)
                record.active_editor_sec = max(record.active_editor_sec or 0, payload.active_editor_sec or 0)
                record.idle_sec = min(record.idle_sec or 0, payload.idle_sec or 0)
                # Overwrite contextual fields with the latest values
                record.timezone = payload.timezone
                record.workspace_name = payload.workspace_name
                record.project_path = payload.project_path
                record.repo_id = payload.repo_id
                record.git_branch = payload.git_branch
                record.active_file_path = payload.active_file_path
                record.active_file_name = payload.active_file_name
                record.active_language = payload.active_language
                record.source = payload.source
                record.schema_version = payload.schema_version
                record.updated_at = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()
                db.commit()
                return {"status": "updated", "collection": "vscode_minute_windows", "id": record.id}

            created_at = payload.created_at or datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()
            updated_at = payload.updated_at or datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            record = VSCodeMinuteWindowRecord(
                user_id=payload.user_id,
                window_start=payload.window_start,
                window_end=payload.window_end,
                timezone=payload.timezone,
                workspace_name=payload.workspace_name,
                project_path=payload.project_path,
                repo_id=payload.repo_id,
                git_branch=payload.git_branch,
                active_file_path=payload.active_file_path,
                active_file_name=payload.active_file_name,
                active_language=payload.active_language,
                vscode_foreground_sec=payload.vscode_foreground_sec,
                active_editor_sec=payload.active_editor_sec,
                idle_sec=payload.idle_sec,
                edit_count=payload.edit_count,
                save_count=payload.save_count,
                file_switch_count=payload.file_switch_count,
                terminal_command_count=payload.terminal_command_count,
                debug_run_count=payload.debug_run_count,
                source=payload.source,
                schema_version=payload.schema_version,
                created_at=created_at,
                updated_at=updated_at,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "vscode_minute_windows", "id": record.id}
        finally:
            if self._owns_session:
                db.close()
