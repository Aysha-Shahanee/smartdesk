import logging
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db_models import IDEMinuteWindowRecord
from app.models.ide_minute_window import IDEMinuteWindowPayload

logger = logging.getLogger("smartdesk.repo.ide")


def _server_timestamp() -> str:
    """Generate a server-side timestamp in ISO format with timezone."""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class IDEMinuteWindowRepository:
    def __init__(self, db: Session | None = None):
        self.db = db
        self._owns_session = db is None

    def upsert(self, payload: IDEMinuteWindowPayload):
        db = self.db or SessionLocal()
        try:
            record = (
                db.query(IDEMinuteWindowRecord)
                .filter(
                    and_(
                        IDEMinuteWindowRecord.user_id == payload.user_id,
                        IDEMinuteWindowRecord.window_start == payload.window_start,
                        IDEMinuteWindowRecord.window_end == payload.window_end,
                    )
                )
                .one_or_none()
            )

            now_iso = _server_timestamp()

            if record:
                # Accumulate additive counters across multiple IDE windows
                record.edit_count = (record.edit_count or 0) + (payload.edit_count or 0)
                record.save_count = (record.save_count or 0) + (payload.save_count or 0)
                record.file_switch_count = (record.file_switch_count or 0) + (payload.file_switch_count or 0)
                record.terminal_command_count = (record.terminal_command_count or 0) + (payload.terminal_command_count or 0)
                record.debug_run_count = (record.debug_run_count or 0) + (payload.debug_run_count or 0)
                # Accumulate coding velocity metrics
                record.lines_added = (record.lines_added or 0) + (payload.lines_added or 0)
                record.lines_deleted = (record.lines_deleted or 0) + (payload.lines_deleted or 0)
                # Keep the higher time values
                record.ide_foreground_sec = max(record.ide_foreground_sec or 0, payload.ide_foreground_sec or 0)
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
                record.extra_data = payload.extra_data
                record.source = payload.source or "ide_extension"
                record.schema_version = payload.schema_version
                # Always set updated_at server-side
                record.updated_at = now_iso
                db.commit()
                return {"status": "updated", "collection": "ide_minute_windows", "id": record.id}

            record = IDEMinuteWindowRecord(
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
                ide_foreground_sec=payload.ide_foreground_sec,
                active_editor_sec=payload.active_editor_sec,
                idle_sec=payload.idle_sec,
                edit_count=payload.edit_count,
                save_count=payload.save_count,
                file_switch_count=payload.file_switch_count,
                terminal_command_count=payload.terminal_command_count,
                debug_run_count=payload.debug_run_count,
                lines_added=payload.lines_added or 0,
                lines_deleted=payload.lines_deleted or 0,
                extra_data=payload.extra_data,
                source=payload.source or "ide_extension",
                schema_version=payload.schema_version,
                # Always set timestamps server-side
                created_at=now_iso,
                updated_at=now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "ide_minute_windows", "id": record.id}
        finally:
            if self._owns_session:
                db.close()
