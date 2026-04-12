from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime


class CalendarPayload(BaseModel):
    timestamp: datetime
    event_type: str
    data: Dict[str, Any]
