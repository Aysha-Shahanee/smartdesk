"""Personal baselines — the component that makes the rules yours.

Every threshold in the rule catalogue marked *personal* resolves here. The
point is that "you switched apps a lot" is not a claim anyone can check, while
"you switched apps more in the last fifteen minutes than in 90% of your
recorded quarter-hours" is. A generic constant would fire on a different user's
ordinary Tuesday; a percentile of your own history cannot.

Robust statistics throughout — median and MAD rather than mean and standard
deviation. Activity data is heavily skewed and full of legitimate outliers (one
nine-and-a-half-hour day sits among a run of two-hour ones), and a mean-based
threshold spends its whole range chasing them.

Computed nightly and cached. No live rule ever sorts an array; it reads a
``baseline.*`` key out of the feature snapshot.
"""

from __future__ import annotations

import math

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import local_now
from app.repositories.preference_repository import PreferenceRepository
from app.models.db import UserBaselineRecord

logger = logging.getLogger("smartdesk.recommendations.baselines")

#: How much history a baseline is computed over. Thirty days is long enough
#: that a single unusual week cannot move a percentile far, and short enough
#: that the numbers still describe how you work now rather than two months ago.
BASELINE_WINDOW_DAYS = 30

#: A percentile drawn from fewer samples than this is noise wearing a number's
#: clothes. Rules requiring such a baseline are gated out instead.
MIN_SAMPLES = 8

#: Scales the median absolute deviation into an estimate of sigma.
#:
#: 1 / Phi-inverse(0.75). Without it the MAD is about two thirds of the
#: standard deviation it stands in for, so a deviation of "three MADs" is
#: really 2.02 sigma — around the 96th percentile, which happens most months —
#: while the wording promises something rare. The constant is what makes the
#: robust z comparable to a normal-theory one, and therefore what makes the
#: language attached to it defensible. Rousseeuw & Croux (1993); Leys et al.
#: (2013) for the applied recommendation.
MAD_TO_SIGMA = 1.4826

#: Scales the interquartile range the same way, for the fallback below.
#: 1 / (2 * Phi-inverse(0.75)).
IQR_TO_SIGMA = 0.7413

#: Wall-clock gap between two active segments that a single block may span.
#:
#: Three minutes, and measured between *active* segments rather than reset by
#: any non-active one. The first version ended a block at every idle segment
#: whatever its length, which collapsed the whole notion: the OS collector
#: marks idle after 120 s of no input, which anyone reading the screen trips
#: constantly, so a two-hour stretch of work arrived as dozens of blocks and
#: the run-length p75 came out at eight minutes. Quoting that back as "your
#: sustainable run length" was visibly wrong, which is how the bug surfaced.
BLOCK_BRIDGE_SEC = 180.0

#: Minimum length for a block to count as deep work. Twenty-five minutes is the
#: shortest stretch that survived the segment splitter often enough to be
#: measurable: across the recorded history the median segment is 62 seconds, so
#: a deep block is always several rows stitched back together.
DEEP_BLOCK_MIN_SEC = 1500.0

DISTRACTION_CATEGORIES = ("entertainment", "social_media")

#: A gap this long separates one working day from the next.
#:
#: Needed because the local-date boundary does not. This user regularly works
#: past midnight — hours 00 and 01 hold 164 recorded windows between them — so
#: "the first activity of the calendar day" was 00:0x on every such day, the
#: median start hour came out as exactly midnight, and DY-08 announced "you
#: started 10h 26m later than usual" against a baseline that described nothing.
#: A day now starts at the first activity following a sleep-sized break; a
#: calendar day that merely continues the previous session has no start of its
#: own and contributes nothing to the baseline.
SLEEP_GAP_SEC = 4 * 3600.0


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile. Empty input yields 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    # Interpolated as an offset from the lower value rather than as a weighted
    # sum of both. Algebraically identical, numerically not: `v*(1-w) + v*w`
    # rounds twice and can land a hair off `v`, so two identical observations
    # produced a p10 fractionally *above* their p90. Percentile ordering is
    # assumed everywhere downstream — a rule comparing against p10 and p90 of a
    # near-constant metric would compare against a range that ran backwards.
    # This form returns the lower value exactly whenever the two agree, because
    # the difference is then exactly zero.
    low_value = ordered[low]
    return low_value + (ordered[high] - low_value) * weight


