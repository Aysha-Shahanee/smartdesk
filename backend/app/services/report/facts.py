"""The report fact base.

Every number in a report originates here, computed before any sentence exists.
The renderer is then a pure function of this object, which is what makes a
report reproducible: regenerating last Tuesday's next month yields byte-identical
output, and a golden-file test can hold that property.

Facts are drawn from the same feature contexts the rule engine uses, so a
figure in the report and the same figure on the Recommendations page come from
one function rather than two implementations that drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.db import RecommendationRecord
from app.services.recommendations.baselines import BaselineSet
from app.services.recommendations.features import build_daily_context
from app.services.recommendations.periods import (
    WEEKDAY_NAMES,
    build_monthly_context,
    build_weekly_context,
)
from app.services.recommendations.types import FeatureContext, Scope

logger = logging.getLogger("smartdesk.report.facts")


@dataclass
class Metric:
    """One headline number, with the comparison that gives it meaning."""

    key: str
    label: str
    value: float
    unit: str
    baseline: float | None = None
    #: Signed difference from the baseline, in the same unit.
    delta: float | None = None
    #: True when moving up is the good direction. Drives colour, not wording.
    higher_is_better: bool = True


@dataclass
class CategorySlice:
    name: str
    minutes: float
    share: float


@dataclass
class HourPoint:
    hour: int
    focus: float
    active_min: float


@dataclass
class DayPoint:
    date: str
    weekday: str
    active_min: float
    deep_min: float
    focus: float


@dataclass
class ReportFacts:
    """Everything a report may say, before anything says it."""

    scope: str
    period_label: str
    period_start: str
    period_end: str
    generated_at: str
    days_of_history: int

    metrics: list[Metric] = field(default_factory=list)
    categories: list[CategorySlice] = field(default_factory=list)
    hours: list[HourPoint] = field(default_factory=list)
    days: list[DayPoint] = field(default_factory=list)

    #: Findings from the rule engine, already ranked, grouped by section.
    findings: dict[str, list[dict]] = field(default_factory=dict)
    #: Hygiene findings, surfaced separately so the caveats are never buried.
    data_notes: list[str] = field(default_factory=list)

    has_activity: bool = True

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)


def _span_label(start: str, end: str) -> str:
    """A date span in prose: "8-14 August 2026", collapsing repeated parts."""
    try:
        first = datetime.fromisoformat(f"{start}T00:00:00")
        last = datetime.fromisoformat(f"{end}T00:00:00")
    except ValueError:
        return f"{start} to {end}"
    if first.year != last.year:
        return f"{first:%-d %B %Y} to {last:%-d %B %Y}".replace("%-d", "")
    if first.month != last.month:
        return f"{first.day} {first:%B} to {last.day} {last:%B} {last.year}"
    return f"{first.day}-{last.day} {last:%B} {last.year}"


def _metric(
    key: str,
    label: str,
    value: float,
    unit: str,
    baseline: float | None = None,
    higher_is_better: bool = True,
) -> Metric:
    return Metric(
        key=key, label=label, value=value, unit=unit, baseline=baseline,
        delta=(value - baseline) if baseline is not None else None,
        higher_is_better=higher_is_better,
    )


def build_report_facts(
    db: Session,
    user_id: str,
    scope: Scope,
    as_of: datetime,
    baselines: BaselineSet,
) -> ReportFacts:
    """Assemble the fact base for one period."""
    if scope is Scope.DAILY:
        return _daily_facts(db, user_id, as_of, baselines)
    if scope is Scope.WEEKLY:
        return _weekly_facts(db, user_id, as_of, baselines)
    return _monthly_facts(db, user_id, as_of, baselines)


def _load_findings(
    db: Session,
    user_id: str,
    scopes: tuple[str, ...],
    local_dates: tuple[str, ...],
) -> tuple[dict[str, list[dict]], list[str]]:
    """Pull already-generated recommendations into the report.

    The report does not re-derive its own observations. Anything worth saying
    has a rule behind it, and reusing those keeps one wording and one
    threshold per claim rather than a second set that slowly disagrees.
    """
    rows = (
        db.query(RecommendationRecord)
        .filter(
            RecommendationRecord.user_id == user_id,
            RecommendationRecord.scope.in_(scopes),
            RecommendationRecord.local_date.in_(local_dates),
            RecommendationRecord.status.in_(("active", "applied")),
        )
        .order_by(RecommendationRecord.score.desc())
        .all()
    )

    grouped: dict[str, list[dict]] = {}
    notes: list[str] = []
    for row in rows:
        # Hygiene rules describe the collection pipeline, not the user. They
        # belong in the caveats footer, not among the findings.
        if row.rule_id.startswith("HY-"):
            notes.append(f"{row.title} — {row.why}")
            continue
        grouped.setdefault(row.section, []).append({
            "rule_id": row.rule_id,
            "severity": row.severity,
            "title": row.title,
            "why": row.why,
            "action": row.action,
            "based_on": row.based_on,
            "score": row.score,
        })
    return grouped, notes


def _days_in_period(ctx: FeatureContext, start: str, end: str) -> list:
    """The period's days, sliced from what the context already reduced.

    The period builders summarise more history than the report shows — four
    weeks behind a weekly context, sixty days behind a monthly one — so the
    reporting window is always a slice of work already done. Calling
    ``summarise_days`` again here re-fetched the same segments and re-derived
    the same blocks, and cost roughly a third of the request. It also left two
    passes over different ranges free to disagree about a figure the report
    prints once.
    """
    return [day for day in ctx.day_summaries if start <= day.date <= end]


def _categories_from(mix: dict[str, float], active_min: float) -> list[CategorySlice]:
    return sorted(
        (
            CategorySlice(
                name=key.replace("_", " "),
                minutes=share * active_min,
                share=share,
            )
            for key, share in mix.items()
        ),
        key=lambda slice_: slice_.minutes,
        reverse=True,
    )


# ---------------------------------------------------------------------- #
# Daily                                                                    #
# ---------------------------------------------------------------------- #

def _daily_facts(
    db: Session, user_id: str, as_of: datetime, baselines: BaselineSet
) -> ReportFacts:
    ctx: FeatureContext = build_daily_context(db, user_id, as_of, baselines)
    date_key = str(ctx.get("local_date", as_of.strftime("%Y-%m-%d")))

    facts = ReportFacts(
        scope="daily",
        period_label=datetime.fromisoformat(f"{date_key}T00:00:00").strftime(
            "%A, %d %B %Y"
        ),
        period_start=date_key,
        period_end=date_key,
        generated_at=as_of.isoformat(),
        days_of_history=ctx.days_of_history,
        has_activity="active_min" in ctx,
    )
    if not facts.has_activity:
        facts.findings, facts.data_notes = _load_findings(
            db, user_id, ("daily",), (date_key,)
        )
        return facts

    facts.metrics = [
        _metric("active", "Active time", ctx.num("active_min"), "min",
                ctx.get("baseline.daily_active_min.p50")),
        _metric("deep", "Deep work", ctx.num("deep_work_min"), "min",
                ctx.get("baseline.deep_work_min.p50")),
        _metric("focus", "Average focus", ctx.num("day_focus"), "score",
                ctx.get("baseline.focus.p50")),
        _metric("distraction", "Distraction share", ctx.num("distraction_share"),
                "share", ctx.get("baseline.distraction_share.p50"),
                higher_is_better=False),
        _metric("fragmentation", "Activities per hour", ctx.num("frag_index"),
                "count", ctx.get("baseline.frag_index.p50"),
                higher_is_better=False),
        _metric("idle", "Idle time", ctx.num("idle_min"), "min", None,
                higher_is_better=False),
    ]

    mix = ctx.get("category_mix") or {}
    facts.categories = _categories_from(mix, ctx.num("active_min"))

    if "best_hour" in ctx:
        facts.hours = [
            HourPoint(
                hour=int(ctx.num("best_hour")),
                focus=ctx.num("best_hour_focus"),
                active_min=0.0,
            ),
            HourPoint(
                hour=int(ctx.num("worst_hour")),
                focus=ctx.num("worst_hour_focus"),
                active_min=0.0,
            ),
        ]

    facts.findings, facts.data_notes = _load_findings(
        db, user_id, ("daily", "live"), (date_key,)
    )
    return facts


# ---------------------------------------------------------------------- #
# Weekly                                                                   #
# ---------------------------------------------------------------------- #

def _weekly_facts(
    db: Session, user_id: str, as_of: datetime, baselines: BaselineSet
) -> ReportFacts:
    ctx = build_weekly_context(db, user_id, as_of, baselines)
    start = str(ctx.get("week_start", ""))
    end = str(ctx.get("week_end", ""))

    facts = ReportFacts(
        scope="weekly",
        period_label=_span_label(start, end),
        period_start=start,
        period_end=end,
        generated_at=as_of.isoformat(),
        days_of_history=ctx.days_of_history,
        has_activity="week_active_min" in ctx,
    )
    if not facts.has_activity:
        return facts

    day_count = max(ctx.num("week_day_count"), 1.0)
    facts.metrics = [
        _metric("active", "Active time", ctx.num("week_active_min"), "min"),
        _metric("deep", "Deep work", ctx.num("week_deep_min"), "min"),
        _metric("active_days", "Active days", ctx.num("week_active_days"), "count"),
        _metric("daily_average", "Daily average",
                ctx.num("week_active_min") / day_count, "min",
                ctx.get("baseline.daily_active_min.p50")),
        _metric("late_nights", "Sessions past midnight",
                ctx.num("late_night_count"), "count", None,
                higher_is_better=False),
    ]

    days = _days_in_period(ctx, start, end)
    facts.days = [
        DayPoint(
            date=d.date,
            weekday=WEEKDAY_NAMES[d.weekday][:3],
            active_min=d.active_min,
            deep_min=d.deep_min,
            focus=d.focus,
        )
        for d in days
    ]
    totals: dict[str, float] = {}
    for day in days:
        for key, minutes in day.category_min.items():
            totals[key] = totals.get(key, 0.0) + minutes
    grand = sum(totals.values())
    if grand:
        facts.categories = _categories_from(
            {k: v / grand for k, v in totals.items()}, grand
        )

    week_dates = tuple(d.date for d in days)
    facts.findings, facts.data_notes = _load_findings(
        db, user_id, ("weekly",), week_dates + (as_of.strftime("%Y-%m-%d"),)
    )
    return facts


# ---------------------------------------------------------------------- #
# Monthly                                                                  #
# ---------------------------------------------------------------------- #

def _monthly_facts(
    db: Session, user_id: str, as_of: datetime, baselines: BaselineSet
) -> ReportFacts:
    ctx = build_monthly_context(db, user_id, as_of, baselines)
    start = str(ctx.get("month_start", ""))
    end = str(ctx.get("month_end", ""))

    facts = ReportFacts(
        scope="monthly",
        period_label=_span_label(start, end),
        period_start=start,
        period_end=end,
        generated_at=as_of.isoformat(),
        days_of_history=ctx.days_of_history,
        has_activity="month_active_min" in ctx,
    )
    if not facts.has_activity:
        return facts

    active_days = max(ctx.num("month_active_days"), 1.0)
    facts.metrics = [
        _metric("active", "Active time", ctx.num("month_active_min"), "min"),
        _metric("deep", "Deep work", ctx.num("month_deep_min"), "min"),
        _metric("active_days", "Active days", ctx.num("month_active_days"), "count"),
        _metric("daily_average", "Daily average",
                ctx.num("month_active_min") / active_days, "min",
                ctx.get("baseline.daily_active_min.p50")),
    ]
    if "mo_deep_now" in ctx:
        facts.metrics.append(
            _metric("deep_median", "Deep work on a typical day",
                    ctx.num("mo_deep_now"), "min", ctx.get("mo_deep_prev"))
        )

    days = _days_in_period(ctx, start, end)
    facts.days = [
        DayPoint(
            date=d.date, weekday=WEEKDAY_NAMES[d.weekday][:3],
            active_min=d.active_min, deep_min=d.deep_min, focus=d.focus,
        )
        for d in days
    ]
    totals: dict[str, float] = {}
    for day in days:
        for key, minutes in day.category_min.items():
            totals[key] = totals.get(key, 0.0) + minutes
    grand = sum(totals.values())
    if grand:
        facts.categories = _categories_from(
            {k: v / grand for k, v in totals.items()}, grand
        )

    facts.findings, facts.data_notes = _load_findings(
        db, user_id, ("monthly",), tuple(d.date for d in days) + (as_of.strftime("%Y-%m-%d"),)
    )
    return facts
