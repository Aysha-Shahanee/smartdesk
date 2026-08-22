"""Geometry helpers for facial-landmark measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
LEFT_IRIS = (468, 469, 470, 471, 472)
RIGHT_IRIS = (473, 474, 475, 476, 477)
MOUTH = (61, 81, 13, 311, 291, 402, 14, 178)


@dataclass(frozen=True)
class HeadPose:
    """Approximate head orientation in degrees."""

    yaw: float
    pitch: float
    roll: float
    direction: str


@dataclass(frozen=True)
class GazeEstimate:
    """Rough iris-position estimate inside the eye region."""

    horizontal_ratio: float
    vertical_ratio: float
    direction: str


@dataclass(frozen=True)
class LandmarkMeasurements:
    """Frame-level raw measurements from face landmarks."""

    ear: float | None
    left_ear: float | None
    right_ear: float | None
    mar: float | None
    head_pose: HeadPose | None
    gaze: GazeEstimate | None


def compute_ear(landmarks: Sequence[object]) -> tuple[float | None, float | None, float | None]:
    """Compute average, left, and right Eye Aspect Ratio."""
    left = _eye_aspect_ratio(landmarks, LEFT_EYE)
    right = _eye_aspect_ratio(landmarks, RIGHT_EYE)
    values = [value for value in (left, right) if value is not None]
    average = float(sum(values) / len(values)) if values else None
    return average, left, right


def compute_mar(landmarks: Sequence[object]) -> float | None:
    """Compute Mouth Aspect Ratio from selected mouth landmarks."""
    if not _has_indices(landmarks, MOUTH):
        return None

    left_corner, upper_left, upper_mid, upper_right, right_corner, lower_right, lower_mid, lower_left = [
        _point_2d(landmarks, index) for index in MOUTH
    ]
    horizontal = _distance(left_corner, right_corner)
    if horizontal == 0:
        return None

    vertical = (
        _distance(upper_left, lower_left)
        + _distance(upper_mid, lower_mid)
        + _distance(upper_right, lower_right)
    ) / 3.0
    return float(vertical / horizontal)


def compute_head_pose(
    landmarks: Sequence[object],
    image_width: int,
    image_height: int,
) -> HeadPose | None:
    """Estimate approximate head pose from six stable face landmarks."""
    import cv2

    required_indices = (1, 152, 33, 263, 61, 291)
    if not _has_indices(landmarks, required_indices):
        return None

    image_points = np.array(
        [
            _point_pixel(landmarks, 1, image_width, image_height),
            _point_pixel(landmarks, 152, image_width, image_height),
            _point_pixel(landmarks, 33, image_width, image_height),
            _point_pixel(landmarks, 263, image_width, image_height),
            _point_pixel(landmarks, 61, image_width, image_height),
            _point_pixel(landmarks, 291, image_width, image_height),
        ],
        dtype=np.float64,
    )

    model_points = np.array(
        [
            (0.0, 0.0, 0.0),
            (0.0, -63.6, -12.5),
            (-43.3, 32.7, -26.0),
            (43.3, 32.7, -26.0),
            (-28.9, -28.9, -24.1),
            (28.9, -28.9, -24.1),
        ],
        dtype=np.float64,
    )

    focal_length = float(image_width)
    camera_matrix = np.array(
        [
            [focal_length, 0.0, image_width / 2.0],
            [0.0, focal_length, image_height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    distortion = np.zeros((4, 1), dtype=np.float64)

    success, rotation_vector, _translation_vector = cv2.solvePnP(
        model_points,
        image_points,
        camera_matrix,
        distortion,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return None

    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    angles, *_ = cv2.RQDecomp3x3(rotation_matrix)
    pitch, yaw, roll = (_normalize_pose_angle(float(angle)) for angle in angles)

    return HeadPose(
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        direction=_head_direction(yaw=yaw, pitch=pitch),
    )


def compute_gaze(landmarks: Sequence[object]) -> GazeEstimate | None:
    """Estimate rough gaze direction from iris position inside both eyes."""
    if not (_has_indices(landmarks, LEFT_EYE + RIGHT_EYE) and _has_indices(landmarks, LEFT_IRIS + RIGHT_IRIS)):
        return None

    left_ratio = _iris_ratio(landmarks, LEFT_EYE, LEFT_IRIS)
    right_ratio = _iris_ratio(landmarks, RIGHT_EYE, RIGHT_IRIS)
    if left_ratio is None or right_ratio is None:
        return None

    horizontal = float((left_ratio[0] + right_ratio[0]) / 2.0)
    vertical = float((left_ratio[1] + right_ratio[1]) / 2.0)
    return GazeEstimate(
        horizontal_ratio=horizontal,
        vertical_ratio=vertical,
        direction=_gaze_direction(horizontal, vertical),
    )


def compute_measurements(
    landmarks: Sequence[object],
    image_width: int,
    image_height: int,
) -> LandmarkMeasurements:
    """Compute the frame-level raw measurements used by later modules."""
    ear, left_ear, right_ear = compute_ear(landmarks)
    return LandmarkMeasurements(
        ear=ear,
        left_ear=left_ear,
        right_ear=right_ear,
        mar=compute_mar(landmarks),
        head_pose=compute_head_pose(landmarks, image_width, image_height),
        gaze=compute_gaze(landmarks),
    )


def _eye_aspect_ratio(landmarks: Sequence[object], indices: tuple[int, int, int, int, int, int]) -> float | None:
    if not _has_indices(landmarks, indices):
        return None

    p1, p2, p3, p4, p5, p6 = [_point_2d(landmarks, index) for index in indices]
    horizontal = _distance(p1, p4)
    if horizontal == 0:
        return None

    vertical = _distance(p2, p6) + _distance(p3, p5)
    return float(vertical / (2.0 * horizontal))


def _iris_ratio(
    landmarks: Sequence[object],
    eye_indices: tuple[int, int, int, int, int, int],
    iris_indices: tuple[int, int, int, int, int],
) -> tuple[float, float] | None:
    eye_points = np.array([_point_2d(landmarks, index) for index in eye_indices], dtype=np.float64)
    iris_points = np.array([_point_2d(landmarks, index) for index in iris_indices], dtype=np.float64)
    min_xy = eye_points.min(axis=0)
    max_xy = eye_points.max(axis=0)
    span = max_xy - min_xy
    if span[0] == 0 or span[1] == 0:
        return None

    center = iris_points.mean(axis=0)
    ratio = (center - min_xy) / span
    return float(ratio[0]), float(ratio[1])


def _head_direction(yaw: float, pitch: float) -> str:
    if yaw <= -25.0:
        return "left"
    if yaw >= 25.0:
        return "right"
    if pitch <= -20.0:
        return "up"
    if pitch >= 20.0:
        return "down"
    return "forward"


def _normalize_pose_angle(angle: float) -> float:
    """Normalize wrapped solvePnP angles into the nearest readable pose angle."""
    if angle < -90.0:
        return angle + 180.0
    if angle > 90.0:
        return angle - 180.0
    return angle


def _gaze_direction(horizontal: float, vertical: float) -> str:
    if horizontal <= 0.35:
        return "left"
    if horizontal >= 0.65:
        return "right"
    if vertical <= 0.35:
        return "up"
    if vertical >= 0.65:
        return "down"
    return "center"


def _has_indices(landmarks: Sequence[object], indices: Sequence[int]) -> bool:
    return bool(landmarks) and max(indices) < len(landmarks)


def _point_2d(landmarks: Sequence[object], index: int) -> np.ndarray:
    point = landmarks[index]
    return np.array([float(point.x), float(point.y)], dtype=np.float64)


def _point_pixel(landmarks: Sequence[object], index: int, image_width: int, image_height: int) -> tuple[float, float]:
    point = landmarks[index]
    return float(point.x) * image_width, float(point.y) * image_height


def _distance(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second))