@dataclass
class Stat:
    """One metric's distribution."""

    n: int
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    mad: float

    @classmethod
    def of(cls, values: list[float]) -> "Stat":
        if not values:
            return cls(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        median = percentile(values, 0.50)
        mad = percentile([abs(v - median) for v in values], 0.50)
        return cls(
            n=len(values),
            p10=percentile(values, 0.10),
            p25=percentile(values, 0.25),
            p50=median,
            p75=percentile(values, 0.75),
            p90=percentile(values, 0.90),
            mad=mad,
        )

    @property
    def sigma(self) -> float:
        """Robust estimate of the standard deviation.

        The MAD scaled to be comparable with sigma, falling back to the
        interquartile range when the MAD collapses.

        That collapse is not exotic. The MAD is zero whenever more than half
        the observations tie, which for a count that is usually zero — meetings
        on a given day, say — is the normal state rather than a corner case.
        The rules answer that by staying silent, so precisely the metrics with
        the clearest signal (four meetings when the median is none) are the
        ones nothing can be said about. The IQR survives up to a quarter of the
        sample tying at each end, which covers most of them.

        Zero only when the distribution really is flat, which callers still
        have to handle: no spread means no way to call anything unusual.
        """
        if self.mad > 0:
            return self.mad * MAD_TO_SIGMA
        iqr = self.p75 - self.p25
        if iqr > 0:
            return iqr * IQR_TO_SIGMA
        return 0.0

    @property
    def usable(self) -> bool:
        return self.n >= MIN_SAMPLES

    def robust_z(self, value: float) -> float:
        """How many robust standard deviations from the median.

        Scaled by :data:`MAD_TO_SIGMA`, so the result sits on the same footing
        as an ordinary z-score and the words attached to it in
        :func:`narrative.magnitude` mean what they say. No usable spread at all
        means a flat distribution, where any deviation is the whole signal —
        reported as a large z rather than a division by zero.
        """
        spread = self.sigma
        if spread > 0:
            z = (value - self.p50) / spread
            # A spread can be positive and still too small to divide by. A
            # subnormal one — which arises whenever a metric is constant to
            # within the last representable bit — passes the check above and
            # then overflows, handing every caller an infinite z: `magnitude`
            # reads it as "sharply", and any rule multiplying by it produces
            # nan. Treated as the flat distribution it effectively is.
            if math.isfinite(z):
                return z
        return 0.0 if value == self.p50 else (3.0 if value > self.p50 else -3.0)


@dataclass
class BaselineSet:
    """Every baseline for one user, ready to be flattened into features."""

    global_stats: dict[str, Stat] = field(default_factory=dict)
    hour_focus: dict[int, float] = field(default_factory=dict)
    hour_samples: dict[int, int] = field(default_factory=dict)
    #: Deep-work minutes per weekday (0=Monday), one entry per recorded day.
    weekday_deep: dict[int, list[float]] = field(default_factory=dict)
    #: The user's usual category split, as shares summing to 1.
    category_mix: dict[str, float] = field(default_factory=dict)
    days_of_history: int = 0
    computed_at: str = ""

    def flatten(self) -> dict[str, float]:
        """Expand into the flat ``baseline.<metric>.<stat>`` keys rules read."""
        out: dict[str, float] = {}
        for metric, stat in self.global_stats.items():
            if not stat.usable:
                # Left absent on purpose: requirement gating then skips every
                # rule that depends on it, which is how the engine declines to
                # make a statistical claim it has no grounds for.
                continue
            out[f"baseline.{metric}.p10"] = stat.p10
            out[f"baseline.{metric}.p25"] = stat.p25
            out[f"baseline.{metric}.p50"] = stat.p50
            out[f"baseline.{metric}.p75"] = stat.p75
            out[f"baseline.{metric}.p90"] = stat.p90
            out[f"baseline.{metric}.mad"] = stat.mad
            out[f"baseline.{metric}.sigma"] = stat.sigma
            out[f"baseline.{metric}.n"] = float(stat.n)
        return out

    def peak_hours(self, count: int = 2) -> list[int]:
        """Your best focus hours, by median window focus.

        Only hours with enough windows behind them are eligible — a single
        brilliant 3 a.m. window should not become "your peak hour".
        """
        eligible = [
            (hour, score)
            for hour, score in self.hour_focus.items()
            if self.hour_samples.get(hour, 0) >= MIN_SAMPLES
        ]
        eligible.sort(key=lambda item: item[1], reverse=True)
        return [hour for hour, _ in eligible[:count]]

    def trough_hours(self, count: int = 2) -> list[int]:
        eligible = [
            (hour, score)
            for hour, score in self.hour_focus.items()
            if self.hour_samples.get(hour, 0) >= MIN_SAMPLES
        ]
        eligible.sort(key=lambda item: item[1])
        return [hour for hour, _ in eligible[:count]]

    def trough_hours_within(self, lo: int, hi: int, count: int = 1) -> list[int]:
        """Weakest hours restricted to a band.

        Needed because a purely statistical trough is not always an actionable
        one. This user's lowest-focus hour is 02:00, and "schedule your
        meetings at 2 a.m." is a correct reading of the data and a useless
        thing to say — meetings involve other people, whatever the focus
        numbers do. The band is a domain constraint the statistic cannot know
        about, applied explicitly rather than by hoping the data avoids it.
        """
        eligible = [
            (hour, score)
            for hour, score in self.hour_focus.items()
            if self.hour_samples.get(hour, 0) >= MIN_SAMPLES and lo <= hour < hi
        ]
        eligible.sort(key=lambda item: item[1])
        return [hour for hour, _ in eligible[:count]]


# ---------------------------------------------------------------------- #
# Block helpers — shared with the feature builder                          #
# ---------------------------------------------------------------------- #

@dataclass
class WorkSession:
    """One waking stretch of work, bounded by sleep-sized gaps.

    The unit the day-shape metrics are actually about. A calendar day is the
    wrong frame for both ends of it: a session beginning at 21:00 and ending at
    01:30 spans two local dates, so "the first activity of the day" reports
    00:00 for the second one and "the last activity of the day" reports 23:59
    for the first. Both baselines were describing the midnight boundary rather
    than the user.
    """

    start: datetime
    end: datetime

    @property
    def start_hour(self) -> float:
        return self.start.hour + self.start.minute / 60.0

    @property
    def stop_hour(self) -> float:
        """End hour on a continuous scale, so a session ending after midnight
        reads as 25.5 rather than 1.5.

        Without this the median of {23.8, 0.4, 22.9, 1.1} is about 12:00 — a
        time this user has never once stopped working at. Percentiles are
        meaningless on a wrapped circular quantity; unwrapping relative to the
        session's own start is what makes them ordinary numbers again.
        """
        days_over = (self.end.date() - self.start.date()).days
        return self.end.hour + self.end.minute / 60.0 + 24.0 * days_over


def build_work_sessions(segments: list[dict]) -> list[WorkSession]:
    """Split active segments into waking stretches separated by SLEEP_GAP_SEC."""
    sessions: list[WorkSession] = []
    current: WorkSession | None = None
    for segment in segments:
        if segment["state"] != "active":
            continue
        if (
            current is None
            or (segment["start"] - current.end).total_seconds() >= SLEEP_GAP_SEC
        ):
            current = WorkSession(start=segment["start"], end=segment["end"])
            sessions.append(current)
        else:
            current.end = max(current.end, segment["end"])
    return sessions


@dataclass
class Block:
    """A contiguous stretch of non-idle activity."""

    start: datetime
    end: datetime
    focus_weighted: float = 0.0
    focus_duration: float = 0.0

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def focus(self) -> float:
        return self.focus_weighted / self.focus_duration if self.focus_duration else 0.0


def build_blocks(segments: list[dict]) -> list[Block]:
    """Stitch consecutive non-idle segments back into continuous blocks.

    The segment splitter cuts on every app change, every IDE/browser session
    edge and at its 900 s cap, so one unbroken hour of work arrives as a dozen
    rows. Any rule about sustained attention has to undo that first.
    """
    blocks: list[Block] = []
    current: Block | None = None

    for segment in segments:
        # Non-active segments are skipped rather than treated as terminators.
        # The gap test below subsumes them: a short idle leaves a short gap
        # between the active segments around it and the block survives, while
        # a real absence leaves a long one and it does not.
        if segment["state"] != "active":
            continue
        start, end = segment["start"], segment["end"]
        if current is not None and (start - current.end).total_seconds() <= BLOCK_BRIDGE_SEC:
            current.end = max(current.end, end)
        else:
            current = Block(start=start, end=end)
            blocks.append(current)
        if segment.get("focus") is not None:
            duration = (end - start).total_seconds()
            current.focus_weighted += segment["focus"] * duration
            current.focus_duration += duration

    return blocks


def fetch_segments(
    db: Session,
    user_id: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Load segments in a half-open range, ordered, as plain dicts.

    Returns dicts rather than ORM rows because every consumer treats them as
    read-only values and the identity map is pure overhead on 12k rows.
    """
    rows = db.execute(
        text("""
            SELECT start_time_utc, end_time_utc, duration_sec, state, app_name,
                   title, detail, category, category_confidence, focus_score,
                   local_date, primary_source
            FROM activity_segments
            WHERE user_id = :user_id
              AND start_time_utc >= :start
              AND start_time_utc < :end
            ORDER BY start_time_utc
        """),
        {
            "user_id": user_id,
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ).mappings().all()

    segments: list[dict] = []
    for row in rows:
        try:
            seg_start = datetime.fromisoformat(row["start_time_utc"])
            seg_end = datetime.fromisoformat(row["end_time_utc"])
        except (TypeError, ValueError):
            continue
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "duration": float(row["duration_sec"] or 0),
            "state": row["state"],
            "app": row["app_name"],
            "title": row["title"],
            "detail": row["detail"],
            "category": row["category"],
            "confidence": row["category_confidence"],
            "focus": row["focus_score"],
            "local_date": row["local_date"],
            "source": row["primary_source"],
        })
    return segments


# ---------------------------------------------------------------------- #
# Computation                                                              #
# ---------------------------------------------------------------------- #

class BaselineBuilder:
    """Computes and persists a user's baselines."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def compute(
        self,
        db: Session,
        user_id: str,
        as_of: datetime | None = None,
    ) -> BaselineSet:
        as_of = as_of or local_now()
        window_start = as_of - timedelta(days=BASELINE_WINDOW_DAYS)

        # A user who has reset their baselines is asking not to be compared
        # against who they were before a job change or a new project. Honoured
        # by moving the window forward, not by deleting anything: the activity
        # is still recorded, still in the timeline, and clearing the epoch
        # restores every comparison.
        epoch = PreferenceRepository(db).baseline_epoch(user_id)
        if epoch:
            try:
                boundary = datetime.fromisoformat(f"{epoch}T00:00:00")
                if boundary > window_start:
                    window_start = boundary
            except ValueError:
                logger.warning("Ignoring unparseable baseline epoch %r", epoch)

        segments = fetch_segments(db, user_id, window_start, as_of)

        result = BaselineSet(computed_at=as_of.isoformat())
        if not segments:
            return result

        result.days_of_history = len({s["local_date"] for s in segments})

        # ---- window-derived metrics -------------------------------------
        window_rows = db.execute(
            text("""
                SELECT window_start, active_seconds, idle_seconds, app_switches,
                       category_switches, unique_apps, avg_focus_score
                FROM activity_window_10m
                WHERE window_start >= :start AND window_start < :end
                  AND active_seconds > 0
            """),
            {
                "start": window_start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": as_of.strftime("%Y-%m-%d %H:%M:%S"),
            },
        ).mappings().all()

        focus_values: list[float] = []
        hour_buckets: dict[int, list[float]] = {}
        switch_rates: list[float] = []
        category_switches: list[float] = []
        unique_apps: list[float] = []

        for row in window_rows:
            focus = float(row["avg_focus_score"] or 0.0)
            focus_values.append(focus)
            # app_switches counts transitions inside a 10-minute window, so
            # dividing by 10 gives the per-minute rate the live rules compare
            # against — the same unit FocusScorer.SWITCH_TOLERANCE is set in.
            switch_rates.append(float(row["app_switches"] or 0) / 10.0)
            category_switches.append(float(row["category_switches"] or 0))
            unique_apps.append(float(row["unique_apps"] or 0))
            try:
                hour = int(str(row["window_start"])[11:13])
            except (ValueError, IndexError):
                continue
            hour_buckets.setdefault(hour, []).append(focus)

        result.global_stats["focus"] = Stat.of(focus_values)
        result.global_stats["switch_rate"] = Stat.of(switch_rates)
        result.global_stats["category_switches"] = Stat.of(category_switches)
        result.global_stats["unique_apps"] = Stat.of(unique_apps)

        for hour, values in hour_buckets.items():
            result.hour_focus[hour] = percentile(values, 0.50)
            result.hour_samples[hour] = len(values)

        # ---- per-day metrics ---------------------------------------------
        by_day: dict[str, list[dict]] = {}
        for segment in segments:
            by_day.setdefault(segment["local_date"], []).append(segment)

        active_minutes: list[float] = []
        deep_minutes: list[float] = []
        fragmentation: list[float] = []
        distraction_share: list[float] = []
        idle_share: list[float] = []
        run_lengths: list[float] = []

        focus_p75 = result.global_stats["focus"].p75

        for day_segments in by_day.values():
            active = [s for s in day_segments if s["state"] == "active"]
            if not active:
                continue

            active_sec = sum(s["duration"] for s in active)
            idle_sec = sum(s["duration"] for s in day_segments if s["state"] == "idle")
            active_minutes.append(active_sec / 60.0)

            if active_sec > 0:
                fragmentation.append(len(active) / (active_sec / 3600.0))
                distraction_sec = sum(
                    s["duration"] for s in active
                    if s["category"] in DISTRACTION_CATEGORIES
                )
                distraction_share.append(distraction_sec / active_sec)
            total_tracked = active_sec + idle_sec
            if total_tracked > 0:
                idle_share.append(idle_sec / total_tracked)

            blocks = build_blocks(day_segments)
            run_lengths.extend(b.seconds / 60.0 for b in blocks)
            deep_minutes.append(sum(
                b.seconds / 60.0 for b in blocks
                if b.seconds >= DEEP_BLOCK_MIN_SEC and b.focus >= focus_p75
            ))

        # Both ends of the day come from work sessions, not from calendar days.
        # The first session in the window is dropped: the fetch begins mid-history
        # so its start may be a continuation of a session that began before it.
        sessions = build_work_sessions(segments)[1:]
        start_hours = [session.start_hour for session in sessions]
        stop_hours = [session.stop_hour for session in sessions]

        # Deep-work minutes per weekday, for the weekly family.
        for day_key, day_segments in by_day.items():
            try:
                weekday = datetime.fromisoformat(f"{day_key}T00:00:00").weekday()
            except ValueError:
                continue
            minutes = sum(
                b.seconds / 60.0 for b in build_blocks(day_segments)
                if b.seconds >= DEEP_BLOCK_MIN_SEC and b.focus >= focus_p75
            )
            result.weekday_deep.setdefault(weekday, []).append(minutes)

        result.global_stats["daily_active_min"] = Stat.of(active_minutes)
        result.global_stats["deep_work_min"] = Stat.of(deep_minutes)
        result.global_stats["frag_index"] = Stat.of(fragmentation)
        result.global_stats["distraction_share"] = Stat.of(distraction_share)
        result.global_stats["idle_share"] = Stat.of(idle_share)
        result.global_stats["start_hour"] = Stat.of(start_hours)
        result.global_stats["stop_hour"] = Stat.of(stop_hours)
        result.global_stats["run_len"] = Stat.of(run_lengths)

        # The usual category split, for DY-11. Computed over the whole window
        # rather than averaged across days, so a short day does not carry the
        # same weight as a long one.
        mix_totals: dict[str, float] = {}
        for segment in segments:
            if segment["state"] != "active":
                continue
            key = segment["category"] or "uncategorised"
            mix_totals[key] = mix_totals.get(key, 0.0) + segment["duration"]
        grand = sum(mix_totals.values())
        if grand > 0:
            result.category_mix = {k: v / grand for k, v in mix_totals.items()}

        return result

    def persist(self, db: Session, user_id: str, baselines: BaselineSet) -> int:
        """Replace this user's stored baselines. Returns the row count written.

        A full replace rather than an upsert: the set of metrics is small and
        fixed, and a metric that stops being computable should disappear rather
        than linger at whatever it last read.
        """
        db.query(UserBaselineRecord).filter(
            UserBaselineRecord.user_id == user_id
        ).delete(synchronize_session=False)

        written = 0
        for metric, stat in baselines.global_stats.items():
            db.add(UserBaselineRecord(
                id=str(uuid.uuid4()),
                user_id=user_id,
                metric=metric,
                dim_key="",
                n=stat.n,
                p10=stat.p10, p25=stat.p25, p50=stat.p50,
                p75=stat.p75, p90=stat.p90, mad=stat.mad,
                computed_at=baselines.computed_at,
            ))
            written += 1

        for hour, score in baselines.hour_focus.items():
            db.add(UserBaselineRecord(
                id=str(uuid.uuid4()),
                user_id=user_id,
                metric="hour_focus",
                dim_key=f"{hour:02d}",
                n=baselines.hour_samples.get(hour, 0),
                p10=score, p25=score, p50=score, p75=score, p90=score, mad=0.0,
                computed_at=baselines.computed_at,
            ))
            written += 1

        db.commit()
        logger.info("Wrote %d baseline rows for %s", written, user_id)
        return written
