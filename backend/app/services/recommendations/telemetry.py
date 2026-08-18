"""Per-rule health telemetry.

The engine can tell you what fired. It could not, until this module, tell you
whether any of it was worth firing. With 74 rules competing for one panel that
is the difference between a catalogue and a portfolio: without per-rule
outcomes, a rule that has been dismissed on sight for three months is
indistinguishable from one the user acts on every time, and both keep their
place in the ranking forever.

The framing is borrowed from clinical decision support, where this exact
problem has a name and a literature. Override rates there run 46.2%-96.2%
across studies (Poly et al. 2020), and the finding that matters here is that
appropriateness varies enormously *by alert type* — so a global dismissal rate
says nothing, and only per-rule rates identify which alerts to cut. Ancker et
al. (2017) locate the mechanism in work complexity and repetition rather than
desensitisation, which is the evidence behind the cooldowns and per-section
caps the engine already has.

Two decisions here are load-bearing.

**The denominator is the card, not the impression.** ``shown`` events look like
the natural denominator and are not: they are emitted only by the desktop
notification path, so a rule that surfaces on the panel and never notifies
would report zero impressions and an undefined rate. Every row in
``recommendations`` is a card that was put in front of the user, which is the
one denominator that exists for all rules equally.

**The comparison is the user's own average, not a fixed bar.** Judging rules
against a constant ("demote below 30% acceptance") imports a number from
nowhere and, given the override rates above, would condemn most of the
catalogue on its first bad week. Each rule is instead compared against *this
user's* acceptance across all rules, which is the same personal-baseline
discipline the rest of the engine uses, and the comparison is made on a Wilson
interval so a rule with three dismissals is reported as unproven rather than
convicted.

Read-only. Nothing here changes what the user sees; it produces the evidence a
decision to demote a rule would rest on.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.preference_repository import PreferenceRepository
from app.services.recommendations.baselines import percentile
from app.services.recommendations.registry import BY_ID

logger = logging.getLogger("smartdesk.recommendations.telemetry")

#: Judged cards (applied + dismissed) a rule needs before its acceptance rate
#: is treated as a measurement rather than an anecdote. Matches the sample
#: floor the baselines use, for the same reason: below it, one press moves the
#: rate further than any real effect would.
MIN_JUDGED = 8

#: 95% two-sided normal quantile, for the Wilson interval below.
Z = 1.959964

#: Reading order for the verdicts — worst-behaved first, because this list is
#: read to decide what to cut.
VERDICT_ORDER = {"below": 0, "typical": 1, "unproven": 2, "above": 3, "silent": 4}


def wilson_interval(successes: int, trials: int, z: float = Z) -> tuple[float, float]:
    """Confidence interval for a proportion, usable at n=3.

    The textbook normal approximation ``p ± z·sqrt(p(1-p)/n)`` is exactly wrong
    at the scale that matters here: at 0 applied out of 4 it returns [0, 0],
    announcing certainty that a rule is worthless on the strength of four
    presses. The Wilson interval keeps its shape at small n and at proportions
    pinned to 0 or 1, which is the entire population of a fresh rule.

    Returns ``(low, high)``. No trials yields ``(0.0, 1.0)`` — the honest
    interval for a question with no data behind it.
    """
    if trials <= 0:
        return 0.0, 1.0
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    margin = (
        z / denom * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


@dataclass
class RuleHealth:
    """One rule's record, and the verdict that follows from it."""

    rule_id: str
    #: Registry metadata, or None for a rule id present in the data but no
    #: longer in the catalogue — a renamed or deleted rule still has history.
    scope: str | None = None
    section: str | None = None
    severity: str | None = None
    known: bool = True

    fired: int = 0
    applied: int = 0
    dismissed: int = 0
    snoozed: int = 0
    expired: int = 0
    still_active: int = 0

    #: Cards the user actually ruled on. The denominator for acceptance.
    judged: int = 0
    #: applied / judged — of the cards you decided about, how many landed.
    acceptance: float | None = None
    acceptance_low: float | None = None
    acceptance_high: float | None = None
    #: applied / fired — of everything this rule put in front of you, how much
    #: was useful. The alert-fatigue literature's positive predictive value.
    ppv: float | None = None
    #: judged / fired — how often the card was engaged with at all. High
    #: acceptance with a low response rate is a rule mostly being scrolled past.
    response_rate: float | None = None

    median_seconds_to_apply: float | None = None
    median_seconds_to_dismiss: float | None = None

    first_fired: str | None = None
    last_fired: str | None = None

    #: One of "silent", "unproven", "below", "typical", "above" — see
    #: :func:`_verdict`.
    verdict: str = "silent"

    #: Whether the user has switched this rule off.
    #:
    #: Reported alongside the counts rather than instead of them: the history
    #: a rule accumulated before it was muted is exactly what justifies the
    #: decision, and hiding it would make the choice unreviewable.
    muted: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleHealthReport:
    """Every rule's health, plus the baseline they were judged against."""

    user_id: str
    since: str | None
    #: Acceptance across all rules — the bar each rule is measured against.
    overall_acceptance: float | None = None
    overall_judged: int = 0
    overall_fired: int = 0
    muted_count: int = 0
    rules: list[RuleHealth] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "since": self.since,
            "overall_acceptance": self.overall_acceptance,
            "overall_judged": self.overall_judged,
            "overall_fired": self.overall_fired,
            "muted_count": self.muted_count,
            "rules": [r.as_dict() for r in self.rules],
        }

    def demotion_candidates(self) -> list[RuleHealth]:
        """Rules whose acceptance sits significantly below the user's average.

        "Significantly" meaning the whole interval sits below the bar, not
        merely the point estimate — the difference between a rule that is doing
        badly and a rule that has had a bad week.
        """
        return [r for r in self.rules if r.verdict == "below"]


