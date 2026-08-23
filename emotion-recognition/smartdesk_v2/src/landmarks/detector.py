"""Shared face-landmark detector.

The detector only finds face landmarks and signal-quality information. Higher
level engagement and drowsiness decisions belong in their own modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LandmarkPoint:
    """One normalized face-landmark point."""

    x: float
    y: float
    z: float = 0.0
    visibility: float | None = None


@dataclass(frozen=True)
class LandmarkDetection:
    """Result from one frame-level landmark detection."""

    face_detected: bool
    landmarks: list[LandmarkPoint]
    image_width: int
    image_height: int
    face_count: int = 0
    backend: str = "mediapipe_face_mesh"


class LandmarkDetector:
    """MediaPipe Face Mesh wrapper for reusable facial landmarks."""

    def __init__(
        self,
        max_num_faces: int = 1,
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        model_path: str | Path | None = None,
    ) -> None:
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise ImportError(
                "MediaPipe is required for LandmarkDetector. Install it with "
                "`pip install mediapipe` in the Python environment used to run "
                "the project."
            ) from exc

        self._mp = mp
        self._backend = ""
        self._face_mesh = None
        self._face_landmarker = None

        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
            self._backend = "mediapipe_face_mesh"
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=max_num_faces,
                refine_landmarks=refine_landmarks,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
            return

        self._backend = "mediapipe_face_landmarker"
        model = Path(model_path) if model_path else Path(__file__).resolve().parents[2] / "models" / "face_landmarker.task"
        if not model.exists():
            raise FileNotFoundError(
                "MediaPipe Face Landmarker requires a model file. Expected: "
                f"{model}. Download `face_landmarker.task` into the models folder "
                "or pass model_path=..."
            )

        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        base_options = python.BaseOptions(model_asset_path=str(model))
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_faces=max_num_faces,
            min_face_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._face_landmarker = vision.FaceLandmarker.create_from_options(options)

    def close(self) -> None:
        """Release MediaPipe resources."""
        if self._face_mesh is not None:
            self._face_mesh.close()
        if self._face_landmarker is not None:
            self._face_landmarker.close()

    def __enter__(self) -> "LandmarkDetector":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def detect(self, frame) -> LandmarkDetection:
        """Detect the most prominent face landmarks from one BGR/RGB frame.

        Args:
            frame: Image array in OpenCV BGR format by default.

        Returns:
            LandmarkDetection with normalized landmark coordinates. If no face
            is detected, `face_detected` is false and `landmarks` is empty.
        """
        if frame is None:
            raise ValueError("frame cannot be None")

        height, width = frame.shape[:2]
        rgb_frame = self._to_rgb(frame)
        if self._face_mesh is not None:
            result = self._face_mesh.process(rgb_frame)
            faces = result.multi_face_landmarks or []
            first_face = faces[0].landmark if faces else []
        else:
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
            result = self._face_landmarker.detect(mp_image)
            faces = result.face_landmarks or []
            first_face = faces[0] if faces else []

        if not faces:
            return LandmarkDetection(
                face_detected=False,
                landmarks=[],
                image_width=width,
                image_height=height,
                face_count=0,
                backend=self._backend,
            )

        landmarks = [
            LandmarkPoint(
                x=float(point.x),
                y=float(point.y),
                z=float(point.z),
                visibility=getattr(point, "visibility", None),
            )
            for point in first_face
        ]
        return LandmarkDetection(
            face_detected=True,
            landmarks=landmarks,
            image_width=width,
            image_height=height,
            face_count=len(faces),
            backend=self._backend,
        )

    @staticmethod
    def _to_rgb(frame):
        """Convert an OpenCV BGR frame to RGB for MediaPipe."""
        import cv2

        if len(frame.shape) == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

