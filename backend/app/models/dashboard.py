"""
Dashboard response schemas for the desktop app API contract.
"""

from pydantic import BaseModel
from typing import List, Optional


class AppUsage(BaseModel):
    name: str
    seconds: int


class CategoryUsage(BaseModel):
    category: str
    seconds: int


class OSDashboardResponse(BaseModel):
    active_time_sec: int
    idle_time_sec: int
    locked_time_sec: int
    top_apps: List[AppUsage]
    category_breakdown: List[CategoryUsage]


class IDEDashboardResponse(BaseModel):
    coding_time_sec: int
    idle_sec: int
    edits: int
    saves: int
    terminal_commands: int
    debug_runs: int
    lines_added: int
    lines_deleted: int
    top_languages: List[AppUsage]
    top_projects: List[AppUsage]


class BrowserDashboardResponse(BaseModel):
    browser_active_time_sec: int
    productive_time_sec: int
    distracting_time_sec: int
    neutral_time_sec: int
    top_domains: List[AppUsage]


class SessionEntry(BaseModel):
    window_start: str
    window_end: str
    foreground_source: str
    foreground_app: Optional[str] = None
    foreground_category: Optional[str] = None
    has_os: bool
    has_ide: bool
    has_browser: bool


class SessionsResponse(BaseModel):
    sessions: List[SessionEntry]
