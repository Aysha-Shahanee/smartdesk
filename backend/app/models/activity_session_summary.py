from typing import Optional

from pydantic import BaseModel


class ActivitySessionBuildRequest(BaseModel):
    user_id: str
    start_time: str
    end_time: str


class ActivitySessionSummaryResponse(BaseModel):
    id: int
    user_id: str
    session_start: str
    session_end: str
    timezone: str
    duration_sec: int

    primary_app: Optional[str] = None
    primary_category: Optional[str] = None

    total_active_time_sec: Optional[int] = None
    total_idle_time_sec: Optional[int] = None
    total_locked_time_sec: Optional[int] = None
    context_switch_count: Optional[int] = None

    browser_time_sec: Optional[int] = None
    top_domain: Optional[str] = None
    active_tab_category: Optional[str] = None

    calendar_meeting_time_sec: Optional[int] = None
    in_meeting: Optional[int] = None

    activity_type: Optional[str] = None
    activity_description: Optional[str] = None

    source: Optional[str] = None
    schema_version: Optional[str] = None
    created_at: str
    updated_at: str
