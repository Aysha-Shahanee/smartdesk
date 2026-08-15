from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class DashboardSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedDuration(DashboardSchema):
    name: str
    seconds: int = Field(ge=0)


class AppDuration(NamedDuration):
    category: str | None = None


class CategoryDuration(DashboardSchema):
    category: str
    seconds: int = Field(ge=0)


class OSDashboardResponse(DashboardSchema):
    active_time_sec: int = Field(default=0, ge=0)
    idle_time_sec: int = Field(default=0, ge=0)
    top_apps: list[AppDuration] = Field(default_factory=list)
    category_breakdown: list[CategoryDuration] = Field(default_factory=list)


class IDEDashboardResponse(DashboardSchema):
    coding_time_sec: int = Field(default=0, ge=0)
    idle_sec: int = Field(default=0, ge=0)
    edits: int = Field(default=0, ge=0)
    saves: int = Field(default=0, ge=0)
    lines_added: int = Field(default=0, ge=0)
    lines_deleted: int = Field(default=0, ge=0)
    # Distinct files touched in the window. The IDE collector already records
    # the per-file detail; only the aggregate was missing, so the Dashboard had
    # no data-backed source for its "Files Modified" tile.
    files_modified: int = Field(default=0, ge=0)
    top_languages: list[NamedDuration] = Field(default_factory=list)
    top_projects: list[NamedDuration] = Field(default_factory=list)


class BrowserDashboardResponse(DashboardSchema):
    browser_active_time_sec: int = Field(default=0, ge=0)
    productive_time_sec: int = Field(default=0, ge=0)
    distracting_time_sec: int = Field(default=0, ge=0)
    neutral_time_sec: int = Field(default=0, ge=0)
    communication_time_sec: int = Field(default=0, ge=0)
    top_domains: list[NamedDuration] = Field(default_factory=list)


class WorkPeriodSummary(DashboardSchema):
    id: str
    period_start: datetime
    period_end: datetime | None = None
    duration_sec: int | None = Field(default=None, ge=0)
    primary_source: str | None = None
    has_os_data: bool = False
    has_ide_data: bool = False
    has_browser_data: bool = False
    has_calendar_data: bool = False


class TimelineDashboardResponse(DashboardSchema):
    work_periods: list[WorkPeriodSummary] = Field(default_factory=list)


class SessionSummary(DashboardSchema):
    id: str
    source: str
    title: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_sec: int | None = Field(default=None, ge=0)
    is_foreground: bool | None = None


class SessionsDashboardResponse(DashboardSchema):
    sessions: list[SessionSummary] = Field(default_factory=list)
