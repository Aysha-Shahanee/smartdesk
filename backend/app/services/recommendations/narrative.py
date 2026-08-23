"""Deterministic template rendering.

No language model. A rule's copy is a ``str.format`` template and the facts it
emitted are the only substitution source, so a sentence cannot contain a number
the predicate did not compute. That constraint is the whole reason the output
is trustworthy, and it is also what makes reports reproducible: the same fact
base renders byte-identical prose every time.

Variant selection is by magnitude and by a hash of the day, so consecutive days
do not repeat a phrasing while the same day always renders identically.
"""

from __future__ import annotations

import logging

from app.services.recommendations.types import Evidence, Finding, RuleSpec

logger = logging.getLogger("smartdesk.recommendations.narrative")


def fmt_minutes(value: float | None) -> str:
    """Durations in the same shape the rest of the UI uses."""
    if value is None:
        return "—"
    total = int(round(float(value)))
    if total < 1:
        return "under a minute"
    if total < 60:
        return f"{total}m"
    hours, minutes = divmod(total, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _split_clock(value: float) -> tuple[int, int, int]:
    """Continuous hours to ``(days_over, hour, minute)``, rounding before wrapping.

    Order matters here and the obvious implementation gets it wrong. Rounding
    the minutes *after* taking the hour modulo 24 lets the minute carry push the
    time past midnight once the day has already been decided:

    * ``fmt_hour(23.999)`` returned ``"23:60"`` — not a time at all.
    * ``fmt_clock(23.999)`` returned ``"00:00"`` with no day qualifier, so a
      stop-time percentile a thousandth of an hour short of midnight was
      reported as the previous morning.

    Converting to whole minutes first makes the carry happen once, in the right
    place, and leaves the day count correct on the other side of it.
    """
    total_minutes = int(round(float(value) * 60))
    days_over, remainder = divmod(total_minutes, 24 * 60)
    hour, minute = divmod(remainder, 60)
    return days_over, hour, minute


def fmt_hour(value: float | None) -> str:
    if value is None:
        return "—"
    _days, hour, minute = _split_clock(value)
    return f"{hour:02d}:{minute:02d}"


def fmt_hour_range(value: float | None) -> str:
    if value is None:
        return "—"
    _days, hour, _minute = _split_clock(value)
    return f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"


def fmt_clock(value: float | None) -> str:
    """A time of day taken from the continuous hour scale.

    ``WorkSession.stop_hour`` unwraps a session ending after midnight to 25.5
    rather than 1.5, so that percentiles over stop times stay meaningful — the
    median of {23.8, 0.4, 22.9, 1.1} is otherwise about noon, a time this user
    has never stopped working at. Display has to wrap it back, and say which
    day it lands on, or "you usually stop by 02:40" reads as the small hours of
    the same morning.
    """
    if value is None:
        return "—"
    days_over, hour, minute = _split_clock(value)
    label = f"{hour:02d}:{minute:02d}"
    if days_over <= 0:
        return label
    if days_over == 1:
        # "the next morning" only when it actually is one. A session ending at
        # 23:59 of the following day is still one day over, and calling that
        # morning is simply wrong.
        return f"{label} the next morning" if hour < 12 else f"{label} the next day"
    return f"{label}, {days_over} days later"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(float(value) * 100)}%"


def fmt_ratio(value: float | None) -> str:
    """A multiplier, for "2.4x your usual" phrasings."""
    if value is None:
        return "—"
    return f"{float(value):.1f}x"


def magnitude(z: float) -> str:
    """Word for how far from normal something sits, in robust sigmas.

    Bucket edges are set where the language stops being defensible rather than
    at round numbers: below 1 sigma is inside the ordinary spread and gets a
    hedge, past 3 sigma is genuinely rare and can be stated plainly.

    The input must be a *scaled* z — see :meth:`Stat.robust_z`. Fed a raw MAD
    count these words overstate by about half: three raw MADs is 2.02 sigma,
    which is a thing that happens most months, not the "sharply" this returns.
    """
    z = abs(z)
    if z < 1.0:
        return "slightly"
    if z < 2.0:
        return "noticeably"
    if z < 3.0:
        return "clearly"
    return "sharply"


def describe_evidence(evidence: Evidence, days: int) -> str:
    """The "Based on ..." footer every card carries.

    Printed even when the basis is absolute, because "no history needed" is
    itself worth knowing — it distinguishes a rule that observed a fact from
    one that compared against a distribution.
    """
    if evidence.basis == "absolute":
        return "Observed directly, no history needed"
    # A within-day comparison is not a 30-day one, and saying "based on 29 days"
    # under a figure derived from three of today's hours misrepresents where the
    # number came from — the one thing this footer exists to prevent.
    if evidence.basis == "within_day":
        unit = "hours" if evidence.n != 1 else "hour"
        return f"Compared across today's {evidence.n} scored {unit}"
    if evidence.basis == "isolation_forest":
        return f"Flagged by anomaly detection over {days} days of your activity"
    if evidence.n <= 0:
        return f"Based on {days} days of your activity"
    unit = "samples" if evidence.n != 1 else "sample"
    return f"Based on {days} days of your activity ({evidence.n:,} {unit})"


def render(spec: RuleSpec, finding: Finding) -> tuple[str, str, str] | None:
    """Fill a rule's templates from its finding. ``None`` if a fact is missing.

    A missing key is a bug in the rule, not a runtime condition, so it is
    logged loudly and the finding is dropped — a card reading "you worked
    {run_text}" is worse than no card.
    """
    try:
        return (
            spec.title.format(**finding.facts),
            spec.why.format(**finding.facts),
            spec.action.format(**finding.facts),
        )
    except (KeyError, IndexError, ValueError) as exc:
        logger.error(
            "Rule %s emitted facts that do not satisfy its templates: %s "
            "(facts=%s)", spec.id, exc, sorted(finding.facts),
        )
        return None
