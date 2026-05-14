from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas import BrowserEventPayload
from app.models.schemas import IngestEventResponse
from app.models.schemas import OSEventPayload
from app.models.schemas import VSCodeEventPayload
from app.services.session_coordinator import SessionCoordinator

router = APIRouter()
coordinator = SessionCoordinator()


@router.get("/status")
def ingest_status():
    return {
        "status": "ready",
        "phase": "session_lifecycle",
        "endpoints": [
            "/api/v1/ingest/os/event",
            "/api/v1/ingest/vscode/event",
            "/api/v1/ingest/browser/event",
        ],
    }


@router.post("/os/event", response_model=IngestEventResponse)
def ingest_os_event(payload: OSEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_os_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/vscode/event", response_model=IngestEventResponse)
def ingest_vscode_event(payload: VSCodeEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_vscode_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/event", response_model=IngestEventResponse)
def ingest_browser_event(payload: BrowserEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_browser_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
