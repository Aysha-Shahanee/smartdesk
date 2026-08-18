"""Matched-comparison effect estimation.

The component that lets the app say "focus is lower after meetings" without
inventing the number. The obvious implementation — average focus in
post-meeting hours — answers a different question, because meetings are not
scattered at random through the week: they cluster in the morning, and mornings
differ from evenings for reasons that have nothing to do with meetings.

So each treated hour is matched to control hours at the *same hour of the same
weekday* on days with no meeting, and the estimate is the median of the paired
differences. Both arms must clear a sample floor or nothing is returned at all,
which is the difference between this and the hardcoded claim it replaces.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.recommendations.baselines import percentile
from app.services.recommendations.stats import sign_test

logger = logging.getLogger("smartdesk.recommendations.effects")

#: Minimum observations in each arm. Below this the median of the differences
#: is one or two hours wearing a decimal point, and reporting it would be the
#: precise failure this module exists to prevent.
MIN_ARM_SAMPLES = 8

#: How long after a meeting ends the "recovery" window runs.
RECOVERY_MINUTES = 60


def _merge_spans(
    spans: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Sort and coalesce overlapping intervals into a disjoint, ordered list.

    Back-to-back meetings produce recovery windows that overlap, and merging
    them first is what lets the membership test below be a binary search
    instead of a scan over every meeting for every window.
    """
    merged: list[tuple[datetime, datetime]] = []
    for start, stop in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged


@dataclass
class MatchedEffect:
    """A paired comparison, with everything needed to judge it."""

    treated_median: float
    control_median: float
    n_treated: int
    n_control: int
    #: Relative change, negative meaning the treatment arm scored lower.
    relative: float
    #: Two-sided p from a sign test over the matched pairs.
    #:
    #: The pairing is what makes this rule the strongest claim the engine
    #: makes, and it is also what makes an effect size on its own misleading:
    #: eleven pairs that mostly moved down look identical to eleven that split
    #: six-five, once you take the median. The sign test asks the only
    #: question the design supports — did the differences fall on one side
    #: more often than a coin would explain — without assuming anything about
    #: their shape.
    pair_p: float = 1.0
    #: How many matched slots the p-value is computed over.
    n_pairs: int = 0

    @property
    def credible(self) -> bool:
        return (
            self.n_treated >= MIN_ARM_SAMPLES
            and self.n_control >= MIN_ARM_SAMPLES
        )


def post_meeting_focus_effect(
    db: Session,
    user_id: str,
    window_start: datetime,
    window_end: datetime,
) -> MatchedEffect | None:
    """Focus in the hour after a meeting, against matched meeting-free hours.

    Returns ``None`` when either arm is too thin, when there are no meetings at
    all, or when no control hour matches a treated one — all of which are
    ordinary conditions rather than errors.
    """
    windows = db.execute(
        text("""
            SELECT window_start, avg_focus_score
            FROM activity_window_10m
            WHERE window_start >= :start AND window_start < :end
              AND active_seconds > 0
        """),
        {
            "start": window_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ).mappings().all()
    if not windows:
        return None

    meetings = db.execute(
        text("""
            SELECT start_time, end_time
            FROM calendar_events
            WHERE user_id = :user_id AND status != 'cancelled'
              AND start_time >= :start AND start_time < :end
        """),
        {
            "user_id": user_id,
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
    ).mappings().all()
    if not meetings:
        return None

    recovery_spans: list[tuple[datetime, datetime]] = []
    meeting_days: set[str] = set()
    for row in meetings:
        try:
            end = datetime.fromisoformat(str(row["end_time"]))
        except (TypeError, ValueError):
            continue
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        recovery_spans.append((end, end + timedelta(minutes=RECOVERY_MINUTES)))
        meeting_days.add(end.strftime("%Y-%m-%d"))

    if not recovery_spans:
        return None

    # Merged once, then binary-searched per window. The obvious `any(...)` over
    # every span inside the window loop is O(windows x meetings), and with a
    # 30-day window against a full calendar that scan was the most expensive
    # thing in the daily feature build.
    merged = _merge_spans(recovery_spans)
    span_starts = [start for start, _ in merged]

    def in_recovery(when: datetime) -> bool:
        index = bisect_right(span_starts, when) - 1
        return index >= 0 and when < merged[index][1]

    treated: dict[tuple[int, int], list[float]] = {}
    control: dict[tuple[int, int], list[float]] = {}

    for row in windows:
        try:
            when = datetime.fromisoformat(str(row["window_start"]))
        except (TypeError, ValueError):
            continue
        focus = float(row["avg_focus_score"] or 0.0)
        key = (when.weekday(), when.hour)

        if in_recovery(when):
            treated.setdefault(key, []).append(focus)
        elif when.strftime("%Y-%m-%d") not in meeting_days:
            # Controls are drawn only from days with no meeting at all. A
            # meeting-free hour on a meeting-heavy day is not a clean control:
            # whatever made the day busy is present in both arms.
            control.setdefault(key, []).append(focus)

    # Only slots present in both arms contribute — that is what "matched" means.
    differences: list[float] = []
    treated_values: list[float] = []
    control_values: list[float] = []
    for key, treated_focus in treated.items():
        control_focus = control.get(key)
        if not control_focus:
            continue
        treated_median = percentile(treated_focus, 0.50)
        control_median = percentile(control_focus, 0.50)
        differences.append(treated_median - control_median)
        treated_values.extend(treated_focus)
        control_values.extend(control_focus)

    if not differences:
        return None

    treated_overall = percentile(treated_values, 0.50)
    control_overall = percentile(control_values, 0.50)
    effect = MatchedEffect(
        treated_median=treated_overall,
        control_median=control_overall,
        n_treated=len(treated_values),
        n_control=len(control_values),
        relative=(
            (treated_overall - control_overall) / control_overall
            if control_overall > 0 else 0.0
        ),
        pair_p=sign_test(differences),
        n_pairs=len(differences),
    )
    if not effect.credible:
        logger.debug(
            "post-meeting effect suppressed: n_treated=%d n_control=%d "
            "(floor %d in each arm)",
            effect.n_treated, effect.n_control, MIN_ARM_SAMPLES,
        )
        return None
    return effect
