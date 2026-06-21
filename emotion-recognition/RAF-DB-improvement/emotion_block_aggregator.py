from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from storage.local_storage import LocalEmotionStorage
from storage.session_manager import SessionManager


EMOTIONS = ("Happy", "Neutral", "Angry", "Surprise")


@dataclass
class EmotionBlockAggregator:
    output_path: Path
    session_manager: SessionManager
    storage: LocalEmotionStorage | None = None
    block_minutes: int = 15
    min_partial_minutes: int = 5
    block_start: datetime | None = None
    last_update_time: datetime | None = None
    emotion_scores: dict[str, float] = field(default_factory=lambda: {emotion: 0.0 for emotion in EMOTIONS})
    processed_frame_count: int = 0

    def __post_init__(self) -> None:
        self.output_path = Path(self.output_path)
        if self.storage is None:
            self.storage = LocalEmotionStorage(self.output_path)
        self.block_start = self.session_manager.session_start_time

    @property
    def block_duration(self) -> timedelta:
        return timedelta(minutes=self.block_minutes)

    def add_frame(self, probabilities: dict[str, float], timestamp: datetime | None = None) -> list[dict]:
        timestamp = timestamp or datetime.now().astimezone()
        completed_blocks = self.complete_expired_blocks(timestamp)
        self.last_update_time = timestamp

        for emotion in EMOTIONS:
            self.emotion_scores[emotion] += float(probabilities.get(emotion, 0.0))
        self.processed_frame_count += 1

        return completed_blocks

    def complete_expired_blocks(self, timestamp: datetime | None = None) -> list[dict]:
        timestamp = timestamp or datetime.now().astimezone()
        self.last_update_time = timestamp

        completed_blocks = []
        while self.block_start is not None and timestamp >= self.block_start + self.block_duration:
            completed_blocks.append(self.finalize_current_block(block_type="complete", end_time=self.block_start + self.block_duration))
            self._start_block(self.block_start + self.block_duration)

        return completed_blocks

    def flush(self, timestamp: datetime | None = None) -> dict | None:
        if self.block_start is None:
            return None

        timestamp = timestamp or datetime.now().astimezone()
        self.last_update_time = timestamp
        duration = timestamp - self.block_start
        if duration < timedelta(minutes=self.min_partial_minutes):
            self._reset_scores()
            return None

        return self.finalize_current_block(block_type="partial", end_time=timestamp)

    def finalize_current_block(self, block_type: str, end_time: datetime) -> dict:
        if self.block_start is None:
            raise RuntimeError("No active emotion block to finalize.")

        if self.processed_frame_count == 0:
            dominant_emotion = "Unknown"
        else:
            dominant_emotion = max(EMOTIONS, key=lambda emotion: self.emotion_scores[emotion])

        duration_minutes = round((end_time - self.block_start).total_seconds() / 60, 2)
        result = {
            "user_id": self.session_manager.user_id,
            "session_id": self.session_manager.session_id,
            "session_start_time": self.session_manager.session_start_time.isoformat(),
            "block_start_time": self.block_start.isoformat(),
            "block_end_time": end_time.isoformat(),
            "block_type": block_type,
            "duration_minutes": duration_minutes,
            "dominant_emotion": dominant_emotion,
            "emotion_scores": dict(self.emotion_scores),
            "processed_frame_count": self.processed_frame_count,
            "synced": False,
        }

        saved_record = self.storage.append_record(result)
        self.storage.cleanup_old_records()
        self._reset_scores()
        return saved_record

    def _start_block(self, block_start: datetime) -> None:
        self.block_start = block_start
        self._reset_scores()

    def _reset_scores(self) -> None:
        self.emotion_scores = {emotion: 0.0 for emotion in EMOTIONS}
        self.processed_frame_count = 0
