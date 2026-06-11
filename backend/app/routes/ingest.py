from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas import BrowserEventPayload
from app.models.schemas import IDEEventPayload
from app.models.schemas import IngestEventResponse
from app.models.schemas import OSEventPayload
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
            "/api/v1/ingest/ide/event",
            "/api/v1/ingest/browser/event",
        ],
    }


@router.post("/os/event", response_model=IngestEventResponse)
def ingest_os_event(payload: OSEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_os_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ide/event", response_model=IngestEventResponse)
def ingest_ide_event(payload: IDEEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_ide_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Compatibility alias for older extension builds that still POST to the
# vscode-named endpoint. Same handler, same table (ide_sessions).
@router.post("/vscode/event", response_model=IngestEventResponse, deprecated=True)
def ingest_vscode_event_alias(payload: IDEEventPayload, db: Session = Depends(get_db)):
    return ingest_ide_event(payload, db)


@router.post("/browser/event", response_model=IngestEventResponse)
def ingest_browser_event(payload: BrowserEventPayload, db: Session = Depends(get_db)):
    try:
        return coordinator.handle_browser_event(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
