from fastapi import APIRouter, Depends
from app.models.os_signals import OSSignalPayload
from app.services.os_signals_service import OSSignalsService

router = APIRouter()

def get_service():
    return OSSignalsService()

@router.post("/")
def collect_data(payload: OSSignalPayload, service: OSSignalsService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}
