"""Same-frame SmartDesk pipeline for landmarks and CNN emotion."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.drowsiness.classifier import SleepinessClassification, classify_drowsiness
from src.drowsiness.features import DrowsinessFeatures, extract_drowsiness_features
from src.emotion import EmotionPrediction, EmotionPredictor
from src.emotion.temporal import EmotionBlockRecorder, EmotionBlockSummary
from src.engagement.classifier import EngagementClassification, classify_engagement
from src.engagement.features import EngagementFeatures, extract_engagement_features
from src.landmarks.baseline import HeadPoseBaseline
from src.landmarks.detector import LandmarkDetection, LandmarkDetector
from src.landmarks.face_crop import FaceCrop, crop_face_from_detection
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
class SmartDeskFrameResult:
    """Per-frame output from both frame branches."""

    timestamp: float
    detection: LandmarkDetection
    face_crop: FaceCrop | None
    emotion: EmotionPrediction | None
    measurements: LandmarkMeasurements | None
    engagement_features: EngagementFeatures | None
    drowsiness_features: DrowsinessFeatures | None


@dataclass(frozen=True)
class CompletedEngagementBlock:
    """Completed engagement block summary and label."""

    summary: EngagementSummary
    classification: EngagementClassification


@dataclass(frozen=True)
class CompletedEmotionBlock:
    """Completed emotion block summary."""

    summary: EmotionBlockSummary


@dataclass(frozen=True)
class CompletedSleepinessBlock:
    """Completed sleepiness block summary and label."""

    summary: SleepinessSummary
    classification: SleepinessClassification


@dataclass(frozen=True)
class SmartDeskPipelineUpdate:
    """Pipeline update after processing one frame."""

    frame_result: SmartDeskFrameResult
    emotion_block: CompletedEmotionBlock | None = None
    engagement_block: CompletedEngagementBlock | None = None
    sleepiness_block: CompletedSleepinessBlock | None = None


@dataclass(frozen=True)
class SmartDeskPipelineFlush:
    """Completed blocks produced when closing the pipeline to a time boundary."""

    emotion_blocks: list[CompletedEmotionBlock]
    engagement_blocks: list[CompletedEngagementBlock]
    sleepiness_blocks: list[CompletedSleepinessBlock]


class SmartDeskPipeline:
    """Run landmark and CNN emotion branches from the same webcam frame."""

    def __init__(
        self,
        detector: LandmarkDetector | None = None,
        emotion_predictor: EmotionPredictor | None = None,
        emotion_recorder: EmotionBlockRecorder | None = None,
        emotion_official_start_timestamp: float = 0.0,
        landmark_official_start_timestamp: float = 0.0,
        history: SignalHistory | None = None,
        store: JsonlBlockStore | None = None,
        storage_dir: str | Path | None = None,
        baseline: HeadPoseBaseline | None = None,
        face_crop_margin: float = 0.25,
        block_time_base: datetime | None = None,
    ) -> None:
        self.detector = detector or LandmarkDetector()
        self.emotion_predictor = emotion_predictor or EmotionPredictor()
        self.emotion_recorder = emotion_recorder or EmotionBlockRecorder(
            official_start_timestamp=emotion_official_start_timestamp,
        )
        self.history = history or SignalHistory()
        self.landmark_official_start_timestamp = float(landmark_official_start_timestamp)
        self.landmark_history_started = False
        self.next_engagement_end_timestamp = self.landmark_official_start_timestamp + 10.0
        self.next_sleepiness_end_timestamp = self.landmark_official_start_timestamp + 60.0
        self.baseline = baseline
        self.face_crop_margin = face_crop_margin
        self.block_time_base = block_time_base
        self.latest_signals: FrameSignals | None = None
        self.latest_emotion: EmotionPrediction | None = None
        if store is not None:
            self.store = store
        elif storage_dir is not None:
            self.store = JsonlBlockStore(storage_dir)
        else:
            self.store = JsonlBlockStore()

    def close(self) -> None:
        """Release pipeline resources."""
        self.detector.close()

    def __enter__(self) -> "SmartDeskPipeline":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def process_frame(self, frame, timestamp: float) -> SmartDeskPipelineUpdate:
        """Process one webcam/image frame through both branches."""
        detection = self.detector.detect(frame)

        measurements: LandmarkMeasurements | None = None
        engagement_features: EngagementFeatures | None = None
        drowsiness_features: DrowsinessFeatures | None = None
        face_crop: FaceCrop | None = None
        emotion: EmotionPrediction | None = None

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

            face_crop = crop_face_from_detection(
                frame,
                detection,
                margin_ratio=self.face_crop_margin,
            )
            if face_crop is not None:
                emotion = self.emotion_predictor.predict_frame(face_crop.image, color_order="bgr")

        signals = FrameSignals(
            timestamp=timestamp,
            face_detected=detection.face_detected,
            engagement=engagement_features,
            drowsiness=drowsiness_features,
        )
        self.latest_signals = signals
        self.latest_emotion = emotion
        completed_engagement_summaries: list[EngagementSummary] = []
        completed_sleepiness_summaries: list[SleepinessSummary] = []
        if timestamp >= self.landmark_official_start_timestamp:
            if not self.landmark_history_started:
                self.history.engagement.reset(self.landmark_official_start_timestamp, signals)
                self.history.sleepiness.reset(self.landmark_official_start_timestamp, signals)
                self.landmark_history_started = True

            while timestamp >= self.next_engagement_end_timestamp:
                boundary_signals = FrameSignals(
                    timestamp=self.next_engagement_end_timestamp,
                    face_detected=signals.face_detected,
                    engagement=signals.engagement,
                    drowsiness=signals.drowsiness,
                )
                self.history.engagement.add(boundary_signals)
                completed_engagement_summaries.append(
                    summarize_engagement(self.history.engagement)
                )
                self.history.engagement.reset(self.next_engagement_end_timestamp, signals)
                self.next_engagement_end_timestamp += 10.0

            while timestamp >= self.next_sleepiness_end_timestamp:
                boundary_signals = FrameSignals(
                    timestamp=self.next_sleepiness_end_timestamp,
                    face_detected=signals.face_detected,
                    engagement=signals.engagement,
                    drowsiness=signals.drowsiness,
                )
                self.history.sleepiness.add(boundary_signals)
                completed_sleepiness_summaries.append(
                    summarize_sleepiness(self.history.sleepiness)
                )
                self.history.sleepiness.reset(self.next_sleepiness_end_timestamp, signals)
                self.next_sleepiness_end_timestamp += 60.0

            self.history.add(signals)

        emotion_block = None
        summary = self.emotion_recorder.add(timestamp, emotion)
        if summary is not None:
            summary = self._with_block_times(summary)
            self.store.append_emotion(summary)
            emotion_block = CompletedEmotionBlock(summary)

        engagement_block = None
        for completed_summary in completed_engagement_summaries:
            summary = completed_summary
            summary = self._with_block_times(summary)
            classification = classify_engagement(summary)
            self.store.append_engagement(summary)
            engagement_block = CompletedEngagementBlock(summary, classification)

        sleepiness_block = None
        for completed_summary in completed_sleepiness_summaries:
            summary = completed_summary
            summary = self._with_block_times(summary)
            classification = classify_drowsiness(summary)
            self.store.append_sleepiness(summary)
            sleepiness_block = CompletedSleepinessBlock(summary, classification)

        return SmartDeskPipelineUpdate(
            frame_result=SmartDeskFrameResult(
                timestamp=timestamp,
                detection=detection,
                face_crop=face_crop,
                emotion=emotion,
                measurements=measurements,
                engagement_features=engagement_features,
                drowsiness_features=drowsiness_features,
            ),
            emotion_block=emotion_block,
            engagement_block=engagement_block,
            sleepiness_block=sleepiness_block,
        )

    def flush_until(self, timestamp: float) -> SmartDeskPipelineFlush:
        """Store any full blocks that end at or before ``timestamp``.

        Normal operation completes blocks when a new frame crosses a fixed
        boundary. At service stop, the camera may end exactly on a boundary with
        no following frame. This method closes only fully elapsed windows using
        the latest observed signal state at each boundary.
        """
        timestamp = float(timestamp)
        emotion_blocks: list[CompletedEmotionBlock] = []
        engagement_blocks: list[CompletedEngagementBlock] = []
        sleepiness_blocks: list[CompletedSleepinessBlock] = []

        while (
            self.emotion_recorder.next_block_end_timestamp is not None
            and timestamp >= self.emotion_recorder.next_block_end_timestamp
        ):
            boundary = self.emotion_recorder.next_block_end_timestamp
            summary = self.emotion_recorder.add(boundary, self.latest_emotion)
            if summary is None:
                break
            summary = self._with_block_times(summary)
            self.store.append_emotion(summary)
            emotion_blocks.append(CompletedEmotionBlock(summary))

        if self.latest_signals is not None and timestamp >= self.landmark_official_start_timestamp:
            if not self.landmark_history_started:
                self.history.engagement.reset(
                    self.landmark_official_start_timestamp,
                    self.latest_signals,
                )
                self.history.sleepiness.reset(
                    self.landmark_official_start_timestamp,
                    self.latest_signals,
                )
                self.landmark_history_started = True

            while timestamp >= self.next_engagement_end_timestamp:
                boundary_signals = FrameSignals(
                    timestamp=self.next_engagement_end_timestamp,
                    face_detected=self.latest_signals.face_detected,
                    engagement=self.latest_signals.engagement,
                    drowsiness=self.latest_signals.drowsiness,
                )
                self.history.engagement.add(boundary_signals)
                summary = self._with_block_times(summarize_engagement(self.history.engagement))
                classification = classify_engagement(summary)
                self.store.append_engagement(summary)
                engagement_blocks.append(CompletedEngagementBlock(summary, classification))
                self.history.engagement.reset(
                    self.next_engagement_end_timestamp,
                    self.latest_signals,
                )
                self.next_engagement_end_timestamp += 10.0

            while timestamp >= self.next_sleepiness_end_timestamp:
                boundary_signals = FrameSignals(
                    timestamp=self.next_sleepiness_end_timestamp,
                    face_detected=self.latest_signals.face_detected,
                    engagement=self.latest_signals.engagement,
                    drowsiness=self.latest_signals.drowsiness,
                )
                self.history.sleepiness.add(boundary_signals)
                summary = self._with_block_times(summarize_sleepiness(self.history.sleepiness))
                classification = classify_drowsiness(summary)
                self.store.append_sleepiness(summary)
                sleepiness_blocks.append(CompletedSleepinessBlock(summary, classification))
                self.history.sleepiness.reset(
                    self.next_sleepiness_end_timestamp,
                    self.latest_signals,
                )
                self.next_sleepiness_end_timestamp += 60.0

        return SmartDeskPipelineFlush(
            emotion_blocks=emotion_blocks,
            engagement_blocks=engagement_blocks,
            sleepiness_blocks=sleepiness_blocks,
        )

    def _with_block_times(self, summary: Any):
        """Attach ISO wall-clock block times when a clock base is available."""
        if (
            self.block_time_base is None
            or summary.start_timestamp is None
            or summary.end_timestamp is None
        ):
            return summary

        start_time = self.block_time_base + timedelta(seconds=float(summary.start_timestamp))
        end_time = self.block_time_base + timedelta(seconds=float(summary.end_timestamp))
        return replace(
            summary,
            block_start_time=start_time.isoformat(),
            block_end_time=end_time.isoformat(),
        )
