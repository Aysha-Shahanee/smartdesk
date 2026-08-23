"""Endpoint helpers for serving SmartDesk v2 detection data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.smartdesk_detection_repository import SmartDeskDetectionRepository
from app.services import smartdesk_detection_response_builder as response_builder


def current_session_response(
    db: Session,
    *,
    user_id: str,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the `/sessions/current` payload from v2 SQL rows."""
    repo = SmartDeskDetectionRepository(db)
    live_session_id = None
    if status and status.get("running"):
        live_session_id = status.get("current_session_id") or status.get("session_id")

    session = repo.session_by_id(live_session_id) if live_session_id else None
    if session is None:
        session = repo.latest_session_with_final_state_blocks(user_id)
    if session is None:
        session = repo.latest_session(user_id)

    block_session_id = live_session_id or (session["id"] if session is not None else None)
    reporting_blocks: list[dict[str, Any]] = []
    final_state_blocks: list[dict[str, Any]] = []

    if block_session_id is not None:
        reporting_blocks = repo.reporting_blocks_for_session(block_session_id, user_id=user_id)
        final_state_blocks = repo.final_state_blocks_for_session(block_session_id, user_id=user_id)

    effective_status = status or _status_from_session(session)
    return response_builder.build_current_session_response(
        status=effective_status,
        session=session,
        reporting_blocks=reporting_blocks,
        final_state_blocks=final_state_blocks,
    )


def workload_risk_response(
    db: Session,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Build the `/stress` replacement payload from v2 reporting rows."""
    repo = SmartDeskDetectionRepository(db)
    reporting_blocks = repo.reporting_blocks_between(user_id, start, end)
    final_state_blocks = repo.final_state_blocks_between(user_id, start, end)
    return response_builder.build_workload_risk_response(
        from_time=start.isoformat(),
        to_time=end.isoformat(),
        reporting_blocks=reporting_blocks,
        final_state_blocks=final_state_blocks,
    )


def _status_from_session(session: dict[str, Any] | None) -> dict[str, Any]:
    if session is None:
        return {
            "running": False,
            "camera_ready": False,
            "last_error": None,
            "current_session_id": None,
            "latest_state": "Unknown",
            "completed_counts": {},
        }

    return {
        "running": session.get("status") == "running",
        "camera_ready": False,
        "last_error": None,
        "current_session_id": session.get("id"),
        "program_start_time": session.get("program_start_time"),
        "warmup_end_time": session.get("warmup_end_time"),
        "real_start_time": session.get("real_start_time"),
        "actual_camera_end_time": session.get("actual_camera_end_time"),
        "usable_block_end_time": session.get("usable_block_end_time"),
        "discarded_tail_seconds": session.get("discarded_tail_seconds") or 0.0,
        "startup_wait_seconds_after_warmup": session.get("startup_wait_seconds_after_warmup") or 0.0,
        "sample_fps": session.get("sample_fps") or 0.0,
        "frames_read": session.get("frames_read") or 0,
        "samples_processed": session.get("samples_processed") or 0,
        "face_detected_samples": session.get("face_detected_samples") or 0,
        "completed_counts": session.get("completed_counts") or {},
    }

