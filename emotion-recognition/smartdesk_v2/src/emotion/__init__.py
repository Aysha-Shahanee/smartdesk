"""Emotion model integration package."""

from src.emotion.temporal import EmotionBlockRecorder, EmotionBlockSummary, EmotionTemporalAccumulator
from src.emotion.types import DifficultySublabel, EmotionClass, EmotionPrediction, EmotionRuleConfig, EmotionState


def __getattr__(name: str):
    if name in {"EmotionPredictor", "prediction_to_plain_dict"}:
        from src.emotion.predictor import EmotionPredictor, prediction_to_plain_dict

        return {
            "EmotionPredictor": EmotionPredictor,
            "prediction_to_plain_dict": prediction_to_plain_dict,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DifficultySublabel",
    "EmotionBlockRecorder",
    "EmotionBlockSummary",
    "EmotionClass",
    "EmotionPrediction",
    "EmotionPredictor",
    "EmotionRuleConfig",
    "EmotionState",
    "EmotionTemporalAccumulator",
    "prediction_to_plain_dict",
]
