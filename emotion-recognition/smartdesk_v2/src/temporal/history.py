"""Temporal accumulators for frame-level signal measurements.

This module does not store raw frames or all per-frame values. It keeps running
time totals and event counts for the current temporal window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.drowsiness.features import DrowsinessFeatures
from src.engagement.features import EngagementFeatures


ENGAGEMENT_WINDOW_SECONDS = 10.0
SLEEPINESS_WINDOW_SECONDS = 60.0
LONG_LOOKAWAY_SECONDS = 2.0
LONG_EYE_CLOSURE_SECONDS = 0.5
YAWN_SECONDS = 1.0
WINDOW_READY_TOLERANCE_SECONDS = 1e-6


@dataclass(frozen=True)
class FrameSignals:
    """Frame-level derived values used by the temporal accumulators."""

    timestamp: float
    face_detected: bool
    engagement: EngagementFeatures | None = None
    drowsiness: DrowsinessFeatures | None = None


@dataclass
class _EventTracker:
    """Track sustained boolean events without storing every frame."""

    min_duration_seconds: float
    active_since: float | None = None
    count: int = 0

    def update(self, is_active: bool, timestamp: float) -> None:
        if is_active and self.active_since is None:
            self.active_since = timestamp
            return

        if not is_active:
            self.close(timestamp)

    def close(self, timestamp: float) -> None:
        if self.active_since is None:
            return

        duration = timestamp - self.active_since
        if duration >= self.min_duration_seconds:
            self.count += 1
        self.active_since = None


@dataclass
class TemporalAccumulator:
    """Running accumulator for one fixed-length temporal window."""

    window_seconds: float
    start_timestamp: float | None = None
    last_timestamp: float | None = None
    total_time: float = 0.0
    face_visible_time: float = 0.0
    screen_facing_time: float = 0.0
    looking_away_time: float = 0.0
    eye_closed_time: float = 0.0
    head_down_time: float = 0.0
    possible_yawn_time: float = 0.0
    long_lookaway: _EventTracker = field(default_factory=lambda: _EventTracker(LONG_LOOKAWAY_SECONDS))
    long_eye_closure: _EventTracker = field(default_factory=lambda: _EventTracker(LONG_EYE_CLOSURE_SECONDS))
    yawn: _EventTracker = field(default_factory=lambda: _EventTracker(YAWN_SECONDS))

    def add(self, signals: FrameSignals) -> bool:
        """Add one frame's derived values and return True if the window is full."""
        timestamp = float(signals.timestamp)
        if self.start_timestamp is None or self.last_timestamp is None:
            self.start_timestamp = timestamp
            self.last_timestamp = timestamp
            self._update_event_states(signals, timestamp)
            return False

        delta = max(0.0, timestamp - self.last_timestamp)
        self.last_timestamp = timestamp
        self.total_time += delta

        if signals.face_detected:
            self.face_visible_time += delta

        engagement = signals.engagement
        if engagement is not None and engagement.signal_available:
            if engagement.screen_facing:
                self.screen_facing_time += delta
            if engagement.looking_away:
                self.looking_away_time += delta

        drowsiness = signals.drowsiness
        if drowsiness is not None and drowsiness.signal_available:
            if drowsiness.eye_closed:
                self.eye_closed_time += delta
            if drowsiness.head_down:
                self.head_down_time += delta
            if drowsiness.possible_yawn:
                self.possible_yawn_time += delta

        self._update_event_states(signals, timestamp)
        return self.is_full

    @property
    def is_full(self) -> bool:
        """Whether enough observed time has accumulated for this window."""
        return self.total_time + WINDOW_READY_TOLERANCE_SECONDS >= self.window_seconds

    def reset(self, start_timestamp: float | None = None, seed_signals: FrameSignals | None = None) -> None:
        """Clear this accumulator for the next window.

        Args:
            start_timestamp: Optional boundary timestamp for the next block.
            seed_signals: Optional current frame state to seed active event
                trackers at the block boundary.
        """
        window_seconds = self.window_seconds
        self.__dict__.update(TemporalAccumulator(window_seconds).__dict__)
        if start_timestamp is not None:
            self.start_timestamp = float(start_timestamp)
            self.last_timestamp = float(start_timestamp)
        if seed_signals is not None and start_timestamp is not None:
            self._update_event_states(seed_signals, float(start_timestamp))

    def close_open_events(self) -> None:
        """Close any active events at the last observed timestamp."""
        if self.last_timestamp is None:
            return
        self.long_lookaway.close(self.last_timestamp)
        self.long_eye_closure.close(self.last_timestamp)
        self.yawn.close(self.last_timestamp)

    def _update_event_states(self, signals: FrameSignals, timestamp: float) -> None:
        engagement = signals.engagement
        drowsiness = signals.drowsiness
        self.long_lookaway.update(
            bool(engagement and engagement.looking_away),
            timestamp,
        )
        self.long_eye_closure.update(
            bool(drowsiness and drowsiness.eye_closed),
            timestamp,
        )
        self.yawn.update(
            bool(drowsiness and drowsiness.possible_yawn),
            timestamp,
        )


@dataclass
class SignalHistory:
    """Named accumulators for engagement and sleepiness windows."""

    engagement: TemporalAccumulator = field(
        default_factory=lambda: TemporalAccumulator(ENGAGEMENT_WINDOW_SECONDS)
    )
    sleepiness: TemporalAccumulator = field(
        default_factory=lambda: TemporalAccumulator(SLEEPINESS_WINDOW_SECONDS)
    )

    def add(self, signals: FrameSignals) -> dict[str, bool]:
        """Add one frame signal to both windows.

        Returns:
            Dict telling which windows became full after this frame.
        """
        return {
            "engagement": self.engagement.add(signals),
            "sleepiness": self.sleepiness.add(signals),
        }
