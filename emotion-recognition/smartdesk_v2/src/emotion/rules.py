"""Rules that convert CNN probabilities into practical app states."""

from __future__ import annotations

from src.emotion.types import DifficultySublabel, EmotionClass, EmotionPrediction, EmotionRuleConfig, EmotionState


DEFAULT_RULE_CONFIG = EmotionRuleConfig()


def interpret_emotion_probabilities(
    probabilities: dict[EmotionClass, float],
    config: EmotionRuleConfig = DEFAULT_RULE_CONFIG,
) -> EmotionPrediction:
    """Convert three CNN probabilities into an app-facing emotion state."""
    _validate_probabilities(probabilities)
    top_class = max(probabilities, key=probabilities.get)
    top_probability = float(probabilities[top_class])
    confusion = float(probabilities[EmotionClass.CONFUSION])
    difficulty_score = confusion

    if difficulty_score >= config.difficulty_threshold:
        return EmotionPrediction(
            probabilities=probabilities,
            top_class=top_class,
            top_probability=top_probability,
            difficulty_score=difficulty_score,
            state=EmotionState.NEEDS_HELP,
            sublabel=DifficultySublabel.CONFUSION,
            thresholds=config,
        )

    if top_class == EmotionClass.HAPPY and top_probability >= config.min_direct_confidence:
        state = EmotionState.HAPPY
    elif top_class == EmotionClass.NEUTRAL and top_probability >= config.min_direct_confidence:
        state = EmotionState.NEUTRAL
    else:
        state = EmotionState.UNCERTAIN

    return EmotionPrediction(
        probabilities=probabilities,
        top_class=top_class,
        top_probability=top_probability,
        difficulty_score=difficulty_score,
        state=state,
        sublabel=DifficultySublabel.NONE,
        thresholds=config,
    )


def _validate_probabilities(probabilities: dict[EmotionClass, float]) -> None:
    missing = [label for label in EmotionClass if label not in probabilities]
    if missing:
        raise ValueError(f"Missing emotion probabilities for: {missing}")
