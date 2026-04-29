from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

# LEGACY: Session-based VS Code payload. Keep for backward compatibility.
class VSCodePayload(BaseModel):
    timestamp: datetime
    event_type: str
    data: Dict[str, Any]
