from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OSEventType(str, Enum):
    FOCUSED = "focused"
    BLURRED = "blurred"
    IDLE_START = "idle_start"
    IDLE_END = "idle_end"
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    SUSPEND = "suspend"
    SHUTDOWN = "shutdown"


class VSCodeEventType(str, Enum):
    STARTED = "started"
    STATE = "state"
    ENDED = "ended"


class BrowserEventType(str, Enum):
    STARTED = "started"
    ENDED = "ended"
    STATE = "state"


class BrowserCategory(str, Enum):
    FOCUSED = "Focused"
    DISTRACTED = "Distracted"
    NEUTRAL = "Neutral"
    COMMUNICATION = "Communication"


class OSEventPayload(StrictSchema):
    user_id: str = Field(min_length=0, default="local_user")

    @field_validator("user_id", mode="before")
    def default_user_id(cls, v):
        if not v or not str(v).strip():
            return "local_user"
        return str(v).strip()
    event: OSEventType
    timestamp: datetime

    app_name: str | None = None
    app_category: str | None = None
    window_title: str | None = None
    process_id: int | None = None
    extra_data: dict[str, Any] | None = None


class VSCodeCounters(StrictSchema):
    edit_count: int = Field(default=0, ge=0)
    save_count: int = Field(default=0, ge=0)
    lines_added: int = Field(default=0, ge=0)
    lines_deleted: int = Field(default=0, ge=0)
    file_switch_count: int = Field(default=0, ge=0)
    terminal_command_count: int = Field(default=0, ge=0)
    debug_run_count: int = Field(default=0, ge=0)
    idle_sec: int = Field(default=0, ge=0)


class VSCodeEventPayload(StrictSchema):
    user_id: str = Field(min_length=0, default="local_user")

    @field_validator("user_id", mode="before")
    def default_user_id(cls, v):
        if not v or not str(v).strip():
            return "local_user"
        return str(v).strip()
    event: VSCodeEventType
    instance_id: str = Field(min_length=1)
    timestamp: datetime

    process_id: int | None = None
    trigger: str | None = None          # e.g. "activation", "blur", "shutdown"
    workspace_name: str | None = None
    project_path: str | None = None
    repo_id: str | None = None
    git_branch: str | None = None
    active_file_path: str | None = None
    active_file_name: str | None = None
    active_language: str | None = None
    counters: VSCodeCounters | None = None
    
    # New session tracking fields
    edited_file_count: int | None = None
    changed_file_count: int | None = None
    total_edit_count: int | None = None
    total_save_count: int | None = None
    total_lines_added: int | None = None
    total_lines_deleted: int | None = None
    dominant_language: str | None = None
    languages_json: dict[str, Any] | None = None
    edited_files_json: list[dict[str, Any]] | None = None

    extra_data: dict[str, Any] | None = None


class BrowserEventPayload(StrictSchema):
    user_id: str = Field(min_length=0, default="local_user")

    @field_validator("user_id", mode="before")
    def default_user_id(cls, v):
        if not v or not str(v).strip():
            return "local_user"
        return str(v).strip()
    event: BrowserEventType
    browser_name: str = Field(min_length=1)
    timestamp: datetime

    browser_window_id: int | None = None
    tab_id: int | None = None
    process_id: int | None = None
    trigger: str | None = None          # e.g. "navigation", "tab_closed", "blur"
    domain: str | None = None
    url: str | None = None
    title: str | None = None
    category: BrowserCategory | None = None
    extra_data: dict[str, Any] | None = None


class IngestEventResponse(StrictSchema):
    status: str
    session_id: str | None = None
    is_foreground: bool | None = None
    accepted: bool = True
