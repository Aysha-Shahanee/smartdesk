"""Build clean API responses from SmartDesk v2 detection rows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


STATE_ORDER = ("Focused", "Struggling", "Disengaged", "Fatigued", "Overloaded")
STATE_KEYS = ("focused", "struggling", "disengaged", "fatigued", "overloaded")
STATE_TITLE = dict(zip(STATE_KEYS, STATE_ORDER))
RISK_WEIGHTS = {
    "Focused": 20.0,
    "Struggling": 55.0,
    "Disengaged": 45.0,
    "Fatigued": 70.0,
    "Overloaded": 90.0,
}


@dataclass(frozen=True)
class WorkloadRiskPoint:
    block_start_time: str
    block_end_time: str
    workload_risk_score: int
    confidence: float
    final_state_block_count: int
    duration_minutes: float
    dominant_state: str | None
    state_scores: dict[str, float]
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkloadRiskSummary:
    workload_risk_score: int | None
    observed_minutes: float
    block_count: int
    driver_state: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_state(value: str | None) -> str | None:
    """Return title-case API state for known v2 state labels."""
    if not value:
        return None
    normalized = str(value).strip().replace("-", "_").replace(" ", "_").lower()
    return STATE_TITLE.get(normalized) or str(value)


def state_scores_from_reporting(block: dict[str, Any]) -> dict[str, float]:
    """Return title-case state score ratios from one reporting block."""
    return {
        title: _float(block.get(f"{key}_ratio"))
        for key, title in zip(STATE_KEYS, STATE_ORDER)
    }


def state_scores_from_final_state(block: dict[str, Any]) -> dict[str, float]:
    """Return one-hot state scores from one 5-minute final-state block."""
    state = normalize_state(block.get("state"))
    return {title: 1.0 if title == state else 0.0 for title in STATE_ORDER}


def reporting_block_to_api_block(block: dict[str, Any]) -> dict[str, Any]:
    """Convert a 15-minute reporting row dict into the clean session block shape."""
    dominant_state = normalize_state(block.get("dominant_state"))
    state_scores = state_scores_from_reporting(block)
    return {
        "block_start_time": block.get("block_start_time"),
        "block_end_time": block.get("block_end_time"),
        "dominant_state": dominant_state,
        "state_scores": state_scores,
        "final_state_block_count": int(block.get("final_state_block_count") or 0),
        "ready": bool(block.get("ready", False)),
    }


def final_state_block_to_api_block(block: dict[str, Any]) -> dict[str, Any]:
    """Convert a 5-minute final-state row dict into a fallback session block shape."""
    dominant_state = normalize_state(block.get("state"))
    state_scores = state_scores_from_final_state(block)
    return {
        "block_start_time": block.get("block_start_time"),
        "block_end_time": block.get("block_end_time"),
        "dominant_state": dominant_state,
        "state_scores": state_scores,
        "final_state_block_count": 1 if block.get("state") else 0,
        "ready": bool(block.get("ready", False)),
    }


def status_to_api_status(status: dict[str, Any]) -> dict[str, Any]:
    """Normalize service status for clean new API fields."""
    latest_state = normalize_state(
        status.get("latest_state")
        or _latest_state_from_counts(status.get("completed_counts") or {})
    )
    return {
        **status,
        "latest_state": latest_state or "Unknown",
        "session_id": status.get("session_id") or status.get("current_session_id"),
        "session_start_time": status.get("session_start_time")
        or status.get("real_start_time")
        or status.get("program_start_time"),
        "model_ready": status.get("model_ready", True),
    }


def build_current_session_response(
    *,
    status: dict[str, Any],
    session: dict[str, Any] | None,
    reporting_blocks: list[dict[str, Any]] | None = None,
    final_state_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the `/sessions/current` response from new v2 rows."""
    reporting_blocks = reporting_blocks or []
    final_state_blocks = final_state_blocks or []
    completed_blocks = [reporting_block_to_api_block(block) for block in reporting_blocks]
    if not completed_blocks:
        completed_blocks = [final_state_block_to_api_block(block) for block in final_state_blocks]

    return {
        "ok": True,
        "status": status_to_api_status(status),
        "session": session,
        "current_block": None,
        "completed_blocks": completed_blocks,
        "blocks": completed_blocks,
        "final_state_blocks": [final_state_block_to_api_block(block) for block in final_state_blocks],
    }


