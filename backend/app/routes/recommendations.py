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
from app.repositories.preference_repository import PreferenceRepository
from app.services.recommendations.engine import engine
from app.services.recommendations.redaction import backfill_stored_cards
from app.services.recommendations.evaluation import evaluate
from app.services.recommendations.simulation import (
    run_suite,
    run_sweeps,
    summarise,
)
from app.services.recommendations.registry import BY_ID
from app.services.recommendations.ranker import ranker
from app.services.recommendations.telemetry import rule_health
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
            # The weekly and monthly families are generated here too, not only
            # by the report route. Their hygiene rules are the ones that say a
            # period recorded nothing at all, and routing that answer solely
            # through the reports page meant the panel stayed blank on exactly
            # the weeks it most needed to explain itself. Generation is deduped
            # and cooled down, so on a normal day this writes nothing.
            engine.generate(db, user_id, as_of, scopes=(Scope.WEEKLY, Scope.MONTHLY))
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


@router.get("/recommendations/rules/health")
def rules_health(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    since: str | None = Query(
        default=None, description="YYYY-MM-DD floor on local_date"
    ),
    verdict: str | None = Query(
        default=None,
        description="Filter to one verdict: below, typical, unproven, above, silent",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Per-rule fire rate, acceptance, PPV and time-to-action.

    The catalogue review view. Rules are ordered worst-first and each is judged
    against this user's own acceptance rate rather than a fixed bar, so the
    ``below`` verdict means "significantly worse than your other rules", not
    "under some number we picked".

    Read-only: nothing here demotes anything. Deciding to cut a rule on this
    evidence is a separate, deliberate act.
    """
    report = rule_health(db, user_id=user_id, since=since)
    payload = report.as_dict()
    if verdict:
        payload["rules"] = [r for r in payload["rules"] if r["verdict"] == verdict]
    return payload


@router.post("/recommendations/rules/{rule_id}/mute")
def set_rule_muted(
    rule_id: str,
    muted: bool = Body(embed=True, default=True),
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Switch a rule off, or back on.

    Scrutability, in the sense Tintarev & Masthoff (2012) use: a system that
    explains itself should also let the user correct it. The engine already
    shows which rule produced a card and what evidence sat behind it; without
    a way to act on that, the explanation is something to read rather than
    something to use.

    Muting takes effect at generation, so a muted rule stops producing cards
    rather than having its cards filtered out downstream. Cards it produced
    before are left exactly as they were — they are history, and the feedback
    on them is the evidence that justified muting in the first place.
    """
    if rule_id not in BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown rule {rule_id}")
    PreferenceRepository(db).set_rule_muted(user_id, rule_id, muted)
    logger.info("Rule %s %s for %s", rule_id, "muted" if muted else "unmuted", user_id)
    return {"rule_id": rule_id, "muted": muted}


@router.get("/recommendations/rules/muted")
def list_muted_rules(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Which rules this user has switched off."""
    muted = sorted(PreferenceRepository(db).muted_rules(user_id))
    return {"muted": muted, "count": len(muted)}


@router.get("/recommendations/evaluation")
def get_evaluation(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    k: int = Query(default=3, ge=1, le=13),
    since: str | None = Query(default=None, description="YYYY-MM-DD floor"),
    db: Session = Depends(get_db),
) -> dict:
    """Offline evaluation of the surfacing policy against its own ablations.

    Answers the two questions a reader asks first — does the ordering beat a
    shuffle, and does the learned ranker improve on the rules alone — using
    the feedback already recorded, on a temporal split. Also reports whether
    an off-policy estimate is identified at all, which until exploration is
    switched on it is not.
    """
    return evaluate(db, user_id=user_id, k=k, since=since).as_dict()


@router.get("/recommendations/simulation")
def get_simulation(seed: int = Query(default=0, description="0 uses the fixed seed")) -> dict:
    """Rule accuracy against synthetic days with planted conditions.

    The only measurement here that is precision and recall in the ordinary
    sense: the condition each rule claims to detect is put into the features
    on purpose, or deliberately withheld, so the right answer is known before
    the rule runs. Feedback cannot do this — a user dismissing a true finding
    says nothing about whether it was true.

    ``sensitivity`` walks the planted deviation up from zero and reports where
    each rule starts firing, which is the evidence for its threshold rather
    than an assertion about it.
    """
    from app.services.recommendations.simulation import DEFAULT_SEED

    chosen = seed or DEFAULT_SEED
    results = run_suite(seed=chosen)
    payload = summarise(results)
    payload["seed"] = chosen
    payload["sensitivity"] = {
        rule_id: {str(step): rate for step, rate in curve.items()}
        for rule_id, curve in run_sweeps(seed=chosen).items()
    }
    return payload


@router.post("/recommendations/rules/{rule_id}/shadow")
def set_rule_shadow(
    rule_id: str,
    shadow: bool = Body(embed=True, default=True),
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Run a rule silently: evaluated on real data, never shown.

    The dark-launch pattern (Zinkevich 2017, rule #5). A new rule currently has
    no trial period — its first contact with live features is also the user's
    first contact with it, so a rule that fires forty times a day is discovered
    by the person it was supposed to help. In shadow mode it is evaluated and
    rendered, its output recorded, and none of it surfaced.
    """
    if rule_id not in BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown rule {rule_id}")
    PreferenceRepository(db).set_rule_shadowed(user_id, rule_id, shadow)
    logger.info(
        "Rule %s shadow mode %s for %s",
        rule_id, "on" if shadow else "off", user_id,
    )
    return {"rule_id": rule_id, "shadow": shadow}


@router.get("/recommendations/rules/shadow")
def shadow_report(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """What the rules under trial would have shown.

    The review step shadow mode exists for: the fire rate of each rule under
    trial, and a sample of the copy it produced, so both can be judged before
    anything is promoted. Compare the fire rate against
    ``/rules/health`` for rules already live — a trial rule firing several times
    a day against an established rule's once a week is the signal to look for.
    """
    shadowed = sorted(PreferenceRepository(db).shadowed_rules(user_id))
    rows = (
        db.query(RecommendationRecord)
        .filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.shadow.is_(True),
        )
        .order_by(RecommendationRecord.generated_at.desc())
        .limit(limit)
        .all()
    )
    per_rule: dict[str, dict] = {}
    for row in rows:
        entry = per_rule.setdefault(
            row.rule_id, {"rule_id": row.rule_id, "fired": 0, "days": set(),
                          "samples": []}
        )
        entry["fired"] += 1
        entry["days"].add(row.local_date)
        if len(entry["samples"]) < 3:
            entry["samples"].append({
                "local_date": row.local_date,
                "title": row.title,
                "why": row.why,
                "action": row.action,
                "based_on": row.based_on,
                "score": row.score,
            })
    summary = []
    for entry in per_rule.values():
        days = len(entry.pop("days"))
        entry["days_seen"] = days
        entry["fires_per_day"] = round(entry["fired"] / days, 2) if days else 0.0
        summary.append(entry)
    summary.sort(key=lambda e: -e["fires_per_day"])
    return {
        "shadowed_rules": shadowed,
        "recorded": len(rows),
        "rules": summary,
    }


@router.get("/recommendations/preferences")
def get_recommendation_preferences(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """The scrutability controls, and their current settings."""
    prefs = PreferenceRepository(db)
    return {
        "baseline_epoch": prefs.baseline_epoch(user_id),
        "sensitivity": prefs.sensitivity(user_id),
        "muted": sorted(prefs.muted_rules(user_id)),
        "shadowed": sorted(prefs.shadowed_rules(user_id)),
    }


@router.post("/recommendations/preferences/baseline-epoch")
def set_baseline_epoch(
    date: str | None = Body(embed=True, default=None),
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """Ignore recorded activity before ``date`` when computing baselines.

    For "my job changed, stop comparing me to who I was". Thirty days of
    history from before a change is not neutral — it is actively misleading,
    and every comparative rule keeps measuring against a person who no longer
    exists.

    Nothing is deleted. The activity stays recorded and still appears in the
    timeline; only the baseline window moves. Passing ``null`` clears the epoch
    and restores every comparison, which a deletion could never do.
    """
    if date:
        try:
            datetime.fromisoformat(f"{date}T00:00:00")
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    stored = PreferenceRepository(db).set_baseline_epoch(user_id, date)
    engine.invalidate_baselines(user_id)
    return {"baseline_epoch": stored}


@router.post("/recommendations/preferences/sensitivity")
def set_sensitivity(
    value: float = Body(embed=True),
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    db: Session = Depends(get_db),
) -> dict:
    """How far from usual a day must be before the engine mentions it.

    A multiplier on the deviation bar the comparative rules share. 1.0 is the
    shipped behaviour; lower speaks up sooner, higher waits for something more
    unusual. Clamped to a range where the panel stays useful at both ends.
    """
    return {"sensitivity": PreferenceRepository(db).set_sensitivity(user_id, value)}


@router.post("/recommendations/maintenance/redact-stored")
def redact_stored_cards(
    user_id: str = Query(default=settings.DEFAULT_USER_ID),
    all_users: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    """Scrub window titles out of cards stored before redaction existed.

    New cards are redacted as their features are built. Older rows were written
    before that and still hold whatever the browser or editor put in a title
    bar — which is exactly the content a report export would carry to whoever
    it is sent to.

    Patches the stored sentence rather than re-rendering it, so a card still
    says what it said at the time apart from the redacted substring. Safe to
    run more than once.
    """
    return backfill_stored_cards(db, user_id=None if all_users else user_id)
