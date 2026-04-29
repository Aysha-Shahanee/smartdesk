from pydantic import BaseModel
from typing import Optional


class ProductivitySummaryBuildRequest(BaseModel):
    user_id: str
    start_time: str
    end_time: str


class ProductivitySummary10MinResponse(BaseModel):
    id: int
    user_id: str
    window_start: str
    window_end: str
    timezone: str

    os_active_sec: Optional[int] = None
    os_idle_sec: Optional[int] = None
    os_locked_sec: Optional[int] = None
    context_switch_count: Optional[int] = None
    top_app: Optional[str] = None
    dominant_app_category: Optional[str] = None

    browser_active_sec: Optional[int] = None
    productive_browser_sec: Optional[int] = None
    neutral_browser_sec: Optional[int] = None
    distracting_browser_sec: Optional[int] = None
    communication_browser_sec: Optional[int] = None
    tab_switch_count: Optional[int] = None
    unique_domains_count: Optional[int] = None
    top_domain: Optional[str] = None
    active_tab_category: Optional[str] = None

    vscode_foreground_sec: Optional[int] = None
    vscode_active_sec: Optional[int] = None
    vscode_idle_sec: Optional[int] = None
    edit_count: Optional[int] = None
    save_count: Optional[int] = None
    file_switch_count: Optional[int] = None
    terminal_command_count: Optional[int] = None
    debug_run_count: Optional[int] = None
    active_project: Optional[str] = None
    active_file_name: Optional[str] = None
    active_language: Optional[str] = None
    git_branch: Optional[str] = None

    calendar_meeting_sec: Optional[int] = None
    in_meeting: Optional[int] = None
    meeting_title: Optional[str] = None

    focus_score: Optional[int] = None
    activity_label: Optional[str] = None
    label_source: Optional[str] = None

    data_quality_score: Optional[int] = None
    missing_sources: Optional[str] = None

    source: Optional[str] = None
    schema_version: Optional[str] = None
    created_at: str
    updated_at: str
