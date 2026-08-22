"""Temporal engagement classifier.

The numeric thresholds are provisional starting values and should be calibrated
after webcam testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.temporal.aggregator import EngagementSummary


HIGH_SCREEN_FACING_RATIO = 0.80
HIGH_LOOKING_AWAY_RATIO = 0.20
MEDIUM_SCREEN_FACING_RATIO = 0.50
MEDIUM_LOOKING_AWAY_RATIO = 0.50
LOW_LOOKING_AWAY_RATIO = 0.50
MAX_HIGH_LONG_LOOKAWAYS = 1
REPEATED_LONG_LOOKAWAYS = 2
MIN_FACE_VISIBLE_RATIO = 0.50


class EngagementLabel(str, Enum):
    """Engagement classifier outputs."""

    PENDING = "pending"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class EngagementClassification:
    """Engagement label with explanation for calibration/debugging."""

    label: EngagementLabel
    confidence: float
    reason: str
    thresholds: dict[str, float | int]


def classify_engagement(summary: EngagementSummary) -> EngagementClassification:
    """Classify engagement from a completed temporal summary."""
    thresholds = _thresholds()
    if not summary.ready:
        return EngagementClassification(
            label=EngagementLabel.PENDING,
            confidence=0.0,
            reason="engagement window is not complete",
            thresholds=thresholds,
        )

    if summary.face_visible_ratio < MIN_FACE_VISIBLE_RATIO:
        return EngagementClassification(
            label=EngagementLabel.PENDING,
            confidence=0.0,
            reason="face visibility is too low for reliable engagement classification",
            thresholds=thresholds,
        )

    if (
        summary.screen_facing_ratio >= HIGH_SCREEN_FACING_RATIO
        and summary.looking_away_ratio <= HIGH_LOOKING_AWAY_RATIO
        and summary.long_lookaway_count <= MAX_HIGH_LONG_LOOKAWAYS
    ):
        return EngagementClassification(
            label=EngagementLabel.HIGH,
            confidence=_clamp(summary.screen_facing_ratio),
            reason="mostly screen-facing with low looking-away evidence",
            thresholds=thresholds,
        )

    if (
        summary.screen_facing_ratio < MEDIUM_SCREEN_FACING_RATIO
        or summary.looking_away_ratio > LOW_LOOKING_AWAY_RATIO
        or summary.long_lookaway_count >= REPEATED_LONG_LOOKAWAYS
    ):
        return EngagementClassification(
            label=EngagementLabel.LOW,
            confidence=_clamp(max(summary.looking_away_ratio, 1.0 - summary.screen_facing_ratio)),
            reason="low screen-facing evidence or repeated long look-away events",
            thresholds=thresholds,
        )

    if (
        summary.screen_facing_ratio >= MEDIUM_SCREEN_FACING_RATIO
        and summary.looking_away_ratio <= MEDIUM_LOOKING_AWAY_RATIO
    ):
        return EngagementClassification(
            label=EngagementLabel.MEDIUM,
            confidence=_clamp(summary.screen_facing_ratio),
            reason="mixed screen-facing and looking-away behavior",
            thresholds=thresholds,
        )

    return EngagementClassification(
        label=EngagementLabel.LOW,
        confidence=0.5,
        reason="engagement evidence did not satisfy medium or high rules",
        thresholds=thresholds,
    )


def _thresholds() -> dict[str, float | int]:
    return {
        "high_screen_facing_ratio": HIGH_SCREEN_FACING_RATIO,
        "high_looking_away_ratio": HIGH_LOOKING_AWAY_RATIO,
        "medium_screen_facing_ratio": MEDIUM_SCREEN_FACING_RATIO,
        "medium_looking_away_ratio": MEDIUM_LOOKING_AWAY_RATIO,
        "low_looking_away_ratio": LOW_LOOKING_AWAY_RATIO,
        "max_high_long_lookaways": MAX_HIGH_LONG_LOOKAWAYS,
        "repeated_long_lookaways": REPEATED_LONG_LOOKAWAYS,
        "min_face_visible_ratio": MIN_FACE_VISIBLE_RATIO,
    }


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))
