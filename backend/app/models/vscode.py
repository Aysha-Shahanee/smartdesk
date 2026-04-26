from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VSCodeSessionData(BaseModel):
    """Structured data from VS Code session payload"""
    event_id: str
    project_name: str
    project_path: str
    file_path: str
    language: Optional[str] = None
    workspace_name: Optional[str] = None
    repo_id: Optional[str] = None
    git_branch: Optional[str] = None
    start_time: str  # ISO format with timezone
    end_time: Optional[str] = None  # ISO format with timezone
    duration_seconds: Optional[int] = None
    active_seconds: int = 0
    idle_seconds: int = 0
    edit_count: int = 0
    save_count: int = 0
    debug_runs: int = 0
    terminal_commands: int = 0
    approx_lines_added: int = 0
    approx_lines_removed: int = 0
    approx_chars_added: int = 0
    approx_chars_removed: int = 0


class VSCodePayload(BaseModel):
    timestamp: datetime  # Server-side snapshot time
    event_type: str  # Should be "vscode_session"
    data: VSCodeSessionData  # Structured session data