def _verdict(health: RuleHealth, overall: float | None) -> str:
    """Where this rule sits against the user's own acceptance rate.

    - ``silent``   — never fired in the window. Says nothing about quality: a
                     hygiene rule that never fires is a rule doing its job.
    - ``unproven`` — fired, but too few judged cards to rate. The default, and
                     for most rules the permanent state at this data scale.
    - ``below``    — the whole interval sits under the user's average. This is
                     the demotion candidate.
    - ``above``    — the whole interval sits over it. Worth surfacing sooner.
    - ``typical``  — the interval straddles the average, which at these sample
                     sizes is the overwhelmingly common answer and means "no
                     evidence of a difference", not "average".
    """
    if health.fired == 0:
        return "silent"
    if health.judged < MIN_JUDGED or overall is None:
        return "unproven"
    if health.acceptance_high is not None and health.acceptance_high < overall:
        return "below"
    if health.acceptance_low is not None and health.acceptance_low > overall:
        return "above"
    return "typical"


def rule_health(
    db: Session,
    user_id: str,
    since: str | None = None,
) -> RuleHealthReport:
    """Aggregate every rule's outcomes.

    ``since`` is an inclusive ``YYYY-MM-DD`` floor on ``local_date``. Left off,
    the whole history is used — the right default for a catalogue this size,
    where most rules have single-digit totals over months.
    """
    # ``shadow IS NOT 1`` throughout: a card nobody saw has no acceptance rate,
    # and counting one would dilute every figure below with rows that never had
    # the chance to be applied.
    where = "WHERE user_id = :user_id AND (shadow IS NULL OR shadow != 1)"
    params: dict = {"user_id": user_id}
    if since:
        where += " AND local_date >= :since"
        params["since"] = since

    # Terminal status off the card itself rather than a count of events. A card
    # can carry several events — the engine logs a repeat dismissal on purpose
    # — so counting events would weight the loudest interactions highest, which
    # is the opposite of what a per-card rate means.
    rows = db.execute(text(f"""
        SELECT rule_id,
               COUNT(*)                                  AS fired,
               SUM(CASE WHEN status = 'applied'   THEN 1 ELSE 0 END) AS applied,
               SUM(CASE WHEN status = 'dismissed' THEN 1 ELSE 0 END) AS dismissed,
               SUM(CASE WHEN status = 'snoozed'   THEN 1 ELSE 0 END) AS snoozed,
               SUM(CASE WHEN status = 'expired'   THEN 1 ELSE 0 END) AS expired,
               SUM(CASE WHEN status = 'active'    THEN 1 ELSE 0 END) AS still_active,
               MIN(local_date)                           AS first_fired,
               MAX(local_date)                           AS last_fired
        FROM recommendations
        {where}
        GROUP BY rule_id
    """), params).mappings().all()

    # Time-to-action lives on the events, the only place latency is recorded.
    # Pulled per rule and reduced in Python rather than SQL because SQLite has
    # no median and these row counts are trivial.
    lat_where = (
        "WHERE e.user_id = :user_id AND e.seconds_to_action IS NOT NULL"
        " AND (r.shadow IS NULL OR r.shadow != 1)"
    )
    if since:
        lat_where += " AND r.local_date >= :since"
    latency_rows = db.execute(text(f"""
        SELECT e.rule_id, e.action, e.seconds_to_action
        FROM recommendation_events e
        JOIN recommendations r ON r.id = e.recommendation_id
        {lat_where}
    """), params).mappings().all()

    latencies: dict[tuple[str, str], list[float]] = {}
    for row in latency_rows:
        key = (str(row["rule_id"]), str(row["action"]))
        latencies.setdefault(key, []).append(float(row["seconds_to_action"]))

    by_rule: dict[str, RuleHealth] = {}
    total_applied = total_judged = total_fired = 0

    for row in rows:
        rule_id = str(row["rule_id"])
        applied = int(row["applied"] or 0)
        dismissed = int(row["dismissed"] or 0)
        fired = int(row["fired"] or 0)
        judged = applied + dismissed

        health = RuleHealth(
            rule_id=rule_id,
            fired=fired,
            applied=applied,
            dismissed=dismissed,
            snoozed=int(row["snoozed"] or 0),
            expired=int(row["expired"] or 0),
            still_active=int(row["still_active"] or 0),
            judged=judged,
            first_fired=row["first_fired"],
            last_fired=row["last_fired"],
        )
        if judged:
            health.acceptance = applied / judged
            low, high = wilson_interval(applied, judged)
            health.acceptance_low, health.acceptance_high = low, high
        if fired:
            health.ppv = applied / fired
            health.response_rate = judged / fired

        applied_lat = latencies.get((rule_id, "applied"))
        dismiss_lat = latencies.get((rule_id, "dismissed"))
        if applied_lat:
            health.median_seconds_to_apply = percentile(applied_lat, 0.50)
        if dismiss_lat:
            health.median_seconds_to_dismiss = percentile(dismiss_lat, 0.50)

        by_rule[rule_id] = health
        total_applied += applied
        total_judged += judged
        total_fired += fired

    # Rules that never fired belong in the picture too: a rule that has produced
    # nothing in ninety days is either perfectly calibrated or dead, and the
    # catalogue cannot be reviewed without seeing which ones they are.
    for rule_id in BY_ID:
        by_rule.setdefault(rule_id, RuleHealth(rule_id=rule_id))

    overall = (total_applied / total_judged) if total_judged else None
    muted = PreferenceRepository(db).muted_rules(user_id)

    for rule_id, health in by_rule.items():
        health.muted = rule_id in muted
        spec = BY_ID.get(rule_id)
        if spec is not None:
            health.scope = spec.scope.value
            health.section = spec.section.value
            health.severity = spec.severity.value
        else:
            health.known = False
        health.verdict = _verdict(health, overall)

    ordered = sorted(
        by_rule.values(),
        key=lambda h: (
            VERDICT_ORDER[h.verdict],
            h.acceptance if h.acceptance is not None else 1.0,
            -h.fired,
            h.rule_id,
        ),
    )

    return RuleHealthReport(
        user_id=user_id,
        since=since,
        muted_count=sum(1 for h in by_rule.values() if h.muted),
        overall_acceptance=overall,
        overall_judged=total_judged,
        overall_fired=total_fired,
        rules=ordered,
    )
