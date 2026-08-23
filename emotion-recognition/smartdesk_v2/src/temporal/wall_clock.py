"""Backward-compatible wall-clock helpers for landmark block timing."""

from __future__ import annotations

from datetime import datetime

from src.temporal.schedule import (
    LANDMARK_STATE_BLOCK_SECONDS,
    LANDMARK_STATE_MIN_REMAINING_SECONDS,
    BlockSchedule,
    build_block_schedule,
    floor_to_block,
    should_record as _should_record,
)


FIVE_MINUTE_BLOCK_SECONDS = LANDMARK_STATE_BLOCK_SECONDS
MIN_USABLE_REMAINING_SECONDS = LANDMARK_STATE_MIN_REMAINING_SECONDS
WallClockSchedule = BlockSchedule


def build_wall_clock_schedule(start_time: datetime) -> WallClockSchedule:
    """Build the landmark branch schedule for a given wall-clock start time.

    Rules:
    - Fixed 5-minute blocks anchor the timing.
    - If less than 2 minutes remain in the current 5-minute block, skip it.
    - Otherwise, start official recording immediately, rounded to the next
      whole second when needed.
    """
    schedule = build_block_schedule(
        start_time=start_time,
        block_seconds=FIVE_MINUTE_BLOCK_SECONDS,
        min_usable_remaining_seconds=MIN_USABLE_REMAINING_SECONDS,
    )
    if not schedule.uses_current_block:
        return schedule

    official_start = ceil_to_next_minute(start_time)
    return BlockSchedule(
        requested_start=schedule.requested_start,
        current_block_start=schedule.current_block_start,
        current_block_end=schedule.current_block_end,
        official_start=official_start,
        warmup_seconds=max(0.0, (official_start - start_time).total_seconds()),
        uses_current_block=schedule.uses_current_block,
        skipped_current_block=schedule.skipped_current_block,
        block_seconds=schedule.block_seconds,
        min_usable_remaining_seconds=schedule.min_usable_remaining_seconds,
    )


def floor_to_five_minute_block(value: datetime) -> datetime:
    """Return the current fixed 5-minute block start."""
    return floor_to_block(value, FIVE_MINUTE_BLOCK_SECONDS)


def ceil_to_next_minute(value: datetime) -> datetime:
    """Return this minute if exact, otherwise the next full minute.

    Kept for scripts that imported it directly. The shared scheduler now uses
    second-level rounding for non-skipped starts.
    """
    from datetime import timedelta

    if value.second == 0 and value.microsecond == 0:
        return value
    return (value + timedelta(minutes=1)).replace(second=0, microsecond=0)


def should_record(now: datetime, schedule: WallClockSchedule) -> bool:
    """Whether official landmark block recording should be active."""
    return _should_record(now, schedule)
