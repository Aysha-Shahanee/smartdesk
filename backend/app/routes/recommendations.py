"""Recommendation endpoints.

``GET /api/v1/recommendations`` generates on read when the stored set for the
requested day is empty or stale. That keeps the page working whether or not the
60-second job has been running, which matters because the app is opened after
the backend has been down as often as during it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.time import local_now
from app.models.db import RecommendationRecord
from app.services.recommendations.engine import engine
from app.services.recommendations.ranker import ranker
from app.services.recommendations.types import Scope, Section

logger = logging.getLogger("smartdesk.routes.recommendations")

router = APIRouter()

FEEDBACK_ACTIONS = ("applied", "dismissed", "snoozed", "shown")


def _serialise(record: RecommendationRecord) -> dict:
    try:
        facts = json.loads(record.facts_json) if record.facts_json else {}
    except (TypeError, ValueError):
        facts = {}
    return {
        "id": record.id,
        "rule_id": record.rule_id,
        "scope": record.scope,
        "section": record.section,
        "severity": record.severity,
        "title": record.title,
        "why": record.why,
        "action": record.action,
        "action_label": record.action_label,
        "based_on": record.based_on,
        "score": record.score,
        "status": record.status,
        "generated_at": record.generated_at,
        "facts": facts,
    }


@router.get("/recommendations")
def get_recommendations(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    date: str | None = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    refresh: bool = Query(default=False, description="Force a regeneration pass"),
    db: Session = Depends(get_db),
) -> dict:
    """Recommendations for a day, grouped into the page's four sections."""
    if date:
        try:
            as_of = datetime.fromisoformat(f"{date}T00:00:00")
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
        # For a past day, evaluate the live family as it stood at the end of
        # that day rather than at midnight, where nothing has happened yet.
        today = local_now()
        as_of = today if as_of.date() == today.date() else as_of.replace(hour=23, minute=59)
    else:
        as_of = local_now()

    local_date = as_of.strftime("%Y-%m-%d")

    # Daily rules describe a *completed* day. Running them against a day still
    # in progress compares a partial total against a full-day baseline, so
    # every "below your usual" rule fires at breakfast and none of them mean
    # anything. On today, they run against yesterday; the live family covers
    # what is happening now.
    daily_as_of = as_of if as_of.date() < local_now().date() else as_of - timedelta(days=1)
    daily_date = daily_as_of.strftime("%Y-%m-%d")

    existing = engine.active_for(db, user_id, local_date)
    if daily_date != local_date:
        existing += engine.active_for(db, user_id, daily_date)

    if refresh or not existing:
        try:
            engine.generate(db, user_id, daily_as_of, scopes=(Scope.DAILY,))
            engine.generate(db, user_id, as_of, scopes=(Scope.LIVE,))
        except Exception:
            # A generation failure must not blank the page; whatever was
            # already stored is still valid and still worth showing.
            logger.exception("Recommendation generation failed for %s", local_date)
        existing = engine.active_for(db, user_id, local_date)
        if daily_date != local_date:
            existing += engine.active_for(db, user_id, daily_date)

    existing.sort(key=lambda r: r.score, reverse=True)

    grouped: dict[str, list[dict]] = {section.value: [] for section in Section}
    for record in existing:
        grouped.setdefault(record.section, []).append(_serialise(record))

    return {
        "date": local_date,
        "daily_date": daily_date,
        "generated_at": as_of.isoformat(),
        "total": len(existing),
        "sections": grouped,
    }


@router.post("/recommendations/{recommendation_id}/feedback", status_code=status.HTTP_200_OK)
def post_feedback(
    recommendation_id: str,
    action: str = Body(embed=True),
    db: Session = Depends(get_db),
) -> dict:
    """Record Applied / Not relevant / Snoozed. This is the ranker's training set."""
    if action not in FEEDBACK_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of {FEEDBACK_ACTIONS}",
        )
    record = engine.record_feedback(db, recommendation_id, action)
    if record is None:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return {"id": record.id, "status": record.status}


@router.get("/recommendations/debug/context")
def debug_context(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    scope: str = Query(default="live"),
    db: Session = Depends(get_db),
) -> dict:
    """Feature snapshot plus per-rule gate status — the "why did nothing fire?" view."""
    try:
        parsed = Scope(scope)
    except ValueError:
        raise HTTPException(status_code=422, detail="scope must be live or daily")
    return engine.describe_context(db, user_id, scope=parsed)


@router.get("/recommendations/ranker/status")
def ranker_status() -> dict:
    """Whether the learned ranker is influencing the ordering yet."""
    return ranker.status()


@router.post("/recommendations/ranker/train")
def train_ranker(db: Session = Depends(get_db)) -> dict:
    """Fit the ranker on recorded feedback.

    Returns ``{"trained": false, "reason": ...}`` rather than raising when
    there is not enough feedback — that is the normal state for a long while,
    not an error.
    """
    return ranker.train(db)
