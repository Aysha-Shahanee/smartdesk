from pydantic import BaseModel
from typing import Optional


class VSCodeMinuteWindowPayload(BaseModel):
    user_id: str
    window_start: str
    window_end: str
    timezone: str
    workspace_name: str
    project_path: str
    repo_id: Optional[str] = None
    git_branch: Optional[str] = None
    active_file_path: Optional[str] = None
    active_file_name: Optional[str] = None
    active_language: Optional[str] = None
    vscode_foreground_sec: Optional[int] = None
    active_editor_sec: Optional[int] = None
    idle_sec: Optional[int] = None
    edit_count: int
    save_count: int
    file_switch_count: int
    terminal_command_count: int
    debug_run_count: int
    source: str
    schema_version: str
    created_at: str
    updated_at: str
