"""Frame-level feature extraction for drowsiness / sleepiness.

This module produces observable evidence flags only. Final Alert/Drowsy
classification should use temporal aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.landmarks.baseline import HeadPoseBaseline
    from src.landmarks.geometry import LandmarkMeasurements


EAR_CLOSED_THRESHOLD = 0.30
MAR_POSSIBLE_YAWN_THRESHOLD = 0.50
MAR_STRONG_YAWN_THRESHOLD = 0.60
HEAD_DOWN_PITCH_THRESHOLD = 10.0
HEAD_DOWN_WITH_LOW_EAR_PITCH_THRESHOLD = 5.0


@dataclass(frozen=True)
class DrowsinessFeatures:
    """Frame-level drowsiness evidence from landmark measurements."""

    ear: float | None
    mar: float | None
    head_pitch: float | None
    eye_closed: bool
    possible_yawn: bool
    strong_yawn: bool
    head_down: bool
    signal_available: bool


def extract_drowsiness_features(
    measurements: LandmarkMeasurements,
    baseline: HeadPoseBaseline | None = None,
) -> DrowsinessFeatures:
    """Extract frame-level drowsiness evidence from raw measurements."""
    ear = measurements.ear
    mar = measurements.mar
    head_pose = measurements.head_pose
    head_pitch = None if head_pose is None else head_pose.pitch
    relative_pitch = None if head_pitch is None else head_pitch
    if baseline is not None and head_pitch is not None:
        relative_pitch = head_pitch - baseline.pitch

    low_ear_with_downward_pitch = (
        relative_pitch is not None
        and relative_pitch >= HEAD_DOWN_WITH_LOW_EAR_PITCH_THRESHOLD
        and ear is not None
        and ear < EAR_CLOSED_THRESHOLD
    )
    head_down = (
        relative_pitch is not None
        and (
            relative_pitch >= HEAD_DOWN_PITCH_THRESHOLD
            or low_ear_with_downward_pitch
        )
    )
    eye_closed = ear is not None and ear < EAR_CLOSED_THRESHOLD and not head_down
    possible_yawn = mar is not None and mar >= MAR_POSSIBLE_YAWN_THRESHOLD
    strong_yawn = mar is not None and mar >= MAR_STRONG_YAWN_THRESHOLD
    signal_available = ear is not None or mar is not None or head_pose is not None

    return DrowsinessFeatures(
        ear=ear,
        mar=mar,
        head_pitch=head_pitch,
        eye_closed=eye_closed,
        possible_yawn=possible_yawn,
        strong_yawn=strong_yawn,
        head_down=head_down,
        signal_available=signal_available,
    )
