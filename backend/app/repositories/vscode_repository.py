from app.models.vscode import VSCodePayload
from app.core.database import SessionLocal
from app.models.db_models import VSCodeSession, VSCodeSessionSnapshot, VSCodeRecord
from datetime import datetime
from sqlalchemy import func
import logging

logger = logging.getLogger(__name__)


def parse_iso_datetime(iso_string: str) -> datetime:
    """Parse ISO 8601 datetime string to Python datetime object."""
    try:
        # Try parsing with timezone info
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except Exception:
        logger.warning(f"Failed to parse ISO datetime: {iso_string}")
        return datetime.now()


# LEGACY: Session-based VS Code ingestion. Keep for backward compatibility.
class VSCodeRepository:
    def save(self, payload: VSCodePayload):
        """
        Process and save VS Code session data.
        
        Steps:
        1. Insert raw snapshot into vscode_session_snapshots
        2. Upsert session into vscode_sessions using event_id as key
        3. Keep legacy vscode_signals table for backward compatibility
        """
        db = SessionLocal()
        try:
            data = payload.data
            server_timestamp = payload.timestamp
            
            # Parse extension-provided timestamps
            start_dt = parse_iso_datetime(data.start_time)
            end_dt = parse_iso_datetime(data.end_time) if data.end_time else None
            
            # Determine if this is the final snapshot for the session
            is_final = 1 if end_dt else 0
            
            # Calculate duration if end_time is present
            duration_sec = data.duration_seconds
            if end_dt and duration_sec is None:
                duration_sec = int((end_dt - start_dt).total_seconds())
            
            # Step 1: Insert snapshot into vscode_session_snapshots
            snapshot = VSCodeSessionSnapshot(
                event_id=data.event_id,
                user_id=None,  # Could be extracted from auth context if available
                snapshot_time=server_timestamp,
                file_path=data.file_path,
                language=data.language,
                active_sec=data.active_seconds,
                idle_sec=data.idle_seconds,
                edit_count=data.edit_count,
                save_count=data.save_count,
                debug_run_count=data.debug_runs,
                terminal_command_count=data.terminal_commands,
                approx_lines_added=data.approx_lines_added,
                approx_lines_removed=data.approx_lines_removed,
                approx_chars_added=data.approx_chars_added,
                approx_chars_removed=data.approx_chars_removed,
                is_final=is_final,
                created_at=server_timestamp
            )
            db.add(snapshot)
            db.flush()  # Flush to ensure snapshot is created before session upsert
            
            # Step 2: Upsert session into vscode_sessions  
            existing_session = db.query(VSCodeSession).filter(
                VSCodeSession.event_id == data.event_id
            ).first()
            
            if existing_session:
                # Update existing session - directly modify the tracked object
                logger.debug(f"Updating existing session {data.event_id}")
                logger.debug(f"  Before: active_sec={existing_session.active_sec}, edit_count={existing_session.edit_count}")
                
                existing_session.file_path = data.file_path
                existing_session.file_name = data.file_path.split("/")[-1] if data.file_path else None
                existing_session.language = data.language
                existing_session.project_path = data.project_path
                existing_session.project_name = data.project_name
                existing_session.workspace_name = data.workspace_name
                existing_session.repo_id = data.repo_id
                existing_session.git_branch = data.git_branch
                existing_session.active_sec = data.active_seconds
                existing_session.idle_sec = data.idle_seconds
                existing_session.edit_count = data.edit_count
                existing_session.save_count = data.save_count
                existing_session.debug_run_count = data.debug_runs
                existing_session.terminal_command_count = data.terminal_commands
                existing_session.approx_lines_added = data.approx_lines_added
                existing_session.approx_lines_removed = data.approx_lines_removed
                existing_session.approx_chars_added = data.approx_chars_added
                existing_session.approx_chars_removed = data.approx_chars_removed
                
                logger.debug(f"  After: active_sec={existing_session.active_sec}, edit_count={existing_session.edit_count}")
                
                # Update end_time and duration only when final snapshot is received
                if is_final:
                    existing_session.end_time = end_dt
                    existing_session.duration_sec = duration_sec
                    existing_session.is_final = 1
                
                existing_session.updated_at = server_timestamp
                # SQLAlchemy will track changes to the object
                # The updated object is already in the session, so we don't need to do anything
            else:
                # Create new session
                new_session = VSCodeSession(
                    event_id=data.event_id,
                    user_id=None,
                    file_path=data.file_path,
                    file_name=data.file_path.split("/")[-1] if data.file_path else None,
                    language=data.language,
                    project_path=data.project_path,
                    project_name=data.project_name,
                    workspace_name=data.workspace_name,
                    repo_id=data.repo_id,
                    git_branch=data.git_branch,
                    start_time=start_dt,
                    end_time=end_dt if is_final else None,
                    duration_sec=duration_sec if is_final else None,
                    active_sec=data.active_seconds,
                    idle_sec=data.idle_seconds,
                    edit_count=data.edit_count,
                    save_count=data.save_count,
                    debug_run_count=data.debug_runs,
                    terminal_command_count=data.terminal_commands,
                    approx_lines_added=data.approx_lines_added,
                    approx_lines_removed=data.approx_lines_removed,
                    approx_chars_added=data.approx_chars_added,
                    approx_chars_removed=data.approx_chars_removed,
                    is_final=is_final,
                    created_at=server_timestamp,
                    updated_at=server_timestamp
                )
                db.add(new_session)
                logger.debug(f"Created new session {data.event_id}")
            
            # Flush session changes
            db.flush()
            
            # Step 3: Optionally keep legacy vscode_signals table for backward compatibility
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
            
            # Commit all changes
            db.commit()
            
            logger.info(
                f"VSCode session processed: event_id={data.event_id}, "
                f"file={data.file_path}, is_final={is_final}"
            )
            
            return {
                "status": "saved",
                "event_id": data.event_id,
                "snapshot_saved": True,
                "session_upserted": True,
                "is_final": is_final == 1
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving VSCode session: {str(e)}")
            raise
        finally:
            db.close()
