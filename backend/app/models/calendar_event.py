from pydantic import BaseModel
from typing import Optional


class CalendarEventPayload(BaseModel):
    user_id: str
    event_id: str
    title: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timezone: Optional[str] = None
    attendees_count: Optional[int] = None
    is_recurring: Optional[bool] = None
    source: str
    schema_version: str
    created_at: str
    updated_at: str


class CalendarEventResponse(CalendarEventPayload):
    id: int
