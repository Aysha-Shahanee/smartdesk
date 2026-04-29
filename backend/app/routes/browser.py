from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.browser import BrowserPayload
from app.models.browser_minute_window import BrowserMinuteWindowPayload
from app.services.browser_minute_window_service import BrowserMinuteWindowService
from app.services.browser_service import BrowserService

router = APIRouter()

def get_service():
    return BrowserService()


# LEGACY: Session-based browser ingestion. Keep for backward compatibility.
@router.get("/")
def browser_endpoint_info():
    return {
        "message": "Browser endpoint is up. Use POST to submit browser activity payloads.",
        "expected_method": "POST",
        "expected_content_type": "application/json",
        "example": {
            "timestamp": "2026-04-23T12:00:00Z",
            "event_type": "browser_history_sync",
            "data": {
                "history": []
            },
        },
    }

# LEGACY: Session-based browser ingestion. Keep for backward compatibility.
@router.post("/")
def collect_data(payload: BrowserPayload, service: BrowserService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}


@router.post("/minute-window")
def collect_minute_window(
    payload: BrowserMinuteWindowPayload,
    db: Session = Depends(get_db),
):
    service = BrowserMinuteWindowService(db)
    result = service.process_and_save(payload)
    return {
        "message": "Browser minute-window data collected successfully",
        "result": result,
    }
