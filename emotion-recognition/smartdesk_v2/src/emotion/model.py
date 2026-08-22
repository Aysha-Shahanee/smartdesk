"""MobileNetV3 emotion model loading."""

from __future__ import annotations

import os
from pathlib import Path
import pathlib

import torch
import torch.nn as nn
from torchvision import models

from src.emotion.types import EmotionClass


DEFAULT_CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "models" / "emotion" / "best_3class_model.pth"
EMOTION_CLASSES = [
    EmotionClass.HAPPY,
    EmotionClass.NEUTRAL,
    EmotionClass.CONFUSION,
]


def build_emotion_model(num_classes: int = len(EMOTION_CLASSES)) -> nn.Module:
    """Create MobileNetV3 Small with the project emotion classifier head."""
    model = models.mobilenet_v3_small(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def load_emotion_model(
    checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
    device: str | torch.device | None = None,
) -> nn.Module:
    """Load the fine-tuned RGB emotion model for inference."""
    resolved_device = torch.device(device) if device is not None else _default_device()
    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Emotion checkpoint not found: {checkpoint_path}")

    model = build_emotion_model()
    checkpoint = _load_checkpoint(checkpoint_path)
    state_dict = checkpoint.get("model_state_dict", checkpoint.get("state_dict", checkpoint))
    state_dict = {key.replace("module.", ""): value for key, value in state_dict.items()}
    model.load_state_dict(state_dict, strict=True)
    model.to(resolved_device)
    model.eval()
    return model


def _default_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _load_checkpoint(checkpoint_path: Path):
    """Load checkpoints saved on Colab/Linux from Windows too."""
    original_posix_path = pathlib.PosixPath
    try:
        if os.name == "nt":
            pathlib.PosixPath = pathlib.WindowsPath
        return torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    finally:
        pathlib.PosixPath = original_posix_path
