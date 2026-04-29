from app.models.vscode import VSCodePayload
from app.repositories.vscode_repository import VSCodeRepository
import logging

logger = logging.getLogger(__name__)


# LEGACY: Session-based VS Code ingestion. Keep for backward compatibility.
class VSCodeService:
    def __init__(self):
        self.repository = VSCodeRepository()

    def validate_payload(self, payload: VSCodePayload) -> tuple[bool, str]:
        """
        Validate incoming VS Code payload.
        
        Returns:
            tuple: (is_valid: bool, error_message: str)
        """
        # Validate event_id
        if not payload.data.event_id or not payload.data.event_id.strip():
            return False, "event_id is required and cannot be empty"
        
        # Validate file_path
        if not payload.data.file_path or not payload.data.file_path.strip():
            return False, "file_path is required and cannot be empty"
        
        # Validate project_path
        if not payload.data.project_path or not payload.data.project_path.strip():
            return False, "project_path is required and cannot be empty"
        
        # Validate start_time format
        if not payload.data.start_time or not payload.data.start_time.strip():
            return False, "start_time is required and cannot be empty"
        
        # Validate counters are non-negative
        counters = {
            "active_seconds": payload.data.active_seconds,
            "idle_seconds": payload.data.idle_seconds,
            "edit_count": payload.data.edit_count,
            "save_count": payload.data.save_count,
            "debug_runs": payload.data.debug_runs,
            "terminal_commands": payload.data.terminal_commands,
        }
        
        for counter_name, counter_value in counters.items():
            if counter_value < 0:
                return False, f"{counter_name} cannot be negative (got {counter_value})"
        
        # Validate event_type is "vscode_session"
        if payload.event_type != "vscode_session":
            return False, f"event_type must be 'vscode_session' (got '{payload.event_type}')"
        
        return True, ""

    def process_and_save(self, payload: VSCodePayload):
        """
        Process and save VS Code session data.
        
        Workflow:
        1. Validate payload structure and content
        2. Insert snapshot into vscode_session_snapshots
        3. Upsert session into vscode_sessions
        4. Return status
        
        Args:
            payload: VSCodePayload containing session data
            
        Returns:
            dict: Status and details of the operation
        """
        # Validate payload
        is_valid, error_msg = self.validate_payload(payload)
        if not is_valid:
            logger.warning(f"Invalid VSCode payload: {error_msg}")
            return {
                "status": "validation_failed",
                "error": error_msg
            }
        
        # Save to repository
        result = self.repository.save(payload)
        
        if result.get("status") == "saved":
            logger.info(
                f"VSCode session processed successfully: "
                f"event_id={payload.data.event_id}, "
                f"file={payload.data.file_path}"
            )
        
        return result
