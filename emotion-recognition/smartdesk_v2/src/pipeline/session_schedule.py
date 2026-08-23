"""Session-level schedule for SmartDesk timing rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.temporal.schedule import (
    BlockSchedule,
    build_full_system_schedule,
    build_landmark_state_schedule,
    build_minute_alignment_schedule,
    floor_to_block,
)


@dataclass(frozen=True)
class SmartDeskSessionSchedule:
    """Official wall-clock starts for one SmartDesk recording session."""

    requested_start: datetime
    full_system: BlockSchedule
    landmark_state: BlockSchedule
    signal_alignment: BlockSchedule
    real_start: datetime

    @property
    def signal_alignment_offset_seconds(self) -> float:
        """Seconds from requested start to official signal alignment start."""
        return max(0.0, (self.signal_alignment.official_start - self.requested_start).total_seconds())

    @property
    def full_system_offset_seconds(self) -> float:
        """Seconds from requested start to official 15-minute block start."""
        return max(0.0, (self.full_system.official_start - self.requested_start).total_seconds())

    @property
    def landmark_state_offset_seconds(self) -> float:
        """Seconds from requested start to official 5-minute landmark-state start."""
        return max(0.0, (self.landmark_state.official_start - self.requested_start).total_seconds())

    @property
    def real_start_offset_seconds(self) -> float:
        """Seconds from requested start to the single real system start."""
        return max(0.0, (self.real_start - self.requested_start).total_seconds())


def first_block_end_offset_seconds(
    requested_start: datetime,
    schedule: BlockSchedule,
    block_seconds: float,
) -> float:
    """Seconds from requested start to the first scheduled block end.

    If the current wall-clock block is usable, the first output ends at that
    block's fixed boundary. If the current block is skipped, the first output
    is a full block after the official start.
    """
    if schedule.uses_current_block:
        return max(0.0, (schedule.current_block_end - requested_start).total_seconds())
    return max(0.0, (schedule.official_start - requested_start).total_seconds()) + block_seconds


def build_smartdesk_session_schedule(start_time: datetime) -> SmartDeskSessionSchedule:
    """Build all official schedules from one timezone-aware wall-clock start."""
    if start_time.tzinfo is None:
        raise ValueError("start_time must be timezone-aware")

    full_system = build_full_system_schedule(start_time)
    landmark_state = build_landmark_state_schedule(start_time)
    signal_alignment = build_minute_alignment_schedule(start_time)

    return SmartDeskSessionSchedule(
        requested_start=start_time,
        full_system=full_system,
        landmark_state=landmark_state,
        signal_alignment=signal_alignment,
        real_start=choose_real_start_time(
            full_system=full_system,
            landmark_state=landmark_state,
            signal_alignment=signal_alignment,
        ),
    )


def choose_real_start_time(
    *,
    full_system: BlockSchedule,
    landmark_state: BlockSchedule,
    signal_alignment: BlockSchedule,
) -> datetime:
    """Choose the official 5-minute boundary-aligned real start time."""
    return landmark_state.official_start


def choose_real_end_time(end_time: datetime) -> datetime:
    """Choose the usable end by flooring to the previous 5-minute boundary."""
    if end_time.tzinfo is None:
        raise ValueError("end_time must be timezone-aware")
    return floor_to_block(end_time, 5 * 60)