def workload_risk_score(state_scores: dict[str, float]) -> int:
    """Convert state ratios into a 0-100 workload-risk score."""
    score = sum(RISK_WEIGHTS[state] * _float(state_scores.get(state)) for state in STATE_ORDER)
    return round(max(0.0, min(100.0, score)))


def reporting_block_to_workload_point(block: dict[str, Any]) -> WorkloadRiskPoint:
    """Convert one reporting block into one workload-risk point."""
    state_scores = state_scores_from_reporting(block)
    return WorkloadRiskPoint(
        block_start_time=str(block.get("block_start_time") or ""),
        block_end_time=str(block.get("block_end_time") or ""),
        workload_risk_score=workload_risk_score(state_scores),
        confidence=_confidence(block),
        final_state_block_count=int(block.get("final_state_block_count") or 0),
        duration_minutes=_duration_minutes(block.get("block_start_time"), block.get("block_end_time")),
        dominant_state=normalize_state(block.get("dominant_state")),
        state_scores=state_scores,
        ready=bool(block.get("ready", False)),
    )


def workload_risk_series(blocks: list[dict[str, Any]]) -> list[WorkloadRiskPoint]:
    """Return oldest-first workload-risk points from reporting blocks."""
    return [
        reporting_block_to_workload_point(block)
        for block in sorted(blocks, key=lambda item: item.get("block_start_time") or "")
        if block.get("block_start_time") and block.get("block_end_time")
    ]


def workload_risk_summary(blocks: list[dict[str, Any]]) -> WorkloadRiskSummary:
    """Return one workload-risk summary for a period of reporting blocks."""
    points = workload_risk_series(blocks)
    if not points:
        return WorkloadRiskSummary(None, 0.0, 0, None)

    weighted_total = 0.0
    weight_total = 0.0
    observed_minutes = 0.0
    state_totals = {state: 0.0 for state in STATE_ORDER}

    for point in points:
        weight = point.duration_minutes * point.confidence
        if weight <= 0:
            continue
        weighted_total += point.workload_risk_score * weight
        weight_total += weight
        observed_minutes += point.duration_minutes
        for state, value in point.state_scores.items():
            state_totals[state] += value * weight

    if weight_total <= 0:
        return WorkloadRiskSummary(None, round(observed_minutes, 1), 0, None)

    driver_state = max(state_totals, key=state_totals.get)
    if state_totals[driver_state] <= 0:
        driver_state = None

    return WorkloadRiskSummary(
        workload_risk_score=round(weighted_total / weight_total),
        observed_minutes=round(observed_minutes, 1),
        block_count=len(points),
        driver_state=driver_state,
    )


def build_workload_risk_response(
    *,
    from_time: str,
    to_time: str,
    reporting_blocks: list[dict[str, Any]],
    final_state_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the clean replacement response for `/stress`."""
    summary = workload_risk_summary(reporting_blocks)
    points = workload_risk_series(reporting_blocks)
    return {
        "from": from_time,
        "to": to_time,
        "summary": summary.to_dict(),
        "points": [point.to_dict() for point in points],
        "final_state_points": [
            final_state_block_to_api_block(block)
            for block in (final_state_blocks or [])
        ],
    }


def _confidence(block: dict[str, Any]) -> float:
    if not block.get("ready", False):
        return 0.0
    count = int(block.get("final_state_block_count") or 0)
    return round(max(0.0, min(1.0, count / 3.0)), 3)


def _duration_minutes(start: Any, end: Any) -> float:
    try:
        start_dt = datetime.fromisoformat(str(start))
        end_dt = datetime.fromisoformat(str(end))
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, (end_dt - start_dt).total_seconds() / 60.0), 2)


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _latest_state_from_counts(counts: dict[str, Any]) -> str | None:
    if counts.get("reporting"):
        return None
    if counts.get("final_state"):
        return None
    return None

