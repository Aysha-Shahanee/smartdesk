from pydantic import BaseModel
from typing import Optional


class IDEMinuteWindowPayload(BaseModel):
    """IDE-agnostic minute window payload.
    Works with VS Code, Antigravity, JetBrains, or any IDE.
    The `source` field identifies which IDE sent the data.
    """
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
    ide_foreground_sec: Optional[int] = None
    active_editor_sec: Optional[int] = None
    idle_sec: Optional[int] = None
    edit_count: int
    save_count: int
    file_switch_count: int
    terminal_command_count: int
    debug_run_count: int

    # Coding velocity metrics
    lines_added: Optional[int] = 0
    lines_deleted: Optional[int] = 0

    # Future extensibility
    extra_data: Optional[str] = None

    # Server-managed fields — optional from client
    source: Optional[str] = "ide_extension"  # "vscode_extension", "antigravity_extension", etc.
    schema_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
