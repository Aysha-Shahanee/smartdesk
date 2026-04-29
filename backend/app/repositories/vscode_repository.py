import logging

from app.core.database import SessionLocal
from app.models.db_models import VSCodeRecord
from app.models.vscode import VSCodePayload

logger = logging.getLogger(__name__)


# LEGACY: Session-based VS Code ingestion. Keep for backward compatibility.
class VSCodeRepository:
    def save(self, payload: VSCodePayload):
        """
        Process and save VS Code session data.

        Steps:
        1. Keep legacy vscode_signals table for backward compatibility
        """
        db = SessionLocal()
        try:
            data = payload.data
            server_timestamp = payload.timestamp
            # Keep legacy vscode_signals table for backward compatibility
            is_final = 1 if data.end_time else 0
            legacy_record = VSCodeRecord(
                timestamp=server_timestamp,
                event_type=payload.event_type,
                data={
                    "event_id": data.event_id,
                    "file_path": data.file_path,
                    "project_path": data.project_path,
                    "project_name": data.project_name,
                    "active_seconds": data.active_seconds,
                    "idle_seconds": data.idle_seconds,
                    "edit_count": data.edit_count,
                    "save_count": data.save_count,
                    "debug_runs": data.debug_runs,
                    "terminal_commands": data.terminal_commands,
                    "is_final": is_final
                }
            )
            db.add(legacy_record)
            
            db.commit()
            
            logger.info(
                f"VSCode session processed: event_id={data.event_id}, "
                f"file={data.file_path}, is_final={is_final}"
            )
            
            return {
                "status": "saved",
                "event_id": data.event_id,
                "is_final": is_final == 1
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving VSCode session: {str(e)}")
            raise
        finally:
            db.close()
