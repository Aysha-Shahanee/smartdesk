from pydantic import BaseModel
from typing import Optional


class BrowserMinuteWindowPayload(BaseModel):
    user_id: str
    window_start: str
    window_end: str
    timezone: str
    browser_name: Optional[str] = None
    active_tab_domain: Optional[str] = None
    active_tab_url: Optional[str] = None
    active_tab_title: Optional[str] = None
    active_tab_category: Optional[str] = None
    browser_active_time_sec: Optional[int] = None
    browser_idle_time_sec: Optional[int] = None
    productive_time_sec: Optional[int] = None
    neutral_time_sec: Optional[int] = None
    distracting_time_sec: Optional[int] = None
    communication_time_sec: Optional[int] = None
    tab_switch_count: int
    unique_domains_count: int
    source: str
    schema_version: str
    created_at: str
    updated_at: str
