"""Face crop helpers based on existing landmark detections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from src.landmarks.detector import LandmarkDetection, LandmarkPoint


@dataclass(frozen=True)
class FaceCrop:
    """Face crop image and source-frame bounding box."""

    image: np.ndarray
    bbox_xyxy: tuple[int, int, int, int]
    margin_ratio: float


def crop_face_from_detection(
    frame: np.ndarray,
    detection: LandmarkDetection,
    margin_ratio: float = 0.25,
) -> FaceCrop | None:
    """Crop a face from a frame using a landmark detection result."""
    if not detection.face_detected or not detection.landmarks:
        return None

    bbox = landmarks_to_bbox(
        detection.landmarks,
        image_width=detection.image_width,
        image_height=detection.image_height,
        margin_ratio=margin_ratio,
    )
    if bbox is None:
        return None

    x1, y1, x2, y2 = bbox
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    return FaceCrop(image=crop.copy(), bbox_xyxy=bbox, margin_ratio=margin_ratio)


def landmarks_to_bbox(
    landmarks: Sequence[LandmarkPoint],
    image_width: int,
    image_height: int,
    margin_ratio: float = 0.25,
) -> tuple[int, int, int, int] | None:
    """Create a padded xyxy face box from normalized landmarks."""
    if not landmarks:
        return None

    xs = np.array([float(point.x) for point in landmarks], dtype=np.float64) * image_width
    ys = np.array([float(point.y) for point in landmarks], dtype=np.float64) * image_height
    x1 = float(xs.min())
    y1 = float(ys.min())
    x2 = float(xs.max())
    y2 = float(ys.max())

    width = x2 - x1
    height = y2 - y1
    if width <= 1.0 or height <= 1.0:
        return None

    margin = max(width, height) * margin_ratio
    x1 = max(0, int(round(x1 - margin)))
    y1 = max(0, int(round(y1 - margin)))
    x2 = min(image_width, int(round(x2 + margin)))
    y2 = min(image_height, int(round(y2 + margin)))
    if x2 <= x1 or y2 <= y1:
        return None

    return x1, y1, x2, y2
