from fastapi import APIRouter, Depends
from app.models.vscode import VSCodePayload
from app.services.vscode_service import VSCodeService

router = APIRouter()

def get_service():
    return VSCodeService()

@router.post("/")
def collect_data(payload: VSCodePayload, service: VSCodeService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}
