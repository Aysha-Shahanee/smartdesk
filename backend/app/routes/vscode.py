from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.vscode import VSCodePayload
from app.models.vscode_minute_window import VSCodeMinuteWindowPayload
from app.services.vscode_service import VSCodeService
from app.services.vscode_minute_window_service import VSCodeMinuteWindowService

router = APIRouter()

def get_service():
    return VSCodeService()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_minute_window_service(db: Session = Depends(get_db)):
    return VSCodeMinuteWindowService(db)

# LEGACY: Session-based VS Code ingestion. Keep for backward compatibility.
@router.post("/")
def collect_data(payload: VSCodePayload, service: VSCodeService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}


@router.post("/minute-window")
def collect_minute_window(
    payload: VSCodeMinuteWindowPayload,
    service: VSCodeMinuteWindowService = Depends(get_minute_window_service),
):
    result = service.process_and_save(payload)
    return {"message": "Minute window collected successfully", "result": result}
