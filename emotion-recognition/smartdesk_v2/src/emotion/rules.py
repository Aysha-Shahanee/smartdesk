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
    happy = float(probabilities[EmotionClass.HAPPY])
    neutral = float(probabilities[EmotionClass.NEUTRAL])
    confusion = float(probabilities[EmotionClass.CONFUSION])
    difficulty_score = confusion

    if top_class == EmotionClass.HAPPY and happy > config.happy_threshold:
        state = EmotionState.HAPPY
        sublabel = DifficultySublabel.NONE
    elif top_class == EmotionClass.CONFUSION and confusion > config.confusion_threshold:
        state = EmotionState.CONFUSION
        sublabel = DifficultySublabel.CONFUSION
    elif top_class == EmotionClass.NEUTRAL and neutral > config.neutral_threshold:
        state = EmotionState.NEUTRAL
        sublabel = DifficultySublabel.NONE
    else:
        state = EmotionState.UNCERTAIN
        sublabel = DifficultySublabel.NONE

    return EmotionPrediction(
        probabilities=probabilities,
        top_class=top_class,
        top_probability=top_probability,
        difficulty_score=difficulty_score,
        state=state,
        sublabel=sublabel,
        thresholds=config,
    )


def _validate_probabilities(probabilities: dict[EmotionClass, float]) -> None:
    missing = [label for label in EmotionClass if label not in probabilities]
    if missing:
        raise ValueError(f"Missing emotion probabilities for: {missing}")
