from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.ide_minute_window import IDEMinuteWindowPayload
from app.services.ide_minute_window_service import IDEMinuteWindowService

router = APIRouter()


def get_minute_window_service(db: Session = Depends(get_db)):
    return IDEMinuteWindowService(db)


@router.post("/minute-window")
def collect_minute_window(
    payload: IDEMinuteWindowPayload,
    service: IDEMinuteWindowService = Depends(get_minute_window_service),
):
    result = service.process_and_save(payload)
    return {"message": "Minute window collected successfully", "result": result}
