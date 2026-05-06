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

    # Future extensibility
    extra_data: Optional[str] = None

    # Server-managed fields — optional from client
    source: Optional[str] = "google_calendar"
    schema_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CalendarEventResponse(CalendarEventPayload):
    id: int
