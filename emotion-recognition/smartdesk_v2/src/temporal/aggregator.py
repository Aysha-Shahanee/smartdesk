"""Temporal aggregation for signal trends."""

from __future__ import annotations

from dataclasses import dataclass

from src.temporal.history import SignalHistory, TemporalAccumulator


@dataclass(frozen=True)
class EngagementSummary:
    """Aggregated visual engagement metrics for one temporal window."""

    start_timestamp: float | None
    end_timestamp: float | None
    block_start_time: str | None
    block_end_time: str | None
    window_seconds: float
    total_time: float
    face_visible_ratio: float
    screen_facing_ratio: float
    looking_away_ratio: float
    long_lookaway_count: int
    ready: bool


@dataclass(frozen=True)
class SleepinessSummary:
    """Aggregated visual sleepiness metrics for one temporal window."""

    start_timestamp: float | None
    end_timestamp: float | None
    block_start_time: str | None
    block_end_time: str | None
    window_seconds: float
    total_time: float
    face_visible_ratio: float
    perclos: float
    eye_closed_ratio: float
    head_down_ratio: float
    possible_yawn_ratio: float
    long_eye_closure_count: int
    yawn_count: int
    ready: bool


@dataclass(frozen=True)
class TemporalSummary:
    """Aggregated metrics for both engagement and sleepiness windows."""

    engagement: EngagementSummary
    sleepiness: SleepinessSummary


def summarize_engagement(accumulator: TemporalAccumulator) -> EngagementSummary:
    """Summarize the current engagement accumulator."""
    accumulator.close_open_events()
    total = accumulator.total_time
    return EngagementSummary(
        start_timestamp=accumulator.start_timestamp,
        end_timestamp=accumulator.last_timestamp,
        block_start_time=None,
        block_end_time=None,
        window_seconds=accumulator.window_seconds,
        total_time=total,
        face_visible_ratio=_ratio(accumulator.face_visible_time, total),
        screen_facing_ratio=_ratio(accumulator.screen_facing_time, total),
        looking_away_ratio=_ratio(accumulator.looking_away_time, total),
        long_lookaway_count=accumulator.long_lookaway.count,
        ready=accumulator.is_full,
    )


def summarize_sleepiness(accumulator: TemporalAccumulator) -> SleepinessSummary:
    """Summarize the current sleepiness accumulator."""
    accumulator.close_open_events()
    total = accumulator.total_time
    eye_closed_ratio = _ratio(accumulator.eye_closed_time, total)
    return SleepinessSummary(
        start_timestamp=accumulator.start_timestamp,
        end_timestamp=accumulator.last_timestamp,
        block_start_time=None,
        block_end_time=None,
        window_seconds=accumulator.window_seconds,
        total_time=total,
        face_visible_ratio=_ratio(accumulator.face_visible_time, total),
        perclos=eye_closed_ratio,
        eye_closed_ratio=eye_closed_ratio,
        head_down_ratio=_ratio(accumulator.head_down_time, total),
        possible_yawn_ratio=_ratio(accumulator.possible_yawn_time, total),
        long_eye_closure_count=accumulator.long_eye_closure.count,
        yawn_count=accumulator.yawn.count,
        ready=accumulator.is_full,
    )


def aggregate_history(history: SignalHistory) -> TemporalSummary:
    """Convert running accumulators into temporal summaries."""
    return TemporalSummary(
        engagement=summarize_engagement(history.engagement),
        sleepiness=summarize_sleepiness(history.sleepiness),
    )


def _ratio(value: float, total: float) -> float:
    if total <= 0.0:
        return 0.0
    return value / total
