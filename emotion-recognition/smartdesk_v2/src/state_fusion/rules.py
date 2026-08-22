"""Rule definitions for three-emotion Developer Work State fusion.

The thresholds are v1 engineering starting points from the project fusion
report. They must be validated on Smart Desk sessions before being treated as
final empirical values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.state_fusion.state_types import (
    DeveloperWorkState,
    FusionCounts,
    FusionDecision,
    FusionRatios,
)


@dataclass(frozen=True)
class FusionRuleConfig:
    """Configurable v1 thresholds for the five-state rule layer."""

    focused_engaged_min: float = 0.70
    focused_drowsy_max: float = 0.30
    focused_confusion_max: float = 0.30
    struggling_confusion_min: float = 0.40
    struggling_engaged_min: float = 0.60
    struggling_drowsy_max: float = 0.50
    disengaged_low_engagement_min: float = 0.50
    disengaged_drowsy_max: float = 0.50
    fatigued_drowsy_min: float = 0.50
    overloaded_confusion_min: float = 0.50
    overloaded_low_engagement_min: float = 0.40
    overloaded_low_engagement_with_drowsy_min: float = 0.25
    overloaded_drowsy_min: float = 0.40


DEFAULT_FUSION_RULE_CONFIG = FusionRuleConfig()


def evaluate_state_rules(
    signal_trends: FusionRatios | FusionCounts | Mapping[str, float],
    *,
    current_state: DeveloperWorkState | str | None = None,
    config: FusionRuleConfig = DEFAULT_FUSION_RULE_CONFIG,
) -> FusionDecision:
    """Evaluate the documented rule priority from five-minute ratios.

    Uses ratios/proportions for all decisions. Counts and dominant labels are
    only explanatory data and are not used to select the state.
    """
    counts = signal_trends if isinstance(signal_trends, FusionCounts) else None
    ratios = _to_ratios(signal_trends)
    held_state = _to_state(current_state)

    if _is_overloaded(ratios, config):
        state = DeveloperWorkState.OVERLOADED
        matched_rule = "overloaded"
    elif ratios.drowsy_ratio >= config.fatigued_drowsy_min:
        state = DeveloperWorkState.FATIGUED
        matched_rule = "fatigued"
    elif (
        ratios.low_engagement_ratio >= config.disengaged_low_engagement_min
        and ratios.drowsy_ratio < config.disengaged_drowsy_max
    ):
        state = DeveloperWorkState.DISENGAGED
        matched_rule = "disengaged"
    elif (
        ratios.confusion_ratio >= config.struggling_confusion_min
        and ratios.engaged_ratio >= config.struggling_engaged_min
        and ratios.drowsy_ratio < config.struggling_drowsy_max
    ):
        state = DeveloperWorkState.STRUGGLING
        matched_rule = "struggling"
    elif (
        ratios.engaged_ratio >= config.focused_engaged_min
        and ratios.drowsy_ratio < config.focused_drowsy_max
        and ratios.confusion_ratio < config.focused_confusion_max
    ):
        state = DeveloperWorkState.FOCUSED
        matched_rule = "focused"
    else:
        state = held_state
        matched_rule = "hold_current" if held_state is not None else "no_match"

    return FusionDecision(
        state=state,
        matched_rule=matched_rule,
        ratios=ratios,
        counts=counts,
    )


def _is_overloaded(ratios: FusionRatios, config: FusionRuleConfig) -> bool:
    return (
        ratios.confusion_ratio >= config.overloaded_confusion_min
        and (
            ratios.low_engagement_ratio >= config.overloaded_low_engagement_min
            or (
                ratios.low_engagement_ratio
                >= config.overloaded_low_engagement_with_drowsy_min
                and ratios.drowsy_ratio >= config.overloaded_drowsy_min
            )
        )
    )


def _to_ratios(value: FusionRatios | FusionCounts | Mapping[str, float]) -> FusionRatios:
    if isinstance(value, FusionRatios):
        return value
    if isinstance(value, FusionCounts):
        return value.to_ratios()
    return FusionRatios(
        confusion_ratio=float(value["confusion_ratio"]),
        stable_emotion_ratio=float(value.get("stable_emotion_ratio", 0.0)),
        engaged_ratio=float(value["engaged_ratio"]),
        low_engagement_ratio=float(value["low_engagement_ratio"]),
        drowsy_ratio=float(value["drowsy_ratio"]),
    )


def _to_state(value: DeveloperWorkState | str | None) -> DeveloperWorkState | None:
    if value is None or isinstance(value, DeveloperWorkState):
        return value
    return DeveloperWorkState(value)
