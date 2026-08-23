"""Build 15-minute reporting summaries from 5-minute final-state blocks."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from src.state_fusion.state_types import DeveloperWorkState, ReportingBlockSummary
from src.temporal.block_store import JsonlBlockStore, StoredBlock


REPORTING_WINDOW_SECONDS = 900.0
EXPECTED_FINAL_STATE_BLOCKS = 3


def build_reporting_summary(
    final_state_blocks: Iterable[StoredBlock],
    *,
    start_timestamp: float,
    end_timestamp: float,
    block_start_time: str | None = None,
    block_end_time: str | None = None,
) -> ReportingBlockSummary:
    """Create one 15-minute report from 5-minute final-state blocks."""
    selected = _filter_window(
        final_state_blocks,
        start_timestamp,
        end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
    )
    states = [
        str(block.summary.get("state", "")).lower()
        for block in selected
        if block.summary.get("ready") and block.summary.get("state")
    ]
    counts = Counter(states)
    total = len(states)
    dominant_state = _dominant_state(counts) if total > 0 else None

    return ReportingBlockSummary(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
        window_seconds=end_timestamp - start_timestamp,
        final_state_block_count=total,
        focused_ratio=_state_ratio(counts, DeveloperWorkState.FOCUSED, total),
        struggling_ratio=_state_ratio(counts, DeveloperWorkState.STRUGGLING, total),
        disengaged_ratio=_state_ratio(counts, DeveloperWorkState.DISENGAGED, total),
        fatigued_ratio=_state_ratio(counts, DeveloperWorkState.FATIGUED, total),
        overloaded_ratio=_state_ratio(counts, DeveloperWorkState.OVERLOADED, total),
        dominant_state=dominant_state,
        ready=total >= EXPECTED_FINAL_STATE_BLOCKS,
    )


def build_and_store_reporting_summary(
    store: JsonlBlockStore,
    *,
    start_timestamp: float,
    end_timestamp: float,
    block_start_time: str | None = None,
    block_end_time: str | None = None,
) -> ReportingBlockSummary:
    """Read final-state blocks, build one report, and append it."""
    summary = build_reporting_summary(
        store.read_blocks("final_state"),
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        block_start_time=block_start_time,
        block_end_time=block_end_time,
    )
    store.append_reporting(summary)
    return summary


def _state_ratio(counts: Counter[str], state: DeveloperWorkState, total: int) -> float:
    if total <= 0:
        return 0.0
    return counts[state.value] / total


def _dominant_state(counts: Counter[str]) -> str | None:
    if not counts:
        return None
    priority = [
        DeveloperWorkState.OVERLOADED.value,
        DeveloperWorkState.FATIGUED.value,
        DeveloperWorkState.DISENGAGED.value,
        DeveloperWorkState.STRUGGLING.value,
        DeveloperWorkState.FOCUSED.value,
    ]
    max_count = max(counts.values())
    tied = {state for state, count in counts.items() if count == max_count}
    for state in priority:
        if state in tied:
            return state
    return sorted(tied)[0]


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
