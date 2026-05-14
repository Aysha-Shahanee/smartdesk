"""Dashboard routes — Phase 9.

All five panels defined in plan.md Part 8 are implemented here.
Each endpoint accepts:
  - ``user_id``  — defaults to "local_user" for single-user desktop mode
  - ``from``     — ISO 8601 datetime (start of query window)
  - ``to``       — ISO 8601 datetime (end of query window)
"""

from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.schemas.dashboard import (
    BrowserDashboardResponse,
    IDEDashboardResponse,
    OSDashboardResponse,
    SessionsDashboardResponse,
    TimelineDashboardResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter()
_service = DashboardService()

# ------------------------------------------------------------------ #
# Default time window helpers                                          #
# ------------------------------------------------------------------ #

def _today_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _today_end() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str, param_name: str) -> str:
    """Validate and normalise an ISO 8601 datetime string."""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid datetime for '{param_name}': {value}. Use ISO 8601.",
        ) from exc


# ------------------------------------------------------------------ #
# Status                                                               #
# ------------------------------------------------------------------ #

@router.get("/status")
def dashboard_status():
    return {
        "status": "ready",
        "phase": "dashboard_api",
        "endpoints": [
            "/dashboard/os",
            "/dashboard/ide",
            "/dashboard/browser",
            "/dashboard/timeline",
            "/dashboard/sessions",
        ],
    }


# ------------------------------------------------------------------ #
# OS panel                                                             #
# ------------------------------------------------------------------ #

@router.get("/os", response_model=OSDashboardResponse)
def get_os_dashboard(
    user_id: str = Query(default="local_user"),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """OS-level summary: active/idle/locked time, top apps, category breakdown."""
    from_iso = _parse_dt(from_, "from") if from_ else _today_start()
    to_iso = _parse_dt(to, "to") if to else _today_end()
    return _service.get_os_summary(db, user_id, from_iso, to_iso)


# ------------------------------------------------------------------ #
# IDE panel                                                            #
# ------------------------------------------------------------------ #

@router.get("/ide", response_model=IDEDashboardResponse)
def get_ide_dashboard(
    user_id: str = Query(default="local_user"),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """IDE summary: coding time, edits, saves, lines, top languages & projects."""
    from_iso = _parse_dt(from_, "from") if from_ else _today_start()
    to_iso = _parse_dt(to, "to") if to else _today_end()
    return _service.get_ide_summary(db, user_id, from_iso, to_iso)


# ------------------------------------------------------------------ #
# Browser panel                                                        #
# ------------------------------------------------------------------ #

@router.get("/browser", response_model=BrowserDashboardResponse)
def get_browser_dashboard(
    user_id: str = Query(default="local_user"),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Browser summary: active time, productive/distracted/neutral, top domains."""
    from_iso = _parse_dt(from_, "from") if from_ else _today_start()
    to_iso = _parse_dt(to, "to") if to else _today_end()
    return _service.get_browser_summary(db, user_id, from_iso, to_iso)


# ------------------------------------------------------------------ #
# Timeline panel                                                       #
# ------------------------------------------------------------------ #

@router.get("/timeline", response_model=TimelineDashboardResponse)
def get_timeline_dashboard(
    user_id: str = Query(default="local_user"),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Timeline: list of work periods with source flags and durations."""
    from_iso = _parse_dt(from_, "from") if from_ else _today_start()
    to_iso = _parse_dt(to, "to") if to else _today_end()
    return _service.get_timeline(db, user_id, from_iso, to_iso)


# ------------------------------------------------------------------ #
# Raw sessions                                                         #
# ------------------------------------------------------------------ #

@router.get("/sessions", response_model=SessionsDashboardResponse)
def get_sessions_dashboard(
    user_id: str = Query(default="local_user"),
    from_: str = Query(default=None, alias="from"),
    to: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """Flat chronological list of all sessions across OS, IDE, and browser."""
    from_iso = _parse_dt(from_, "from") if from_ else _today_start()
    to_iso = _parse_dt(to, "to") if to else _today_end()
    return _service.get_sessions(db, user_id, from_iso, to_iso)
