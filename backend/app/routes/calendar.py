"""Calendar routes — Google Calendar connect, sync, and queries."""

import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.calendar_service import CalendarNotConfiguredError
from app.services.calendar_service import CalendarNotConnectedError
from app.services.calendar_service import CalendarService

router = APIRouter()
logger = logging.getLogger("smartdesk.calendar_routes")
_service = CalendarService()

_CALLBACK_OK_HTML = """
<html><body style="font-family:sans-serif;text-align:center;padding-top:80px">
<h2>&#9989; Google Calendar connected</h2>
<p>First sync is running. You can close this tab and go back to the dashboard.</p>
</body></html>
"""


@router.get("/status")
def calendar_status(
    user_id: str = Query(default=None),
    db: Session = Depends(get_db),
):
    return _service.status(user_id or settings.DEFAULT_USER_ID, db)


@router.get("/connect")
def calendar_connect(user_id: str = Query(default=None)):
    """One-click connect: redirects the browser to Google's consent screen."""
    try:
        auth_url = _service.build_auth_url(user_id or settings.DEFAULT_USER_ID)
    except CalendarNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(auth_url)


@router.get("/oauth/callback")
def calendar_oauth_callback(
    state: str,
    code: str = Query(default=None),
    error: str = Query(default=None),
    db: Session = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    try:
        user_id = _service.handle_oauth_callback(state, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("OAuth token exchange failed.")
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;"
            "padding-top:80px'><h2>&#10060; Calendar connection failed</h2>"
            f"<p>{type(exc).__name__}: {exc}</p>"
            "<p>Close this tab and try Connect again from the dashboard.</p>"
            "</body></html>",
            status_code=500,
        )

    # Run the first sync right away so the dashboard shows data immediately.
    try:
        _service.sync(user_id, db)
    except Exception:
        logger.exception("Initial calendar sync failed (token saved; retry via Sync).")

    return HTMLResponse(_CALLBACK_OK_HTML)


@router.post("/sync")
def calendar_sync(
    user_id: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Manual sync — used by the dashboard Sync button."""
    try:
        return _service.sync(user_id or settings.DEFAULT_USER_ID, db)
    except CalendarNotConnectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CalendarNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/disconnect")
def calendar_disconnect(user_id: str = Query(default=None)):
    _service.disconnect(user_id or settings.DEFAULT_USER_ID)
    return {"status": "disconnected"}


@router.get("/events")
def calendar_events(
    user_id: str = Query(default=None),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Events ordered by start time (Asia/Colombo)."""
    rows = _service.list_events(user_id or settings.DEFAULT_USER_ID, db, from_, to)
    return {
        "events": [
            {
                "event_id": r.event_id,
                "title": r.title,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "is_all_day": bool(r.is_all_day),
                "duration_sec": r.duration_sec,
                "status": r.status,
                "location": r.location,
                "organizer_email": r.organizer_email,
                "attendees_count": r.attendees_count,
                "is_recurring": bool(r.is_recurring),
                "html_link": r.html_link,
                "last_synced_at": r.last_synced_at,
            }
            for r in rows
        ],
        "count": len(rows),
    }
