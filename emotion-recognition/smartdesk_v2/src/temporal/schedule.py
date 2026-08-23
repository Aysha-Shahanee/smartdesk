"""Shared wall-clock block scheduling rules.

The system uses fixed wall-clock blocks rather than windows that start whenever
the process starts. If too little time remains in the current block, official
recording starts at the next block boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


SECONDS_PER_MINUTE = 60

FULL_SYSTEM_BLOCK_SECONDS = 15 * SECONDS_PER_MINUTE
LANDMARK_STATE_BLOCK_SECONDS = 5 * SECONDS_PER_MINUTE
MINUTE_ALIGNMENT_BLOCK_SECONDS = SECONDS_PER_MINUTE

FULL_SYSTEM_MIN_REMAINING_SECONDS = 2 * SECONDS_PER_MINUTE
LANDMARK_STATE_MIN_REMAINING_SECONDS = 2 * SECONDS_PER_MINUTE
MINUTE_ALIGNMENT_MIN_REMAINING_SECONDS = SECONDS_PER_MINUTE


@dataclass(frozen=True)
class BlockSchedule:
    """Official start information for one fixed wall-clock block type."""

    requested_start: datetime
    current_block_start: datetime
    current_block_end: datetime
    official_start: datetime
    warmup_seconds: float
    uses_current_block: bool
    skipped_current_block: bool
    block_seconds: int
    min_usable_remaining_seconds: int


def build_block_schedule(
    start_time: datetime,
    block_seconds: int,
    min_usable_remaining_seconds: int,
) -> BlockSchedule:
    """Build a schedule for any fixed-size wall-clock block.

    If the remaining time in the current block is less than the configured
    minimum, the official start moves to the next block boundary. Otherwise, the
    official start is the current time rounded up to the next whole second.
    """
    if start_time.tzinfo is None:
        raise ValueError("start_time must be timezone-aware")
    if block_seconds <= 0:
        raise ValueError("block_seconds must be positive")
    if min_usable_remaining_seconds <= 0:
        raise ValueError("min_usable_remaining_seconds must be positive")

    block_start = floor_to_block(start_time, block_seconds)
    block_end = block_start + timedelta(seconds=block_seconds)
    remaining_seconds = (block_end - start_time).total_seconds()

    if remaining_seconds < min_usable_remaining_seconds:
        official_start = block_end
        uses_current_block = False
    else:
        official_start = ceil_to_next_second(start_time)
        uses_current_block = True

    return BlockSchedule(
        requested_start=start_time,
        current_block_start=block_start,
        current_block_end=block_end,
        official_start=official_start,
        warmup_seconds=max(0.0, (official_start - start_time).total_seconds()),
        uses_current_block=uses_current_block,
        skipped_current_block=not uses_current_block,
        block_seconds=block_seconds,
        min_usable_remaining_seconds=min_usable_remaining_seconds,
    )


def build_full_system_schedule(start_time: datetime) -> BlockSchedule:
    """Build the 15-minute full-system schedule."""
    return build_block_schedule(
        start_time=start_time,
        block_seconds=FULL_SYSTEM_BLOCK_SECONDS,
        min_usable_remaining_seconds=FULL_SYSTEM_MIN_REMAINING_SECONDS,
    )


def build_landmark_state_schedule(start_time: datetime) -> BlockSchedule:
    """Build the 5-minute landmark-side final-state schedule."""
    if start_time.tzinfo is None:
        raise ValueError("start_time must be timezone-aware")

    block_start = floor_to_block(start_time, LANDMARK_STATE_BLOCK_SECONDS)
    block_end = block_start + timedelta(seconds=LANDMARK_STATE_BLOCK_SECONDS)
    official_start = ceil_to_block(start_time, LANDMARK_STATE_BLOCK_SECONDS)
    uses_current_block = official_start == start_time

    return BlockSchedule(
        requested_start=start_time,
        current_block_start=block_start,
        current_block_end=block_end,
        official_start=official_start,
        warmup_seconds=max(0.0, (official_start - start_time).total_seconds()),
        uses_current_block=uses_current_block,
        skipped_current_block=not uses_current_block,
        block_seconds=LANDMARK_STATE_BLOCK_SECONDS,
        min_usable_remaining_seconds=LANDMARK_STATE_BLOCK_SECONDS,
    )


def build_minute_alignment_schedule(start_time: datetime) -> BlockSchedule:
    """Build the 1-minute alignment schedule used before 10-second blocks."""
    return build_block_schedule(
        start_time=start_time,
        block_seconds=MINUTE_ALIGNMENT_BLOCK_SECONDS,
        min_usable_remaining_seconds=MINUTE_ALIGNMENT_MIN_REMAINING_SECONDS,
    )


def ceil_to_block(value: datetime, block_seconds: int) -> datetime:
    """Return the current block start when exact, otherwise the next block start."""
    block_start = floor_to_block(value, block_seconds)
    if value == block_start:
        return value
    return block_start + timedelta(seconds=block_seconds)


def floor_to_block(value: datetime, block_seconds: int) -> datetime:
    """Return the fixed block start for ``value``.

    Blocks are anchored to midnight in the timestamp's local timezone.
    """
    if value.tzinfo is None:
        raise ValueError("value must be timezone-aware")
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = int((value - midnight).total_seconds())
    block_start_seconds = elapsed_seconds - (elapsed_seconds % block_seconds)
    return midnight + timedelta(seconds=block_start_seconds)


def ceil_to_next_second(value: datetime) -> datetime:
    """Return ``value`` if exact, otherwise the next full second."""
    if value.microsecond == 0:
        return value
    return (value + timedelta(seconds=1)).replace(microsecond=0)


def should_record(now: datetime, schedule: BlockSchedule) -> bool:
    """Whether official recording should be active for this schedule."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now >= schedule.official_start

