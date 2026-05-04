from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.browser_minute_window import BrowserMinuteWindowPayload
from app.services.browser_minute_window_service import BrowserMinuteWindowService

router = APIRouter()


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
