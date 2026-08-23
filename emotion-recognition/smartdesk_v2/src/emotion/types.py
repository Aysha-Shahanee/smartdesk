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
    NEEDS_HELP = "needs_help"
    UNCERTAIN = "uncertain"


class DifficultySublabel(str, Enum):
    """Optional detail when the app-facing state is Needs Help."""

    NONE = "none"
    CONFUSION = "confusion"


@dataclass(frozen=True)
class EmotionRuleConfig:
    """Thresholds for converting raw emotion probabilities to app state."""

    difficulty_threshold: float = 0.60
    min_direct_confidence: float = 0.40


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
