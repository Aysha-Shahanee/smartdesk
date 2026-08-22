"""Frame-level emotion prediction with practical Needs Help interpretation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

from src.emotion.model import EMOTION_CLASSES, DEFAULT_CHECKPOINT_PATH, load_emotion_model
from src.emotion.preprocess import ColorOrder, preprocess_frame, preprocess_image
from src.emotion.rules import DEFAULT_RULE_CONFIG, interpret_emotion_probabilities
from src.emotion.types import EmotionClass, EmotionPrediction, EmotionRuleConfig


class EmotionPredictor:
    """Run the fine-tuned CNN branch on frames or images."""

    def __init__(
        self,
        checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
        device: str | torch.device | None = None,
        rule_config: EmotionRuleConfig = DEFAULT_RULE_CONFIG,
        model: nn.Module | None = None,
    ) -> None:
        self.device = torch.device(device) if device is not None else _default_device()
        self.model = model or load_emotion_model(checkpoint_path, device=self.device)
        self.model.eval()
        self.rule_config = rule_config

    @torch.no_grad()
    def predict_frame(
        self,
        frame: np.ndarray,
        color_order: ColorOrder = "bgr",
    ) -> EmotionPrediction:
        """Predict emotion from one frame array."""
        tensor = preprocess_frame(frame, color_order=color_order).to(self.device)
        return self._predict_tensor(tensor)

    @torch.no_grad()
    def predict_image(self, image: Image.Image) -> EmotionPrediction:
        """Predict emotion from one PIL image."""
        tensor = preprocess_image(image).to(self.device)
        return self._predict_tensor(tensor)

    def _predict_tensor(self, tensor: torch.Tensor) -> EmotionPrediction:
        logits = self.model(tensor)
        probabilities_tensor = torch.softmax(logits, dim=1)[0].detach().cpu()
        probabilities = {
            label: float(probabilities_tensor[index].item())
            for index, label in enumerate(EMOTION_CLASSES)
        }
        return interpret_emotion_probabilities(probabilities, config=self.rule_config)


def prediction_to_plain_dict(prediction: EmotionPrediction) -> dict[str, object]:
    """Convert prediction dataclass to JSON/UI-friendly primitives."""
    return {
        "state": prediction.state.value,
        "sublabel": prediction.sublabel.value,
        "top_class": prediction.top_class.value,
        "top_probability": prediction.top_probability,
        "difficulty_score": prediction.difficulty_score,
        "probabilities": {
            EmotionClass.HAPPY.value: prediction.probability(EmotionClass.HAPPY),
            EmotionClass.NEUTRAL.value: prediction.probability(EmotionClass.NEUTRAL),
            EmotionClass.CONFUSION.value: prediction.probability(EmotionClass.CONFUSION),
        },
        "thresholds": {
            "difficulty_threshold": prediction.thresholds.difficulty_threshold,
            "min_direct_confidence": prediction.thresholds.min_direct_confidence,
        },
    }


def _default_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
