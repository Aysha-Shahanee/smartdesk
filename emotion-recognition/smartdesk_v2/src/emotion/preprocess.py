"""Image preprocessing for the RGB emotion CNN."""

from __future__ import annotations

from typing import Literal

import numpy as np
import torch
from PIL import Image
from torchvision import transforms


IMAGE_SIZE = 224
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


ColorOrder = Literal["bgr", "rgb"]


def build_emotion_transform(image_size: int = IMAGE_SIZE) -> transforms.Compose:
    """Build the deterministic inference transform used by the CNN branch."""
    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )


def frame_to_pil(frame: np.ndarray, color_order: ColorOrder = "bgr") -> Image.Image:
    """Convert an OpenCV or RGB frame array to a PIL RGB image."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Emotion CNN expects a color frame with shape HxWx3.")

    if color_order == "bgr":
        rgb = frame[:, :, ::-1]
    elif color_order == "rgb":
        rgb = frame
    else:
        raise ValueError(f"Unsupported color order: {color_order}")

    return Image.fromarray(np.ascontiguousarray(rgb).astype("uint8"), mode="RGB")


def preprocess_frame(
    frame: np.ndarray,
    color_order: ColorOrder = "bgr",
    image_size: int = IMAGE_SIZE,
) -> torch.Tensor:
    """Preprocess one frame to a batched tensor with shape 1x3x224x224."""
    image = frame_to_pil(frame, color_order=color_order)
    tensor = build_emotion_transform(image_size)(image)
    return tensor.unsqueeze(0)


def preprocess_image(image: Image.Image, image_size: int = IMAGE_SIZE) -> torch.Tensor:
    """Preprocess a PIL image to a batched tensor with shape 1x3x224x224."""
    tensor = build_emotion_transform(image_size)(image.convert("RGB"))
    return tensor.unsqueeze(0)
