"""Dashboard routes — Phase 9.

All five panels defined in plan.md Part 8 are implemented here.
Each endpoint accepts:
  - ``user_id``  — defaults to "local_user" for single-user desktop mode
  - ``from``     — ISO 8601 datetime (start of query window)
  - ``to``       — ISO 8601 datetime (end of query window)

Additional endpoints:
  - POST /dashboard/corrections — record a user‑provided label correction
  - GET /dashboard/segments/summary — get segment counts and durations by category for a day
"""

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import local_day_start_iso
from app.core.time import local_now_iso
from app.core.time import to_local_iso
from app.models.schemas.dashboard import (
    BrowserDashboardResponse,
    IDEDashboardResponse,
    OSDashboardResponse,
    SessionsDashboardResponse,
    TimelineDashboardResponse,
)
from app.models.db import ActivitySegmentRecord, ActivitySegmentLabelRecord
from app.services.dashboard_service import DashboardService
from app.services.categorizer import categorizer

router = APIRouter()
_service = DashboardService()

# ------------------------------------------------------------------ #
# Default time window helpers                                          #
# ------------------------------------------------------------------ #


def _today_start() -> str:
    return local_day_start_iso()


def _today_end() -> str:
    return local_now_iso()


def _parse_dt(value: str, param_name: str) -> str:
    """Validate and normalise an ISO 8601 datetime string."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return to_local_iso(dt)
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
            "/dashboard/overview",
            "/dashboard/ui",
            "/dashboard/corrections",
            "/dashboard/segments/summary",
            "/dashboard/segments",
        ],
    }


# ------------------------------------------------------------------ #
# Monitoring overview + UI                                             #
# ------------------------------------------------------------------ #


@router.get("/overview")
def get_overview(
    user_id: str = Query(default="local_user"),
    db: Session = Depends(get_db),
):
    """Health-check overview of all four collection layers."""
    return _service.get_overview(db, user_id)


@router.get("/ui", include_in_schema=False)
def dashboard_ui():
    """Small static monitoring dashboard."""
    page = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"
    return FileResponse(page, media_type="text/html")


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
    """OS-level summary: active/idle time, top apps, category breakdown."""
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


# ------------------------------------------------------------------ #
# Corrections                                                          #
# ------------------------------------------------------------------ #


class CorrectionRequest(BaseModel):
    segment_id: str = Field(..., description="UUID of the activity segment")
    correct_label: str = Field(..., description="User‑provided correct label")


@router.post("/corrections", status_code=status.HTTP_201_CREATED)
def record_correction(
    request: CorrectionRequest,
    user_id: str = Query(default="local_user"),
    db: Session = Depends(get_db),
):
    """Store a user‑provided correction for an activity segment."""
    # Validate the segment exists
    segment = db.get(ActivitySegmentRecord, request.segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    # Optional: verify user_id/device_id match? For simplicity we assume the segment belongs to the user.
    # Use the segment's own user_id and device_id for storage consistency.
    # Record the correction via the categorizer service (this will increment the retraining counter)
    try:
        label_id = categorizer.store_user_correction(segment, request.correct_label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record correction: {e}")
    return {"label_id": label_id}


# ------------------------------------------------------------------ #
# Segments Summary (for donut chart)                                   #
# ------------------------------------------------------------------ #


class SummaryResponse(BaseModel):
    date: str
    total_segments: int
    total_duration_sec: int
    count_by_category: Dict[str, int]
    duration_by_category: Dict[str, int]


@router.get("/segments/summary", response_model=SummaryResponse)
def get_segments_summary(
    date: Optional[str] = Query(None, description="YYYY‑MM‑DD, defaults to today"),
    user_id: str = Query(default="local_user"),
    db: Session = Depends(get_db),
):
    """Return aggregation of activity segments for a given day."""
    # Determine the target date in local time
    if date:
        try:
            target_date = datetime.fromisoformat(date).date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        target_date = datetime.now().date()

    target_date_str = target_date.isoformat()  # "YYYY-MM-DD"

    # Use the local_date column which is already stored as YYYY-MM-DD
    from sqlalchemy import func
    q = (
        db.query(
            ActivitySegmentRecord.category,
            func.count(ActivitySegmentRecord.id).label("cnt"),
            func.sum(ActivitySegmentRecord.duration_sec).label("dur"),
        )
        .filter(
            ActivitySegmentRecord.user_id == user_id,
            ActivitySegmentRecord.local_date == target_date_str,
            ActivitySegmentRecord.category.isnot(None),
            # Work time only. Idle segments carry a category too, so without
            # this the breakdown counts time at an unattended machine as work —
            # 47.8 h of the 81.5 h recorded for 2026-07-21..28. This filter was
            # harmless before idle segments existed; every non-gap row was
            # 'active' and gaps had a NULL category.
            ActivitySegmentRecord.state == "active",
        )
        .group_by(ActivitySegmentRecord.category)
    )
    rows = q.all()
    count_by_category = {row.category: row.cnt for row in rows}
    duration_by_category = {row.category: row.dur for row in rows}
    total_segments = sum(count_by_category.values())
    total_duration = sum(duration_by_category.values())
    return SummaryResponse(
        date=target_date_str,
        total_segments=total_segments,
        total_duration_sec=total_duration,
        count_by_category=count_by_category,
        duration_by_category=duration_by_category,
    )


# ------------------------------------------------------------------ #
# Segments List (for correction table)                                 #
# ------------------------------------------------------------------ #


class SegmentItem(BaseModel):
    id: str
    app_name: Optional[str]
    title: Optional[str]
    detail: Optional[str]
    predicted_category: Optional[str]
    predicted_method: Optional[str]
    predicted_confidence: Optional[float]
    correction_label: Optional[str]
    focus_score: Optional[float]
    start_time_utc: Optional[str]
    end_time_utc: Optional[str]
    duration_sec: Optional[int]
    # Source/state provenance. Without these the UI has to guess a segment's
    # origin by substring-matching app_name against a keyword list, which
    # misses renamed binaries and mislabels anything not on the list.
    state: Optional[str]
    primary_source: Optional[str]
    has_ide_session: bool = False
    has_browser_session: bool = False
    has_os_session: bool = False


class SegmentsResponse(BaseModel):
    date: str
    limit: int
    offset: int
    total: int
    segments: List[SegmentItem]


@router.get("/segments", response_model=SegmentsResponse)
def get_segments_list(
    date: Optional[str] = Query(None, description="YYYY‑MM‑DD, defaults to today"),
    user_id: str = Query(default="local_user"),
    limit: int = Query(100, gt=0, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return a list of activity segments for a given day with prediction info and any existing correction."""
    # Determine the target date in local time
    if date:
        try:
            target_date = datetime.fromisoformat(date).date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        target_date = datetime.now().date()

    target_date_str = target_date.isoformat()  # "YYYY-MM-DD"

    # Use the local_date column which is already stored as YYYY-MM-DD
    q = db.query(ActivitySegmentRecord).filter(
        ActivitySegmentRecord.user_id == user_id,
        ActivitySegmentRecord.local_date == target_date_str,
    )
    total = q.count()
    # Fetch rows with pagination
    rows = q.order_by(ActivitySegmentRecord.start_time_utc.desc()).offset(offset).limit(limit).all()

    # Build a set of segment IDs for batch correction lookup
    seg_ids = [seg.id for seg in rows]
    # Batch-fetch the latest correction per segment (avoids N+1 queries)
    corrections: Dict[str, str] = {}
    if seg_ids:
        from sqlalchemy import func as sa_func
        latest_labels = (
            db.query(
                ActivitySegmentLabelRecord.segment_id,
                sa_func.max(ActivitySegmentLabelRecord.created_at).label("latest"),
            )
            .filter(ActivitySegmentLabelRecord.segment_id.in_(seg_ids))
            .group_by(ActivitySegmentLabelRecord.segment_id)
            .subquery()
        )
        label_rows = (
            db.query(ActivitySegmentLabelRecord)
            .join(
                latest_labels,
                (ActivitySegmentLabelRecord.segment_id == latest_labels.c.segment_id)
                & (ActivitySegmentLabelRecord.created_at == latest_labels.c.latest),
            )
            .all()
        )
        corrections = {lr.segment_id: lr.correct_label for lr in label_rows}

    # Use stored category/method/confidence — no ML inference needed per request
    seg_list: List[SegmentItem] = []
    for seg in rows:
        seg_list.append(
            SegmentItem(
                id=seg.id,
                app_name=seg.app_name,
                title=seg.title,
                detail=seg.detail,
                predicted_category=seg.category,
                predicted_method=seg.category_method,
                predicted_confidence=seg.category_confidence,
                correction_label=corrections.get(seg.id),
                focus_score=seg.focus_score,
                start_time_utc=seg.start_time_utc.isoformat() if seg.start_time_utc else None,
                end_time_utc=seg.end_time_utc.isoformat() if seg.end_time_utc else None,
                duration_sec=seg.duration_sec,
                state=seg.state,
                primary_source=seg.primary_source,
                has_ide_session=seg.ide_session_id is not None,
                has_browser_session=seg.browser_session_id is not None,
                has_os_session=seg.os_session_id is not None,
            )
        )
    return SegmentsResponse(
        date=target_date_str,
        limit=limit,
        offset=offset,
        total=total,
        segments=seg_list,
    )