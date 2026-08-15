"""Weekly and monthly feature construction.

Both scopes are built from the same per-day summary pass, so a figure quoted in
a weekly card and the same figure rolled into a monthly one cannot disagree.
Kept out of ``features.py`` because the live path imports that module on a
60-second timer and has no use for any of this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.recommendations.baselines import (
    BaselineSet,
    DEEP_BLOCK_MIN_SEC,
    DISTRACTION_CATEGORIES,
    build_blocks,
    build_work_sessions,
    fetch_segments,
    percentile,
)
from app.services.recommendations.types import FeatureContext

logger = logging.getLogger("smartdesk.recommendations.periods")

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday")

#: How many trailing weeks the four-week trend needs. Below this a slope is
#: fitted through so few points that its sign is close to arbitrary.
TREND_MIN_WEEKS = 4

#: A session ending past this hour on the continuous scale counts as late
#: night. 24.0 is literally "after midnight", which is the thing being counted.
LATE_NIGHT_HOUR = 24.0


@dataclass
class DaySummary:
    """One local day, reduced to the handful of numbers the period rules use."""

    date: str
    weekday: int
    active_min: float
    deep_min: float
    distraction_min: float
    learn_min: float
    focus: float
    meeting_min: float
    latest_stop_hour: float | None
    category_min: dict[str, float]

    @property
    def is_weekend(self) -> bool:
        return self.weekday >= 5

    @property
    def distraction_share(self) -> float:
        return self.distraction_min / self.active_min if self.active_min else 0.0


def summarise_days(
    db: Session,
    user_id: str,
    start: datetime,
    end: datetime,
    baselines: BaselineSet,
) -> list[DaySummary]:
    """One pass over a date range, reduced to per-day summaries.

    A single segment fetch for the whole range rather than one per day: at 30
    days that is the difference between one query and thirty, and the grouping
    is trivial once the rows are in memory.
    """
    segments = fetch_segments(db, user_id, start, end)
    if not segments:
        return []

    focus_stat = baselines.global_stats.get("focus")
    deep_bar = focus_stat.p75 if focus_stat and focus_stat.usable else 0.5

    meetings = _meeting_minutes_by_day(db, user_id, start, end)

    by_day: dict[str, list[dict]] = {}
    for segment in segments:
        by_day.setdefault(segment["local_date"], []).append(segment)

    summaries: list[DaySummary] = []
    for date_key in sorted(by_day):
        day_segments = by_day[date_key]
        active = [s for s in day_segments if s["state"] == "active"]
        if not active:
            continue
        try:
            weekday = datetime.fromisoformat(f"{date_key}T00:00:00").weekday()
        except ValueError:
            continue

        active_sec = sum(s["duration"] for s in active)
        category_min: dict[str, float] = {}
        for segment in active:
            key = segment["category"] or "uncategorised"
            category_min[key] = category_min.get(key, 0.0) + segment["duration"] / 60.0

        blocks = build_blocks(day_segments)
        deep_sec = sum(
            b.seconds for b in blocks
            if b.seconds >= DEEP_BLOCK_MIN_SEC and b.focus >= deep_bar
        )

        focus_weight = sum(s["duration"] for s in active if s["focus"] is not None)
        focus = (
            sum((s["focus"] or 0) * s["duration"] for s in active if s["focus"] is not None)
            / focus_weight
            if focus_weight
            else 0.0
        )

        sessions = [
            session for session in build_work_sessions(day_segments)
            if session.start.date().isoformat() == date_key
        ]

        summaries.append(DaySummary(
            date=date_key,
            weekday=weekday,
            active_min=active_sec / 60.0,
            deep_min=deep_sec / 60.0,
            distraction_min=sum(
                s["duration"] for s in active
                if s["category"] in DISTRACTION_CATEGORIES
            ) / 60.0,
            learn_min=category_min.get("learn", 0.0),
            focus=focus,
            meeting_min=meetings.get(date_key, 0.0),
            latest_stop_hour=max(
                (s.stop_hour for s in sessions), default=None
            ),
            category_min=category_min,
        ))
    return summaries


def _meeting_minutes_by_day(
    db: Session, user_id: str, start: datetime, end: datetime
) -> dict[str, float]:
    rows = db.execute(
        text("""
            SELECT start_time, duration_sec
            FROM calendar_events
            WHERE user_id = :user_id AND status != 'cancelled'
              AND start_time >= :start AND start_time < :end
        """),
        {"user_id": user_id, "start": start.isoformat(), "end": end.isoformat()},
    ).mappings().all()
    out: dict[str, float] = {}
    for row in rows:
        key = str(row["start_time"])[:10]
        out[key] = out.get(key, 0.0) + float(row["duration_sec"] or 0) / 60.0
    return out


def theil_sen_slope(values: list[float]) -> float | None:
    """Median of pairwise slopes — the robust alternative to least squares.

    Chosen because one exceptional week should not set the direction of a
    four-week trend, and with only four points least squares lets it.
    """
    if len(values) < 3:
        return None
    slopes = [
        (values[j] - values[i]) / (j - i)
        for i in range(len(values))
        for j in range(i + 1, len(values))
    ]
    return percentile(slopes, 0.50) if slopes else None


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, for "does meeting load track focus?".

    Rank-based rather than Pearson because neither quantity is remotely normal
    and a single 9.5-hour day would otherwise drive the coefficient.
    """
    if len(xs) != len(ys) or len(xs) < 6:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    den_x = sum((a - mean_x) ** 2 for a in rx) ** 0.5
    den_y = sum((b - mean_y) ** 2 for b in ry) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


