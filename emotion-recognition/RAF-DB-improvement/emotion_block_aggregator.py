from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


EMOTIONS = ("Happy", "Neutral", "Angry", "Surprise")


def floor_to_block_start(timestamp: datetime, block_minutes: int = 15) -> datetime:
    minute = (timestamp.minute // block_minutes) * block_minutes
    return timestamp.replace(minute=minute, second=0, microsecond=0)


@dataclass
class EmotionBlockAggregator:
    output_path: Path
    block_minutes: int = 15
    block_start: datetime | None = None
    emotion_scores: dict[str, float] = field(default_factory=lambda: {emotion: 0.0 for emotion in EMOTIONS})
    processed_frame_count: int = 0

    def __post_init__(self) -> None:
        self.output_path = Path(self.output_path)

    @property
    def block_duration(self) -> timedelta:
        return timedelta(minutes=self.block_minutes)

    def add_frame(self, probabilities: dict[str, float], timestamp: datetime | None = None) -> list[dict]:
        timestamp = timestamp or datetime.now().astimezone()
        completed_blocks = self.complete_expired_blocks(timestamp)

        for emotion in EMOTIONS:
            self.emotion_scores[emotion] += float(probabilities.get(emotion, 0.0))
        self.processed_frame_count += 1

        return completed_blocks

    def complete_expired_blocks(self, timestamp: datetime | None = None) -> list[dict]:
        timestamp = timestamp or datetime.now().astimezone()
        self._ensure_block(timestamp)

        completed_blocks = []
        while self.block_start is not None and timestamp >= self.block_start + self.block_duration:
            completed_blocks.append(self.finalize_current_block())
            self._start_block(self.block_start + self.block_duration)

        return completed_blocks

    def flush(self) -> dict | None:
        if self.block_start is None:
            return None
        return self.finalize_current_block()

    def finalize_current_block(self) -> dict:
        if self.block_start is None:
            raise RuntimeError("No active emotion block to finalize.")

        block_end = self.block_start + self.block_duration
        if self.processed_frame_count == 0:
            dominant_emotion = "Unknown"
        else:
            dominant_emotion = max(EMOTIONS, key=lambda emotion: self.emotion_scores[emotion])

        result = {
            "block_start_time": self.block_start.isoformat(),
            "block_end_time": block_end.isoformat(),
            "dominant_emotion": dominant_emotion,
            "emotion_scores": dict(self.emotion_scores),
            "processed_frame_count": self.processed_frame_count,
        }

        self._save_result(result)
        self._reset_scores()
        return result

    def _ensure_block(self, timestamp: datetime) -> None:
        if self.block_start is None:
            self._start_block(floor_to_block_start(timestamp, self.block_minutes))

    def _start_block(self, block_start: datetime) -> None:
        self.block_start = block_start
        self._reset_scores()

    def _reset_scores(self) -> None:
        self.emotion_scores = {emotion: 0.0 for emotion in EMOTIONS}
        self.processed_frame_count = 0

    def _save_result(self, result: dict) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(result) + "\n")
