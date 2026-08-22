"""Temporal averaging for frame-level emotion probabilities."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.emotion.rules import DEFAULT_RULE_CONFIG, interpret_emotion_probabilities
from src.emotion.types import EmotionClass, EmotionPrediction, EmotionRuleConfig


EMOTION_WINDOW_SECONDS = 10.0


@dataclass(frozen=True)
class EmotionBlockSummary:
    """Average emotion probabilities for one completed temporal block."""

    start_timestamp: float | None
    end_timestamp: float | None
    block_start_time: str | None
    block_end_time: str | None
    window_seconds: float
    total_time: float
    valid_frame_count: int
    happy_avg: float
    neutral_avg: float
    confusion_avg: float
    top_class: str
    top_probability: float
    state: str
    sublabel: str
    ready: bool


@dataclass
class EmotionTemporalAccumulator:
    """Running 10-second emotion accumulator.

    It stores only probability sums and counts, not per-frame predictions.
    """

    window_seconds: float = EMOTION_WINDOW_SECONDS
    rule_config: EmotionRuleConfig = DEFAULT_RULE_CONFIG
    start_timestamp: float | None = None
    last_timestamp: float | None = None
    total_time: float = 0.0
    valid_frame_count: int = 0
    probability_sums: dict[EmotionClass, float] = field(
        default_factory=lambda: {label: 0.0 for label in EmotionClass}
    )

    def add(self, timestamp: float, prediction: EmotionPrediction | None) -> bool:
        """Add one frame prediction and return True if the block is full."""
        timestamp = float(timestamp)
        if self.start_timestamp is None or self.last_timestamp is None:
            self.start_timestamp = timestamp
            self.last_timestamp = timestamp
            self._add_prediction(prediction)
            return False

        delta = max(0.0, timestamp - self.last_timestamp)
        self.last_timestamp = timestamp
        self.total_time += delta
        self._add_prediction(prediction)
        return self.is_full

    @property
    def is_full(self) -> bool:
        """Whether enough observed time has accumulated for this block."""
        return self.total_time >= self.window_seconds

    def summarize(self) -> EmotionBlockSummary:
        """Create a summary from the current running sums."""
        averages = self._average_probabilities()
        interpreted = interpret_emotion_probabilities(averages, config=self.rule_config)
        return EmotionBlockSummary(
            start_timestamp=self.start_timestamp,
            end_timestamp=self.last_timestamp,
            block_start_time=None,
            block_end_time=None,
            window_seconds=self.window_seconds,
            total_time=self.total_time,
            valid_frame_count=self.valid_frame_count,
            happy_avg=averages[EmotionClass.HAPPY],
            neutral_avg=averages[EmotionClass.NEUTRAL],
            confusion_avg=averages[EmotionClass.CONFUSION],
            top_class=interpreted.top_class.value,
            top_probability=interpreted.top_probability,
            state=interpreted.state.value,
            sublabel=interpreted.sublabel.value,
            ready=self.is_full and self.valid_frame_count > 0,
        )

    def reset(self, start_timestamp: float | None = None, seed_prediction: EmotionPrediction | None = None) -> None:
        """Clear this accumulator for the next emotion block."""
        window_seconds = self.window_seconds
        rule_config = self.rule_config
        self.__dict__.update(
            EmotionTemporalAccumulator(
                window_seconds=window_seconds,
                rule_config=rule_config,
            ).__dict__
        )
        if start_timestamp is not None:
            self.start_timestamp = float(start_timestamp)
            self.last_timestamp = float(start_timestamp)
        if seed_prediction is not None:
            self._add_prediction(seed_prediction)

    def _add_prediction(self, prediction: EmotionPrediction | None) -> None:
        if prediction is None:
            return
        for label in EmotionClass:
            self.probability_sums[label] += prediction.probability(label)
        self.valid_frame_count += 1

    def _average_probabilities(self) -> dict[EmotionClass, float]:
        if self.valid_frame_count <= 0:
            return {label: 0.0 for label in EmotionClass}
        return {
            label: self.probability_sums[label] / self.valid_frame_count
            for label in EmotionClass
        }


@dataclass
class EmotionBlockRecorder:
    """Gate emotion blocks behind an official aligned start timestamp."""

    official_start_timestamp: float = 0.0
    window_seconds: float = EMOTION_WINDOW_SECONDS
    rule_config: EmotionRuleConfig = DEFAULT_RULE_CONFIG
    accumulator: EmotionTemporalAccumulator = field(init=False)
    started: bool = False
    next_block_end_timestamp: float | None = None

    def __post_init__(self) -> None:
        self.official_start_timestamp = float(self.official_start_timestamp)
        self.accumulator = EmotionTemporalAccumulator(
            window_seconds=self.window_seconds,
            rule_config=self.rule_config,
        )

    def add(self, timestamp: float, prediction: EmotionPrediction | None) -> EmotionBlockSummary | None:
        """Add one frame and return a completed summary when a block closes.

        Predictions before ``official_start_timestamp`` are ignored, so partial
        warmup time is not stored as an official emotion block.
        """
        timestamp = float(timestamp)
        if timestamp < self.official_start_timestamp:
            return None

        if not self.started:
            self.accumulator.reset(start_timestamp=self.official_start_timestamp)
            self.started = True
            self.next_block_end_timestamp = self.official_start_timestamp + self.window_seconds

        if (
            self.next_block_end_timestamp is not None
            and timestamp >= self.next_block_end_timestamp
        ):
            self.accumulator.last_timestamp = self.next_block_end_timestamp
            self.accumulator.total_time = (
                self.next_block_end_timestamp - float(self.accumulator.start_timestamp)
            )
            summary = self.accumulator.summarize()
            self.accumulator.reset(
                start_timestamp=self.next_block_end_timestamp,
                seed_prediction=prediction,
            )
            self.next_block_end_timestamp += self.window_seconds
            return summary

        self.accumulator.add(timestamp, prediction)
        return None
