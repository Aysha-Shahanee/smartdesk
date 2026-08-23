"""Frame-level feature extraction for engagement / visual attention.

This module produces observable evidence flags only. Final High/Medium/Low
classification should use temporal aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.landmarks.baseline import HeadPoseBaseline
    from src.landmarks.geometry import LandmarkMeasurements


SCREEN_FACING_YAW_LIMIT = 20.0
SCREEN_FACING_PITCH_LIMIT = 10.0
LOOKING_AWAY_YAW_LIMIT = 25.0
LOOKING_AWAY_PITCH_LIMIT = 10.0
DOWNWARD_OCCLUSION_PITCH_LIMIT = 5.0
DOWNWARD_OCCLUSION_EAR_LIMIT = 0.22


@dataclass(frozen=True)
class EngagementFeatures:
    """Frame-level visual engagement evidence from landmark measurements."""

    head_direction: str | None
    gaze_direction: str | None
    head_yaw: float | None
    head_pitch: float | None
    gaze_valid: bool
    screen_facing: bool
    looking_away: bool
    signal_available: bool


def extract_engagement_features(
    measurements: LandmarkMeasurements,
    eye_closed: bool = False,
    baseline: HeadPoseBaseline | None = None,
) -> EngagementFeatures:
    """Extract frame-level engagement evidence from raw measurements."""
    head_pose = measurements.head_pose
    gaze = measurements.gaze
    head_direction = None if head_pose is None else head_pose.direction
    gaze_direction = None if gaze is None else gaze.direction
    head_yaw = None if head_pose is None else head_pose.yaw
    head_pitch = None if head_pose is None else head_pose.pitch
    relative_yaw = None if head_yaw is None else head_yaw
    relative_pitch = None if head_pitch is None else head_pitch
    if baseline is not None:
        relative_yaw = None if head_yaw is None else head_yaw - baseline.yaw
        relative_pitch = None if head_pitch is None else head_pitch - baseline.pitch

    downward_occlusion = (
        relative_pitch is not None
        and relative_pitch >= DOWNWARD_OCCLUSION_PITCH_LIMIT
        and measurements.ear is not None
        and measurements.ear < DOWNWARD_OCCLUSION_EAR_LIMIT
    )
    head_screen_facing = (
        relative_yaw is not None
        and relative_pitch is not None
        and abs(relative_yaw) <= SCREEN_FACING_YAW_LIMIT
        and abs(relative_pitch) <= SCREEN_FACING_PITCH_LIMIT
        and not downward_occlusion
    )
    gaze_valid = gaze is not None and not eye_closed
    gaze_screen_facing = (not gaze_valid) or gaze_direction == "center"
    screen_facing = head_screen_facing and gaze_screen_facing

    head_looking_away = (
        relative_yaw is not None
        and relative_pitch is not None
        and (
            abs(relative_yaw) >= LOOKING_AWAY_YAW_LIMIT
            or abs(relative_pitch) >= LOOKING_AWAY_PITCH_LIMIT
            or downward_occlusion
        )
    )
    looking_away = head_looking_away
    signal_available = head_pose is not None or gaze is not None

    return EngagementFeatures(
        head_direction=head_direction,
        gaze_direction=gaze_direction,
        head_yaw=head_yaw,
        head_pitch=head_pitch,
        gaze_valid=gaze_valid,
        screen_facing=screen_facing,
        looking_away=looking_away,
        signal_available=signal_available,
    )
