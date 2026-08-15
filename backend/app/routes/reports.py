"""Report endpoints.

Reports are generated on read rather than stored. The renderer is deterministic
given the fact base, so a cache would only ever hold what regeneration produces
anyway — and a stored report would silently go stale as segments are
recategorised beneath it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.time import local_now
from app.services.recommendations.engine import engine
from app.services.recommendations.types import Scope
from app.services.report import (
    build_report_facts,
    build_sections,
    render_html,
    render_markdown,
)

logger = logging.getLogger("smartdesk.routes.reports")

router = APIRouter()

SCOPES = {"daily": Scope.DAILY, "weekly": Scope.WEEKLY, "monthly": Scope.MONTHLY}


def _resolve(scope: str, date: str | None) -> tuple[Scope, datetime]:
    if scope not in SCOPES:
        raise HTTPException(
            status_code=422, detail="scope must be daily, weekly or monthly"
        )
    if date:
        try:
            as_of = datetime.fromisoformat(f"{date}T00:00:00")
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    else:
        as_of = local_now().replace(tzinfo=None)

    parsed = SCOPES[scope]
    # A daily report describes a completed day. Asked for today, it reports
    # yesterday rather than a partial day measured against full-day baselines.
    if parsed is Scope.DAILY and as_of.date() >= local_now().date():
        as_of -= timedelta(days=1)
    return parsed, as_of


def _build(db: Session, user_id: str, parsed: Scope, as_of: datetime):
    baselines = engine.baselines(db, user_id, as_of)
    # Make sure the findings the report quotes actually exist. Generation is
    # deduped and cooled down, so calling it here is cheap and idempotent.
    try:
        engine.generate(db, user_id, as_of, scopes=(parsed,))
    except Exception:
        logger.exception("Could not refresh findings for the %s report", parsed.value)
    facts = build_report_facts(db, user_id, parsed, as_of, baselines)
    return facts, build_sections(facts)


@router.get("/reports/{scope}")
def get_report(
    scope: str,
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Structured report: facts plus rendered sections."""
    parsed, as_of = _resolve(scope, date)
    facts, sections = _build(db, user_id, parsed, as_of)
    return {
        "scope": facts.scope,
        "period_label": facts.period_label,
        "period_start": facts.period_start,
        "period_end": facts.period_end,
        "generated_at": facts.generated_at,
        "days_of_history": facts.days_of_history,
        "has_activity": facts.has_activity,
        "metrics": [asdict(m) for m in facts.metrics],
        "categories": [asdict(c) for c in facts.categories],
        "days": [asdict(d) for d in facts.days],
        "sections": [asdict(s) for s in sections],
    }


@router.get("/reports/{scope}/markdown", response_class=PlainTextResponse)
def get_report_markdown(
    scope: str,
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> str:
    """The canonical export form."""
    parsed, as_of = _resolve(scope, date)
    facts, sections = _build(db, user_id, parsed, as_of)
    return render_markdown(facts, sections)


@router.get("/reports/{scope}/html", response_class=HTMLResponse)
def get_report_html(
    scope: str,
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> str:
    """A self-contained printable page. The Electron shell turns this into PDF."""
    parsed, as_of = _resolve(scope, date)
    facts, sections = _build(db, user_id, parsed, as_of)
    return render_html(facts, sections)
