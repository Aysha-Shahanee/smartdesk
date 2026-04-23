from fastapi import APIRouter, Depends
from app.models.browser import BrowserPayload
from app.services.browser_service import BrowserService

router = APIRouter()

def get_service():
    return BrowserService()


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

@router.post("/")
def collect_data(payload: BrowserPayload, service: BrowserService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}
