"""Emotion branch data types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EmotionClass(str, Enum):
    """Internal CNN emotion classes."""

    HAPPY = "Happy"
    NEUTRAL = "Neutral"
    CONFUSION = "Confusion"


class EmotionState(str, Enum):
    """App-facing emotion state used before final work-state fusion."""

    HAPPY = "happy"
    NEUTRAL = "neutral"
    CONFUSION = "confusion"
    UNCERTAIN = "uncertain"


class DifficultySublabel(str, Enum):
    """Optional detail for emotion states that need extra explanation."""

    NONE = "none"
    CONFUSION = "confusion"


@dataclass(frozen=True)
class EmotionRuleConfig:
    """Thresholds for converting raw emotion probabilities to app state."""

    happy_threshold: float = 0.80
    confusion_threshold: float = 0.80
    neutral_threshold: float = 0.50


@dataclass(frozen=True)
class EmotionPrediction:
    """CNN output plus calibrated app-facing interpretation."""

    probabilities: dict[EmotionClass, float]
    top_class: EmotionClass
    top_probability: float
    difficulty_score: float
    state: EmotionState
    sublabel: DifficultySublabel
    thresholds: EmotionRuleConfig

    def probability(self, label: EmotionClass) -> float:
        """Return the probability for one internal emotion class."""
        return self.probabilities[label]
