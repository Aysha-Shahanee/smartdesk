"""Persistent storage for completed temporal summary blocks.

Only finished block summaries are stored. Raw webcam frames and per-frame
feature values are never written by this module.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.emotion.temporal import EmotionBlockSummary
from src.state_fusion.state_types import FinalStateBlockSummary, ReportingBlockSummary
from src.temporal.aggregator import (
    EngagementSummary,
    SleepinessSummary,
    summarize_engagement,
    summarize_sleepiness,
)
from src.temporal.history import FrameSignals, SignalHistory


ENGAGEMENT_MAX_BLOCKS = 90
SLEEPINESS_MAX_BLOCKS = 15
EMOTION_MAX_BLOCKS = 90
FINAL_STATE_MAX_BLOCKS = 12
REPORTING_MAX_BLOCKS = 8
DEFAULT_STORAGE_DIR = Path("data") / "temporal"


BlockType = Literal["emotion", "engagement", "sleepiness", "final_state", "reporting"]


@dataclass(frozen=True)
class StoredBlock:
    """One persisted temporal summary block."""

    block_type: BlockType
    saved_at: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class SessionRecord:
    """One persisted camera session record."""

    session_id: str
    saved_at: str
    program_start_time: str
    warmup_end_time: str
    real_start_time: str
    actual_camera_end_time: str
    usable_block_end_time: str
    discarded_tail_seconds: float
    startup_wait_seconds_after_warmup: float
    official_seconds_requested: float
    sample_fps: float
    frames_read: int
    samples_processed: int
    face_detected_samples: int
    completed_counts: dict[str, int]
    storage_dir: str


class JsonlBlockStore:
    """Append-only JSONL block store with max-block trimming."""

    def __init__(
        self,
        storage_dir: Path | str = DEFAULT_STORAGE_DIR,
        emotion_max_blocks: int = EMOTION_MAX_BLOCKS,
        engagement_max_blocks: int = ENGAGEMENT_MAX_BLOCKS,
        sleepiness_max_blocks: int = SLEEPINESS_MAX_BLOCKS,
        final_state_max_blocks: int = FINAL_STATE_MAX_BLOCKS,
        reporting_max_blocks: int = REPORTING_MAX_BLOCKS,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.emotion_max_blocks = emotion_max_blocks
        self.engagement_max_blocks = engagement_max_blocks
        self.sleepiness_max_blocks = sleepiness_max_blocks
        self.final_state_max_blocks = final_state_max_blocks
        self.reporting_max_blocks = reporting_max_blocks
        self.emotion_path = self.storage_dir / "emotion_blocks.jsonl"
        self.engagement_path = self.storage_dir / "engagement_blocks.jsonl"
        self.sleepiness_path = self.storage_dir / "sleepiness_blocks.jsonl"
        self.final_state_path = self.storage_dir / "final_state_blocks.jsonl"
        self.reporting_path = self.storage_dir / "reporting_blocks.jsonl"
        self.session_path = self.storage_dir / "session_records.jsonl"

    def append_emotion(self, summary: EmotionBlockSummary) -> None:
        """Append a completed 10-second emotion block."""
        self._append(
            path=self.emotion_path,
            block_type="emotion",
            summary=summary,
            max_blocks=self.emotion_max_blocks,
        )

    def append_engagement(self, summary: EngagementSummary) -> None:
        """Append a completed 10-second engagement block."""
        self._append(
            path=self.engagement_path,
            block_type="engagement",
            summary=summary,
            max_blocks=self.engagement_max_blocks,
        )

    def append_sleepiness(self, summary: SleepinessSummary) -> None:
        """Append a completed 60-second sleepiness block."""
        self._append(
            path=self.sleepiness_path,
            block_type="sleepiness",
            summary=summary,
            max_blocks=self.sleepiness_max_blocks,
        )

    def append_final_state(self, summary: FinalStateBlockSummary) -> None:
        """Append a completed 5-minute final work-state block."""
        self._append(
            path=self.final_state_path,
            block_type="final_state",
            summary=summary,
            max_blocks=self.final_state_max_blocks,
        )

    def append_reporting(self, summary: ReportingBlockSummary) -> None:
        """Append a completed 15-minute reporting block."""
        self._append(
            path=self.reporting_path,
            block_type="reporting",
            summary=summary,
            max_blocks=self.reporting_max_blocks,
        )

    def read_blocks(self, block_type: BlockType) -> list[StoredBlock]:
        """Read stored summary blocks for later decision logic."""
        if block_type == "emotion":
            path = self.emotion_path
        elif block_type == "engagement":
            path = self.engagement_path
        elif block_type == "sleepiness":
            path = self.sleepiness_path
        elif block_type == "final_state":
            path = self.final_state_path
        else:
            path = self.reporting_path
        if not path.exists():
            return []

        blocks: list[StoredBlock] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                blocks.append(
                    StoredBlock(
                        block_type=data["block_type"],
                        saved_at=data["saved_at"],
                        summary=data["summary"],
                    )
                )
        return blocks

    def append_session(self, record: SessionRecord) -> None:
        """Append one completed session metadata record."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        with self.session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def read_sessions(self) -> list[SessionRecord]:
        """Read stored session metadata records."""
        if not self.session_path.exists():
            return []

        sessions: list[SessionRecord] = []
        with self.session_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                sessions.append(SessionRecord(**json.loads(line)))
        return sessions

    def _append(
        self,
        path: Path,
        block_type: BlockType,
        summary: (
            EmotionBlockSummary
            | EngagementSummary
            | SleepinessSummary
            | FinalStateBlockSummary
            | ReportingBlockSummary
        ),
        max_blocks: int,
    ) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        record = StoredBlock(
            block_type=block_type,
            saved_at=datetime.now(UTC).isoformat(),
            summary=_to_dict(summary),
        )

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

        self._trim(path, max_blocks)

    @staticmethod
    def _trim(path: Path, max_blocks: int) -> None:
        if max_blocks <= 0 or not path.exists():
            return

        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_blocks:
            return

        latest = lines[-max_blocks:]
        path.write_text("\n".join(latest) + "\n", encoding="utf-8")


class TemporalBlockRecorder:
    """Update accumulators and store completed summary blocks."""

    def __init__(
        self,
        history: SignalHistory | None = None,
        store: JsonlBlockStore | None = None,
    ) -> None:
        self.history = history or SignalHistory()
        self.store = store or JsonlBlockStore()

    def add(self, signals: FrameSignals) -> dict[str, bool]:
        """Add one frame signal and store any completed block summaries.

        Returns:
            Dict showing whether an engagement or sleepiness block was stored.
        """
        status = self.history.add(signals)
        stored = {"engagement": False, "sleepiness": False}

        if status["engagement"]:
            self.store.append_engagement(summarize_engagement(self.history.engagement))
            self.history.engagement.reset(signals.timestamp, signals)
            stored["engagement"] = True

        if status["sleepiness"]:
            self.store.append_sleepiness(summarize_sleepiness(self.history.sleepiness))
            self.history.sleepiness.reset(signals.timestamp, signals)
            stored["sleepiness"] = True

        return stored


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"Cannot serialize block summary of type {type(value)!r}")