# ---------------------------------------------------------------------- #
# Weekly                                                                   #
# ---------------------------------------------------------------------- #

def build_weekly_context(
    db: Session,
    user_id: str,
    week_end: datetime,
    baselines: BaselineSet,
) -> FeatureContext:
    """Snapshot describing the seven completed days ending at ``week_end``."""
    week_end = week_end.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_end - timedelta(days=7)
    # Four weeks of history so the trend has something to fit.
    history_start = week_end - timedelta(days=7 * TREND_MIN_WEEKS)

    days = summarise_days(db, user_id, history_start, week_end, baselines)
    this_week = [d for d in days if d.date >= week_start.strftime("%Y-%m-%d")]

    data: dict = {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": (week_end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "week_day_count": float(len(this_week)),
    }
    if not this_week:
        data.update(baselines.flatten())
        return FeatureContext(
            data, as_of=week_end, user_id=user_id,
            days_of_history=baselines.days_of_history,
        )

    data["week_active_min"] = sum(d.active_min for d in this_week)
    data["week_deep_min"] = sum(d.deep_min for d in this_week)
    data["week_active_days"] = float(len(this_week))

    # WK-01 — strongest and weakest weekday, across all recorded weeks so a
    # single bad Tuesday cannot name Tuesday the weak day.
    by_weekday: dict[int, list[float]] = {}
    for day in days:
        by_weekday.setdefault(day.weekday, []).append(day.deep_min)
    ranked = sorted(
        ((wd, percentile(v, 0.50), len(v)) for wd, v in by_weekday.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    eligible = [item for item in ranked if item[2] >= 2]
    if len(eligible) >= 3:
        data["best_weekday"] = WEEKDAY_NAMES[eligible[0][0]]
        data["best_weekday_deep"] = eligible[0][1]
        data["worst_weekday"] = WEEKDAY_NAMES[eligible[-1][0]]
        data["worst_weekday_deep"] = eligible[-1][1]
        data["weekday_sample_weeks"] = float(min(item[2] for item in eligible))

    # WK-02 — weekday vs weekend.
    weekend_min = sum(d.active_min for d in this_week if d.is_weekend)
    if data["week_active_min"] > 0:
        data["weekend_share"] = weekend_min / data["week_active_min"]
        data["weekend_min"] = weekend_min

    # WK-03 — four-week trend in deep-work minutes.
    weekly_totals: list[float] = []
    for index in range(TREND_MIN_WEEKS):
        bucket_end = week_end - timedelta(days=7 * index)
        bucket_start = bucket_end - timedelta(days=7)
        total = sum(
            d.deep_min for d in days
            if bucket_start.strftime("%Y-%m-%d") <= d.date < bucket_end.strftime("%Y-%m-%d")
        )
        weekly_totals.append(total)
    weekly_totals.reverse()
    if len([t for t in weekly_totals if t > 0]) >= 3:
        slope = theil_sen_slope(weekly_totals)
        if slope is not None:
            data["deep_trend_slope"] = slope
            data["deep_trend_weeks"] = float(len(weekly_totals))
            data["deep_trend_first"] = weekly_totals[0]
            data["deep_trend_last"] = weekly_totals[-1]

    # WK-04 — meeting load against focus.
    with_meetings = [d for d in days if d.meeting_min > 0]
    if len(with_meetings) >= 6:
        rho = spearman(
            [d.meeting_min for d in days], [d.focus for d in days]
        )
        if rho is not None:
            data["meeting_focus_rho"] = rho
            data["meeting_focus_n"] = float(len(days))

    # WK-05 — consistency of daily active hours.
    actives = [d.active_min for d in this_week]
    if len(actives) >= 4:
        data["week_active_iqr"] = percentile(actives, 0.75) - percentile(actives, 0.25)
        data["week_active_median"] = percentile(actives, 0.50)

    # WK-06 — focus drift from the week's first workday to its last. Fitted
    # over the days in order rather than compared end to end, so one weak
    # Friday does not define the week.
    ordered = sorted(this_week, key=lambda d: d.date)
    scored = [d.focus for d in ordered if d.focus > 0]
    if len(scored) >= 4:
        slope = theil_sen_slope(scored)
        if slope is not None:
            data["week_focus_slope"] = slope
            data["week_focus_first"] = scored[0]
            data["week_focus_last"] = scored[-1]
            data["week_focus_days"] = float(len(scored))

    # WK-09 — which languages the editor time went to, and how that moved.
    languages = db.execute(
        text("""
            SELECT dominant_language, SUM(duration_sec) / 60.0 AS minutes
            FROM ide_sessions
            WHERE user_id = :user_id AND session_start >= :start
              AND session_start < :end AND dominant_language IS NOT NULL
            GROUP BY dominant_language ORDER BY minutes DESC
        """),
        {
            "user_id": user_id,
            "start": week_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": week_end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ).mappings().all()
    if languages:
        total = sum(float(r["minutes"] or 0) for r in languages)
        if total > 0:
            data["top_language"] = languages[0]["dominant_language"]
            data["top_language_share"] = float(languages[0]["minutes"] or 0) / total
            data["language_count"] = float(len(languages))
            data["top_language_min"] = float(languages[0]["minutes"] or 0)

    # WK-07 — a distraction slot recurring at the same hour of the week.
    recurring = _recurring_distraction_hour(db, user_id, history_start, week_end)
    if recurring:
        data["recurring_hour"], data["recurring_weeks"] = recurring

    # WK-08 — where the coding time went.
    workspaces = db.execute(
        text("""
            SELECT workspace_name, SUM(duration_sec) / 60.0 AS minutes
            FROM ide_sessions
            WHERE user_id = :user_id AND session_start >= :start AND session_start < :end
              AND workspace_name IS NOT NULL
            GROUP BY workspace_name ORDER BY minutes DESC LIMIT 3
        """),
        {
            "user_id": user_id,
            "start": week_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": week_end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ).mappings().all()
    if workspaces:
        data["top_workspace"] = workspaces[0]["workspace_name"]
        data["top_workspace_min"] = float(workspaces[0]["minutes"] or 0)
        data["workspace_count"] = float(len(workspaces))

    # WK-10 — learning share against the trailing norm.
    learn_min = sum(d.learn_min for d in this_week)
    if data["week_active_min"] > 0:
        data["week_learn_share"] = learn_min / data["week_active_min"]
        data["week_learn_min"] = learn_min
    prior = [d for d in days if d.date < week_start.strftime("%Y-%m-%d")]
    prior_active = sum(d.active_min for d in prior)
    if prior_active > 0:
        data["prior_learn_share"] = sum(d.learn_min for d in prior) / prior_active

    # WK-11 — consecutive days meeting the deep-work median.
    deep_stat = baselines.global_stats.get("deep_work_min")
    if deep_stat and deep_stat.usable and deep_stat.p50 > 0:
        streak = 0
        for day in reversed(days):
            if day.deep_min >= deep_stat.p50:
                streak += 1
            else:
                break
        data["deep_streak_days"] = float(streak)
        data["deep_streak_bar"] = deep_stat.p50

    # WK-12 — late nights.
    late = [
        d for d in this_week
        if d.latest_stop_hour is not None and d.latest_stop_hour >= LATE_NIGHT_HOUR
    ]
    data["late_night_count"] = float(len(late))

    data.update(baselines.flatten())
    return FeatureContext(
        data, as_of=week_end, user_id=user_id,
        days_of_history=baselines.days_of_history,
    )


def _recurring_distraction_hour(
    db: Session, user_id: str, start: datetime, end: datetime
) -> tuple[str, float] | None:
    """An hour-of-week distracted in at least three of the last four weeks.

    Read from the clustering rather than recomputed: ``focus_level`` is already
    stored per ten-minute window, and a slot that shows up as distracted week
    after week is a habit rather than a bad afternoon.
    """
    rows = db.execute(
        text("""
            SELECT window_start
            FROM activity_window_patterns
            WHERE scope = 'day' AND focus_level = 'distracted'
              AND window_start >= :start AND window_start < :end
        """),
        {
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ).mappings().all()

    slots: dict[tuple[int, int], set[str]] = {}
    for row in rows:
        try:
            when = datetime.fromisoformat(str(row["window_start"]))
        except (TypeError, ValueError):
            continue
        key = (when.weekday(), when.hour)
        slots.setdefault(key, set()).add(when.strftime("%Y-%W"))

    best = max(slots.items(), key=lambda item: len(item[1]), default=None)
    if best is None or len(best[1]) < 3:
        return None
    (weekday, hour), weeks = best
    return f"{WEEKDAY_NAMES[weekday]} around {hour:02d}:00", float(len(weeks))


# ---------------------------------------------------------------------- #
# Monthly                                                                  #
# ---------------------------------------------------------------------- #

def build_monthly_context(
    db: Session,
    user_id: str,
    month_end: datetime,
    baselines: BaselineSet,
) -> FeatureContext:
    """Snapshot comparing the trailing 30 days against the 30 before them."""
    month_end = month_end.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = month_end - timedelta(days=30)
    prior_start = month_start - timedelta(days=30)

    days = summarise_days(db, user_id, prior_start, month_end, baselines)
    boundary = month_start.strftime("%Y-%m-%d")
    current = [d for d in days if d.date >= boundary]
    prior = [d for d in days if d.date < boundary]

    data: dict = {
        "month_start": month_start.strftime("%Y-%m-%d"),
        "month_end": (month_end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "month_active_days": float(len(current)),
    }
    if not current:
        data.update(baselines.flatten())
        return FeatureContext(
            data, as_of=month_end, user_id=user_id,
            days_of_history=baselines.days_of_history,
        )

    data["month_active_min"] = sum(d.active_min for d in current)
    data["month_deep_min"] = sum(d.deep_min for d in current)

    # MO-01 — month-over-month deltas, only where a prior month exists to
    # compare against. Without this guard the first month would report a 100%
    # improvement on every metric.
    if len(prior) >= 10:
        data["prior_active_days"] = float(len(prior))
        for label, selector in (
            ("deep", lambda d: d.deep_min),
            ("active", lambda d: d.active_min),
            ("distraction", lambda d: d.distraction_min),
        ):
            now_median = percentile([selector(d) for d in current], 0.50)
            was_median = percentile([selector(d) for d in prior], 0.50)
            data[f"mo_{label}_now"] = now_median
            data[f"mo_{label}_prev"] = was_median
            if was_median > 0:
                data[f"mo_{label}_change"] = (now_median - was_median) / was_median

    # MO-04 — the month's best day, as a template to copy.
    best = max(current, key=lambda d: d.deep_min, default=None)
    if best is not None and best.deep_min > 0:
        data["best_day_date"] = best.date
        data["best_day_deep_min"] = best.deep_min
        data["best_day_weekday"] = WEEKDAY_NAMES[best.weekday]
        data["best_day_active_min"] = best.active_min
        if best.latest_stop_hour is not None:
            data["best_day_stop_hour"] = best.latest_stop_hour

    # MO-06 — where the hours moved between categories.
    def mix(rows: list[DaySummary]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for row in rows:
            for key, minutes in row.category_min.items():
                totals[key] = totals.get(key, 0.0) + minutes
        grand = sum(totals.values())
        return {k: v / grand for k, v in totals.items()} if grand else {}

    if len(prior) >= 10:
        now_mix, was_mix = mix(current), mix(prior)
        shifts = {
            key: now_mix.get(key, 0.0) - was_mix.get(key, 0.0)
            for key in set(now_mix) | set(was_mix)
        }
        if shifts:
            gained = max(shifts.items(), key=lambda kv: kv[1])
            lost = min(shifts.items(), key=lambda kv: kv[1])
            if gained[1] >= 0.05 or lost[1] <= -0.05:
                data["mix_gained"] = gained[0]
                data["mix_gained_delta"] = gained[1]
                data["mix_lost"] = lost[0]
                data["mix_lost_delta"] = lost[1]

    # MO-02 / MO-03 — habit formation and erosion. A metric that moved by at
    # least one MAD and *stayed* moved for three consecutive weeks is a habit;
    # the same movement in a single week is a good or bad week. Measured on
    # weekly medians so a single day cannot carry it.
    weekly_deep: list[float] = []
    for index in range(4):
        bucket_end = month_end - timedelta(days=7 * index)
        bucket_start = bucket_end - timedelta(days=7)
        window = [
            d.deep_min for d in current
            if bucket_start.strftime("%Y-%m-%d") <= d.date < bucket_end.strftime("%Y-%m-%d")
        ]
        if window:
            weekly_deep.append(percentile(window, 0.50))
    weekly_deep.reverse()

    if len(weekly_deep) >= 3 and prior:
        prior_median = percentile([d.deep_min for d in prior], 0.50)
        spread = percentile(
            [abs(d.deep_min - prior_median) for d in prior], 0.50
        )
        if spread > 0:
            above = [w for w in weekly_deep[-3:] if w - prior_median >= spread]
            below = [w for w in weekly_deep[-3:] if prior_median - w >= spread]
            if len(above) == 3:
                data["habit_direction"] = "formed"
                data["habit_weeks"] = 3.0
                data["habit_now"] = weekly_deep[-1]
                data["habit_before"] = prior_median
            elif len(below) == 3:
                data["habit_direction"] = "eroded"
                data["habit_weeks"] = 3.0
                data["habit_now"] = weekly_deep[-1]
                data["habit_before"] = prior_median

    # MO-05 — days where the anomaly detector flagged several windows at once.
    anomaly_days = db.execute(
        text("""
            SELECT substr(window_start, 1, 10) AS day, COUNT(*) AS n
            FROM activity_window_patterns
            WHERE scope = 'day' AND anomaly_score < 0
              AND window_start >= :start AND window_start < :end
            GROUP BY day HAVING n >= 3 ORDER BY n DESC LIMIT 3
        """),
        {
            "start": month_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": month_end.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ).mappings().all()
    if anomaly_days:
        data["anomaly_day_count"] = float(len(anomaly_days))
        data["anomaly_top_day"] = str(anomaly_days[0]["day"])
        data["anomaly_top_windows"] = float(anomaly_days[0]["n"])

    # MO-07 — how much of the month all four layers actually covered.
    layer_days = db.execute(
        text("""
            SELECT
              (SELECT COUNT(DISTINCT substr(session_start, 1, 10)) FROM ide_sessions
                WHERE user_id = :u AND session_start >= :s) AS ide_days,
              (SELECT COUNT(DISTINCT substr(session_start, 1, 10)) FROM browser_sessions
                WHERE user_id = :u AND session_start >= :s) AS browser_days
        """),
        {"u": user_id, "s": month_start.strftime("%Y-%m-%dT%H:%M:%S")},
    ).mappings().first()
    if layer_days and current:
        data["ide_coverage"] = float(layer_days["ide_days"] or 0) / len(current)
        data["browser_coverage"] = float(layer_days["browser_days"] or 0) / len(current)

    data.update(baselines.flatten())
    return FeatureContext(
        data, as_of=month_end, user_id=user_id,
        days_of_history=baselines.days_of_history,
    )
