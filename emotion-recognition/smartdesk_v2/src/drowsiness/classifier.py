"""Temporal sleepiness / drowsiness classifier.

The numeric thresholds are provisional starting values and should be calibrated
after webcam testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.temporal.aggregator import SleepinessSummary


PERCLOS_AWAKE_MAX = 0.075
PERCLOS_DROWSY_MIN = 0.15
REPEATED_LONG_EYE_CLOSURES = 2
REPEATED_YAWNS = 2
HEAD_DOWN_RATIO_DROWSY = 0.20
HEAD_DOWN_RATIO_SUPPORT = 0.10
MEDIUM_PERCLOS_SUPPORT_MIN = 0.075
MIN_FACE_VISIBLE_RATIO = 0.50


class SleepinessLabel(str, Enum):
    """Sleepiness classifier outputs."""

    PENDING = "pending"
    ALERT = "alert"
    DROWSY = "drowsy"


@dataclass(frozen=True)
class SleepinessClassification:
    """Sleepiness label with explanation for calibration/debugging."""

    label: SleepinessLabel
    confidence: float
    reason: str
    thresholds: dict[str, float | int]


def classify_drowsiness(summary: SleepinessSummary) -> SleepinessClassification:
    """Classify sleepiness from a completed temporal summary."""
    thresholds = _thresholds()
    if not summary.ready:
        return SleepinessClassification(
            label=SleepinessLabel.PENDING,
            confidence=0.0,
            reason="sleepiness window is not complete",
            thresholds=thresholds,
        )

    if summary.face_visible_ratio < MIN_FACE_VISIBLE_RATIO:
        return SleepinessClassification(
            label=SleepinessLabel.PENDING,
            confidence=0.0,
            reason="face visibility is too low for reliable sleepiness classification",
            thresholds=thresholds,
        )

    if summary.perclos > PERCLOS_DROWSY_MIN:
        return SleepinessClassification(
            label=SleepinessLabel.DROWSY,
            confidence=_clamp(summary.perclos / PERCLOS_DROWSY_MIN),
            reason="PERCLOS is above the drowsy evidence threshold",
            thresholds=thresholds,
        )

    if summary.long_eye_closure_count >= REPEATED_LONG_EYE_CLOSURES:
        return SleepinessClassification(
            label=SleepinessLabel.DROWSY,
            confidence=0.8,
            reason="repeated long eye closures detected",
            thresholds=thresholds,
        )

    if summary.yawn_count >= REPEATED_YAWNS:
        return SleepinessClassification(
            label=SleepinessLabel.DROWSY,
            confidence=0.7,
            reason="repeated yawn events detected",
            thresholds=thresholds,
        )

    if summary.head_down_ratio >= HEAD_DOWN_RATIO_DROWSY:
        return SleepinessClassification(
            label=SleepinessLabel.DROWSY,
            confidence=_clamp(summary.head_down_ratio / HEAD_DOWN_RATIO_DROWSY),
            reason="head-down evidence is high in the sleepiness window",
            thresholds=thresholds,
        )

    if (
        summary.perclos >= MEDIUM_PERCLOS_SUPPORT_MIN
        and (
            summary.long_eye_closure_count > 0
            or summary.yawn_count > 0
            or summary.head_down_ratio >= HEAD_DOWN_RATIO_SUPPORT
        )
    ):
        return SleepinessClassification(
            label=SleepinessLabel.DROWSY,
            confidence=0.65,
            reason="medium PERCLOS with supporting drowsiness evidence",
            thresholds=thresholds,
        )

    return SleepinessClassification(
        label=SleepinessLabel.ALERT,
        confidence=_clamp(1.0 - summary.perclos),
        reason="PERCLOS and supporting drowsiness evidence are low",
        thresholds=thresholds,
    )


def _thresholds() -> dict[str, float | int]:
    return {
        "perclos_awake_max": PERCLOS_AWAKE_MAX,
        "perclos_drowsy_min": PERCLOS_DROWSY_MIN,
        "repeated_long_eye_closures": REPEATED_LONG_EYE_CLOSURES,
        "repeated_yawns": REPEATED_YAWNS,
        "head_down_ratio_drowsy": HEAD_DOWN_RATIO_DROWSY,
        "head_down_ratio_support": HEAD_DOWN_RATIO_SUPPORT,
        "medium_perclos_support_min": MEDIUM_PERCLOS_SUPPORT_MIN,
        "min_face_visible_ratio": MIN_FACE_VISIBLE_RATIO,
    }


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))
