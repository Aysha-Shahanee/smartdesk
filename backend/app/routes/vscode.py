from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.vscode_minute_window import VSCodeMinuteWindowPayload
from app.services.vscode_minute_window_service import VSCodeMinuteWindowService

router = APIRouter()


def get_minute_window_service(db: Session = Depends(get_db)):
    return VSCodeMinuteWindowService(db)


@router.post("/minute-window")
def collect_minute_window(
    payload: VSCodeMinuteWindowPayload,
    service: VSCodeMinuteWindowService = Depends(get_minute_window_service),
):
    result = service.process_and_save(payload)
    return {"message": "Minute window collected successfully", "result": result}
