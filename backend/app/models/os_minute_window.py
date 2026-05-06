from pydantic import BaseModel
from typing import Optional


class OSMinuteWindowPayload(BaseModel):
    user_id: str
    window_start: str
    window_end: str
    timezone: str
    active_time_sec: Optional[int] = None
    idle_time_sec: Optional[int] = None
    locked_time_sec: Optional[int] = None
    context_switch_count: Optional[int] = None
    top_app: Optional[str] = None
    top_app_sec: Optional[int] = None
    dominant_app_category: Optional[str] = None
    dominant_app_category_sec: Optional[int] = None
    active_app_durations_json: Optional[str] = None
    category_durations_json: Optional[str] = None

    # Future extensibility
    extra_data: Optional[str] = None

    # Server-managed fields — optional from client
    source: Optional[str] = "os_collector"
    schema_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OSMinuteWindowResponse(OSMinuteWindowPayload):
    id: int
