from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

class VSCodePayload(BaseModel):
    timestamp: datetime
    event_type: str
    data: Dict[str, Any]
