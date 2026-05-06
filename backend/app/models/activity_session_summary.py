from typing import Optional

from pydantic import BaseModel


class ActivitySessionBuildRequest(BaseModel):
    user_id: str
    start_time: str
    end_time: str


class ActivityTimelineIndexResponse(BaseModel):
    id: int
    user_id: str
    window_start: str
    window_end: str
    timezone: str

    foreground_source: str
    foreground_app: Optional[str] = None
    foreground_window_title: Optional[str] = None
    foreground_category: Optional[str] = None

    has_os_data: bool = False
    has_ide_data: bool = False
    has_browser_data: bool = False

    ide_workspace: Optional[str] = None
    browser_domain: Optional[str] = None

    activity_confidence: Optional[float] = None

    created_at: str
