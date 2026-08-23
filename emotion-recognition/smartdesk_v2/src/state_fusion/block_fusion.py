"""Build five-minute final-state blocks from stored lower-level summaries."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Iterable

from src.drowsiness.classifier import SleepinessLabel, classify_drowsiness
from src.engagement.classifier import EngagementLabel, classify_engagement
from src.state_fusion.fusion import fuse_developer_state
from src.state_fusion.state_types import (
    DeveloperWorkState,
    FinalStateBlockSummary,
    FusionCounts,
)
from src.temporal.aggregator import EngagementSummary, SleepinessSummary
from src.temporal.block_store import JsonlBlockStore, StoredBlock


FINAL_STATE_WINDOW_SECONDS = 300.0
MIN_EMOTION_BLOCKS = 1
MIN_ENGAGEMENT_BLOCKS = 1
MIN_SLEEPINESS_BLOCKS = 1


def build_final_state_summary(
    emotion_blocks: Iterable[StoredBlock],
    engagement_blocks: Iterable[StoredBlock],
    sleepiness_blocks: Iterable[StoredBlock],
    *,
    start_timestamp: float,
    end_timestamp: float,
    block_start_time: str | None = None,
    block_end_time: str | None = None,
    current_state: DeveloperWorkState | str | None = None,
) -> FinalStateBlockSummary:
    """Create one final-state summary from stored blocks inside a window."""
    emotion_window = _filter_window(
        emotion_blocks,
        start_timestamp,
        end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
    )
    engagement_window = _filter_window(
        engagement_blocks,
        start_timestamp,
        end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
    )
    sleepiness_window = _filter_window(
        sleepiness_blocks,
        start_timestamp,
        end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
    )

    counts = FusionCounts(
        emotion_confusion_count=_count_confusion(emotion_window),
        emotion_stable_count=_count_stable_emotion(emotion_window),
        engagement_high_count=_count_engagement(engagement_window, EngagementLabel.HIGH),
        engagement_medium_count=_count_engagement(engagement_window, EngagementLabel.MEDIUM),
        engagement_low_count=_count_engagement(engagement_window, EngagementLabel.LOW),
        sleepiness_alert_count=_count_sleepiness(sleepiness_window, SleepinessLabel.ALERT),
        sleepiness_drowsy_count=_count_sleepiness(sleepiness_window, SleepinessLabel.DROWSY),
    )
    decision = fuse_developer_state(counts, current_state=current_state)
    ratios = decision.ratios
    ready = (
        counts.emotion_total >= MIN_EMOTION_BLOCKS
        and counts.engagement_total >= MIN_ENGAGEMENT_BLOCKS
        and counts.sleepiness_total >= MIN_SLEEPINESS_BLOCKS
    )
    state = decision.state.value if decision.state is not None and ready else None
    matched_rule = decision.matched_rule if ready else "insufficient_data"

    return FinalStateBlockSummary(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
        window_seconds=end_timestamp - start_timestamp,
        state=state,
        matched_rule=matched_rule,
        confusion_ratio=ratios.confusion_ratio,
        stable_emotion_ratio=ratios.stable_emotion_ratio,
        engaged_ratio=ratios.engaged_ratio,
        low_engagement_ratio=ratios.low_engagement_ratio,
        drowsy_ratio=ratios.drowsy_ratio,
        emotion_confusion_count=counts.emotion_confusion_count,
        emotion_stable_count=counts.emotion_stable_count,
        engagement_high_count=counts.engagement_high_count,
        engagement_medium_count=counts.engagement_medium_count,
        engagement_low_count=counts.engagement_low_count,
        sleepiness_alert_count=counts.sleepiness_alert_count,
        sleepiness_drowsy_count=counts.sleepiness_drowsy_count,
        dominant_emotion=counts.dominant_emotion,
        dominant_engagement=counts.dominant_engagement,
        dominant_sleepiness=counts.dominant_sleepiness,
        ready=ready,
    )


def build_and_store_final_state_summary(
    store: JsonlBlockStore,
    *,
    start_timestamp: float,
    end_timestamp: float,
    block_start_time: str | None = None,
    block_end_time: str | None = None,
    current_state: DeveloperWorkState | str | None = None,
) -> FinalStateBlockSummary:
    """Read stored lower-level blocks, fuse one window, and append it."""
    summary = build_final_state_summary(
        store.read_blocks("emotion"),
        store.read_blocks("engagement"),
        store.read_blocks("sleepiness"),
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
        current_state=current_state,
    )
    store.append_final_state(summary)
    return summary


def _filter_window(
    blocks: Iterable[StoredBlock],
    start_timestamp: float,
    end_timestamp: float,
    *,
    block_start_time: str | None = None,
    block_end_time: str | None = None,
) -> list[StoredBlock]:
    target_start = _parse_time(block_start_time)
    target_end = _parse_time(block_end_time)
    selected = []
    for block in blocks:
        summary = block.summary
        summary_start_time = _parse_time(summary.get("block_start_time"))
        summary_end_time = _parse_time(summary.get("block_end_time"))
        if target_start is not None and target_end is not None:
            if summary_start_time is None or summary_end_time is None:
                continue
            if summary_start_time >= target_start and summary_end_time <= target_end:
                selected.append(block)
            continue

        block_start = summary.get("start_timestamp")
        block_end = summary.get("end_timestamp")
        if block_start is None or block_end is None:
            continue
        if float(block_start) >= start_timestamp and float(block_end) <= end_timestamp:
            selected.append(block)
    return selected


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _count_confusion(blocks: Iterable[StoredBlock]) -> int:
    return sum(1 for block in blocks if _emotion_label(block) == "confusion")


def _count_stable_emotion(blocks: Iterable[StoredBlock]) -> int:
    return sum(1 for block in blocks if _emotion_label(block) in {"happy", "neutral"})


def _emotion_label(block: StoredBlock) -> str:
    summary = block.summary
    top_class = str(summary.get("top_class", "")).lower()
    state = str(summary.get("state", "")).lower()
    if top_class in {"happy", "neutral", "confusion"}:
        return top_class
    if state in {"needs_help", "confusion"}:
        return "confusion"
    if state in {"happy", "neutral"}:
        return state
    return ""


def _count_engagement(blocks: Iterable[StoredBlock], label: EngagementLabel) -> int:
    count = 0
    for block in blocks:
        classification = classify_engagement(_summary_from_dict(EngagementSummary, block.summary))
        if classification.label == label:
            count += 1
    return count


def _count_sleepiness(blocks: Iterable[StoredBlock], label: SleepinessLabel) -> int:
    count = 0
    for block in blocks:
        classification = classify_drowsiness(_summary_from_dict(SleepinessSummary, block.summary))
        if classification.label == label:
            count += 1
    return count


def _summary_from_dict(summary_type, data: dict):
    allowed = {field.name for field in fields(summary_type)}
    return summary_type(**{key: value for key, value in data.items() if key in allowed})

