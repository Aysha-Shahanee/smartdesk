"""Developer Work State fusion entry point."""

from __future__ import annotations

from src.state_fusion.rules import DEFAULT_FUSION_RULE_CONFIG, FusionRuleConfig, evaluate_state_rules
from src.state_fusion.state_types import DeveloperWorkState, FusionCounts, FusionDecision, FusionRatios


def fuse_developer_state(
    signal_trends: FusionRatios | FusionCounts | dict[str, float],
    *,
    current_state: DeveloperWorkState | str | None = None,
    config: FusionRuleConfig = DEFAULT_FUSION_RULE_CONFIG,
) -> FusionDecision:
    """Fuse five-minute signal ratios into one Developer Work State.

    The decision layer uses proportions only. Dominant labels and counts are
    retained for explanation but do not replace the ratio rules.
    """
    return evaluate_state_rules(
        signal_trends,
        current_state=current_state,
        config=config,
    )
