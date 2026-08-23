"""End-to-end landmark branch pipeline.

This pipeline connects local face landmarks, raw geometry, frame-level features,
temporal block accumulation, block storage, and signal classification. It does
not run the Emotion CNN or final Developer Work State fusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.drowsiness.classifier import SleepinessClassification, classify_drowsiness
from src.drowsiness.features import DrowsinessFeatures, extract_drowsiness_features
from src.engagement.classifier import EngagementClassification, classify_engagement
from src.engagement.features import EngagementFeatures, extract_engagement_features
from src.landmarks.baseline import HeadPoseBaseline
from src.landmarks.detector import LandmarkDetection, LandmarkDetector
from src.landmarks.geometry import LandmarkMeasurements, compute_measurements
from src.temporal.aggregator import (
    EngagementSummary,
    SleepinessSummary,
    summarize_engagement,
    summarize_sleepiness,
)
from src.temporal.block_store import JsonlBlockStore
from src.temporal.history import FrameSignals, SignalHistory


@dataclass(frozen=True)
class LandmarkFrameResult:
    """Per-frame landmark branch output."""

    timestamp: float
    detection: LandmarkDetection
    measurements: LandmarkMeasurements | None
    engagement_features: EngagementFeatures | None
    drowsiness_features: DrowsinessFeatures | None


@dataclass(frozen=True)
class CompletedEngagementBlock:
    """Completed engagement block summary and label."""

    summary: EngagementSummary
    classification: EngagementClassification


@dataclass(frozen=True)
class CompletedSleepinessBlock:
    """Completed sleepiness block summary and label."""

    summary: SleepinessSummary
    classification: SleepinessClassification


@dataclass(frozen=True)
class LandmarkPipelineUpdate:
    """Pipeline update after processing one frame."""

    frame_result: LandmarkFrameResult
    engagement_block: CompletedEngagementBlock | None = None
    sleepiness_block: CompletedSleepinessBlock | None = None


class LandmarkPipeline:
    """Run the full landmark-based engagement and sleepiness branch."""

    def __init__(
        self,
        detector: LandmarkDetector | None = None,
        history: SignalHistory | None = None,
        store: JsonlBlockStore | None = None,
        storage_dir: str | Path | None = None,
        baseline: HeadPoseBaseline | None = None,
    ) -> None:
        self.detector = detector or LandmarkDetector()
        self.history = history or SignalHistory()
        self.baseline = baseline
        if store is not None:
            self.store = store
        elif storage_dir is not None:
            self.store = JsonlBlockStore(storage_dir)
        else:
            self.store = JsonlBlockStore()

    def close(self) -> None:
        """Release pipeline resources."""
        self.detector.close()

    def __enter__(self) -> "LandmarkPipeline":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def process_frame(self, frame, timestamp: float) -> LandmarkPipelineUpdate:
        """Process one webcam/image frame through the landmark branch."""
        detection = self.detector.detect(frame)

        measurements: LandmarkMeasurements | None = None
        engagement_features: EngagementFeatures | None = None
        drowsiness_features: DrowsinessFeatures | None = None

        if detection.face_detected:
            measurements = compute_measurements(
                detection.landmarks,
                detection.image_width,
                detection.image_height,
            )
            drowsiness_features = extract_drowsiness_features(
                measurements,
                baseline=self.baseline,
            )
            engagement_features = extract_engagement_features(
                measurements,
                eye_closed=drowsiness_features.eye_closed,
                baseline=self.baseline,
            )

        signals = FrameSignals(
            timestamp=timestamp,
            face_detected=detection.face_detected,
            engagement=engagement_features,
            drowsiness=drowsiness_features,
        )
        status = self.history.add(signals)

        engagement_block = None
        if status["engagement"]:
            summary = summarize_engagement(self.history.engagement)
            classification = classify_engagement(summary)
            self.store.append_engagement(summary)
            self.history.engagement.reset(timestamp, signals)
            engagement_block = CompletedEngagementBlock(summary, classification)

        sleepiness_block = None
        if status["sleepiness"]:
            summary = summarize_sleepiness(self.history.sleepiness)
            classification = classify_drowsiness(summary)
            self.store.append_sleepiness(summary)
            self.history.sleepiness.reset(timestamp, signals)
            sleepiness_block = CompletedSleepinessBlock(summary, classification)

        return LandmarkPipelineUpdate(
            frame_result=LandmarkFrameResult(
                timestamp=timestamp,
                detection=detection,
                measurements=measurements,
                engagement_features=engagement_features,
                drowsiness_features=drowsiness_features,
            ),
            engagement_block=engagement_block,
            sleepiness_block=sleepiness_block,
        )
