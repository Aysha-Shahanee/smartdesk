from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.calendar_auth_service import CalendarAuthService
from app.services.calendar_sync_service import CalendarSyncService

router = APIRouter()

_auth = CalendarAuthService(
    credentials_file=settings.GOOGLE_CALENDAR_CREDENTIALS_FILE,
    token_file=settings.GOOGLE_CALENDAR_TOKEN_FILE,
    scopes=settings.GOOGLE_CALENDAR_SCOPES,
    redirect_uri=settings.GOOGLE_CALENDAR_REDIRECT_URI,
    state_file=settings.GOOGLE_CALENDAR_OAUTH_STATE_FILE,
)

_sync_service = CalendarSyncService(
    auth_service=_auth,
    sync_state_file=settings.GOOGLE_CALENDAR_SYNC_STATE_FILE,
)


@router.get("/status")
def calendar_status():
    return {
        "authorized": _auth.token_present(),
    }


@router.get("/auth/start")
def calendar_auth_start():
    try:
        url = _auth.get_authorization_url()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"auth_url": url}


@router.get("/auth/callback")
def calendar_auth_callback(code: str, state: str | None = None):
    try:
        _auth.handle_callback(code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "authorized"}


@router.post("/sync")
def calendar_sync(
    user_id: str = Query(default=None),
    time_min: str | None = Query(default=None),
    time_max: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    target_user = user_id or settings.DEFAULT_USER_ID
    try:
        result = _sync_service.sync(db, target_user, time_min=time_min, time_max=time_max)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return result
