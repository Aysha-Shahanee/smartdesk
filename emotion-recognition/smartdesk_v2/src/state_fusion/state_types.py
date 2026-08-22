"""Shared state labels and evidence types for rule-based fusion."""

from dataclasses import dataclass
from enum import Enum


class DeveloperWorkState(str, Enum):
    """Current five Developer Work States."""

    FOCUSED = "focused"
    STRUGGLING = "struggling"
    DISENGAGED = "disengaged"
    FATIGUED = "fatigued"
    OVERLOADED = "overloaded"


@dataclass(frozen=True)
class FusionRatios:
    """Five-minute proportion features used by the v1 fusion rules."""

    confusion_ratio: float
    stable_emotion_ratio: float
    engaged_ratio: float
    low_engagement_ratio: float
    drowsy_ratio: float


@dataclass(frozen=True)
class FusionCounts:
    """Counts behind the ratio features, kept for explanation/debugging."""

    emotion_confusion_count: int = 0
    emotion_stable_count: int = 0
    engagement_high_count: int = 0
    engagement_medium_count: int = 0
    engagement_low_count: int = 0
    sleepiness_alert_count: int = 0
    sleepiness_drowsy_count: int = 0

    @property
    def emotion_total(self) -> int:
        return self.emotion_confusion_count + self.emotion_stable_count

    @property
    def engagement_total(self) -> int:
        return (
            self.engagement_high_count
            + self.engagement_medium_count
            + self.engagement_low_count
        )

    @property
    def sleepiness_total(self) -> int:
        return self.sleepiness_alert_count + self.sleepiness_drowsy_count

    def to_ratios(self) -> FusionRatios:
        """Convert stored counts into rule ratios."""
        emotion_total = self.emotion_total
        engagement_total = self.engagement_total
        sleepiness_total = self.sleepiness_total
        return FusionRatios(
            confusion_ratio=_ratio(self.emotion_confusion_count, emotion_total),
            stable_emotion_ratio=_ratio(self.emotion_stable_count, emotion_total),
            engaged_ratio=_ratio(
                self.engagement_high_count + self.engagement_medium_count,
                engagement_total,
            ),
            low_engagement_ratio=_ratio(self.engagement_low_count, engagement_total),
            drowsy_ratio=_ratio(self.sleepiness_drowsy_count, sleepiness_total),
        )

    @property
    def dominant_emotion(self) -> str | None:
        if self.emotion_total == 0:
            return None
        if self.emotion_confusion_count > self.emotion_stable_count:
            return "confusion"
        return "stable"

    @property
    def dominant_engagement(self) -> str | None:
        counts = {
            "high": self.engagement_high_count,
            "medium": self.engagement_medium_count,
            "low": self.engagement_low_count,
        }
        if self.engagement_total == 0:
            return None
        return max(counts, key=counts.get)

    @property
    def dominant_sleepiness(self) -> str | None:
        if self.sleepiness_total == 0:
            return None
        if self.sleepiness_drowsy_count > self.sleepiness_alert_count:
            return "drowsy"
        return "alert"


@dataclass(frozen=True)
class FusionDecision:
    """Final state decision plus the rule evidence used to choose it."""

    state: DeveloperWorkState | None
    matched_rule: str
    ratios: FusionRatios
    counts: FusionCounts | None = None


@dataclass(frozen=True)
class FinalStateBlockSummary:
    """Stored five-minute Developer Work State summary."""

    start_timestamp: float | None
    end_timestamp: float | None
    block_start_time: str | None
    block_end_time: str | None
    window_seconds: float
    state: str | None
    matched_rule: str
    confusion_ratio: float
    stable_emotion_ratio: float
    engaged_ratio: float
    low_engagement_ratio: float
    drowsy_ratio: float
    emotion_confusion_count: int
    emotion_stable_count: int
    engagement_high_count: int
    engagement_medium_count: int
    engagement_low_count: int
    sleepiness_alert_count: int
    sleepiness_drowsy_count: int
    dominant_emotion: str | None
    dominant_engagement: str | None
    dominant_sleepiness: str | None
    ready: bool


@dataclass(frozen=True)
class ReportingBlockSummary:
    """Stored 15-minute reporting summary from final-state blocks."""

    start_timestamp: float | None
    end_timestamp: float | None
    block_start_time: str | None
    block_end_time: str | None
    window_seconds: float
    final_state_block_count: int
    focused_ratio: float
    struggling_ratio: float
    disengaged_ratio: float
    fatigued_ratio: float
    overloaded_ratio: float
    dominant_state: str | None
    ready: bool


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
