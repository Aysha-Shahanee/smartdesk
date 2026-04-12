from fastapi import APIRouter, Depends
from app.models.browser import BrowserPayload
from app.services.browser_service import BrowserService

router = APIRouter()

def get_service():
    return BrowserService()

@router.post("/")
def collect_data(payload: BrowserPayload, service: BrowserService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}
