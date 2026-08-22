"""Read and write SmartDesk v2 detection rows."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import parse_iso
from app.models.db.smartdesk_detection import SmartDeskDetectionSessionRecord
from app.models.db.smartdesk_detection import SmartDeskFinalStateBlockRecord
from app.models.db.smartdesk_detection import SmartDeskReportingBlockRecord
from app.models.db.smartdesk_detection import SmartDeskSignalBlockRecord


_ZONE_PADDING = timedelta(hours=30)


class SmartDeskDetectionRepository:
    """Database helper for the new SmartDesk detection tables."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_session(self, record: dict[str, Any]) -> dict[str, Any]:
        values = {
            "id": record["id"],
            "user_id": record["user_id"],
            "status": record["status"],
            "program_start_time": record["program_start_time"],
            "warmup_end_time": record.get("warmup_end_time"),
            "real_start_time": record.get("real_start_time"),
            "actual_camera_end_time": record.get("actual_camera_end_time"),
            "usable_block_end_time": record.get("usable_block_end_time"),
            "discarded_tail_seconds": float(record.get("discarded_tail_seconds") or 0.0),
            "startup_wait_seconds_after_warmup": float(record.get("startup_wait_seconds_after_warmup") or 0.0),
            "official_seconds_requested": float(record.get("official_seconds_requested") or 0.0),
            "sample_fps": float(record.get("sample_fps") or 0.0),
            "frames_read": int(record.get("frames_read") or 0),
            "samples_processed": int(record.get("samples_processed") or 0),
            "face_detected_samples": int(record.get("face_detected_samples") or 0),
            "completed_counts_json": _json_dumps(record.get("completed_counts") or {}),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        existing = self.db.get(SmartDeskDetectionSessionRecord, values["id"])
        if existing is None:
            self.db.add(SmartDeskDetectionSessionRecord(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        self.db.commit()
        return record

    def upsert_signal_block(self, record: dict[str, Any]) -> dict[str, Any]:
        summary = record.get("summary") or record
        values = {
            "id": record["id"],
            "user_id": record["user_id"],
            "session_id": record["session_id"],
            "block_type": record["block_type"],
            "block_start_time": summary["block_start_time"],
            "block_end_time": summary["block_end_time"],
            "window_seconds": float(summary.get("window_seconds") or 0.0),
            "total_time": float(summary.get("total_time") or 0.0),
            "ready": bool(summary.get("ready", False)),
            "valid_frame_count": int(summary.get("valid_frame_count") or 0),
            "happy_avg": float(summary.get("happy_avg") or 0.0),
            "neutral_avg": float(summary.get("neutral_avg") or 0.0),
            "confusion_avg": float(summary.get("confusion_avg") or 0.0),
            "top_class": summary.get("top_class"),
            "top_probability": float(summary.get("top_probability") or 0.0),
            "emotion_state": summary.get("state"),
            "emotion_sublabel": summary.get("sublabel"),
            "face_visible_ratio": float(summary.get("face_visible_ratio") or 0.0),
            "screen_facing_ratio": float(summary.get("screen_facing_ratio") or 0.0),
            "looking_away_ratio": float(summary.get("looking_away_ratio") or 0.0),
            "long_lookaway_count": int(summary.get("long_lookaway_count") or 0),
            "engagement_label": record.get("engagement_label"),
            "perclos": float(summary.get("perclos") or 0.0),
            "eye_closed_ratio": float(summary.get("eye_closed_ratio") or 0.0),
            "head_down_ratio": float(summary.get("head_down_ratio") or 0.0),
            "possible_yawn_ratio": float(summary.get("possible_yawn_ratio") or 0.0),
            "long_eye_closure_count": int(summary.get("long_eye_closure_count") or 0),
            "yawn_count": int(summary.get("yawn_count") or 0),
            "sleepiness_label": record.get("sleepiness_label"),
            "raw_summary_json": _json_dumps(summary),
            "created_at": record["created_at"],
        }
        existing = self.db.get(SmartDeskSignalBlockRecord, values["id"])
        if existing is None:
            self.db.add(SmartDeskSignalBlockRecord(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        self.db.commit()
        return record

    def upsert_final_state_block(self, record: dict[str, Any]) -> dict[str, Any]:
        summary = record.get("summary") or record
        values = {
            "id": record["id"],
            "user_id": record["user_id"],
            "session_id": record["session_id"],
            "block_start_time": summary["block_start_time"],
            "block_end_time": summary["block_end_time"],
            "window_seconds": float(summary.get("window_seconds") or 0.0),
            "state": summary.get("state"),
            "matched_rule": summary.get("matched_rule") or "unknown",
            "ready": bool(summary.get("ready", False)),
            "confusion_ratio": float(summary.get("confusion_ratio") or 0.0),
            "stable_emotion_ratio": float(summary.get("stable_emotion_ratio") or 0.0),
            "engaged_ratio": float(summary.get("engaged_ratio") or 0.0),
            "low_engagement_ratio": float(summary.get("low_engagement_ratio") or 0.0),
            "drowsy_ratio": float(summary.get("drowsy_ratio") or 0.0),
            "emotion_confusion_count": int(summary.get("emotion_confusion_count") or 0),
            "emotion_stable_count": int(summary.get("emotion_stable_count") or 0),
            "engagement_high_count": int(summary.get("engagement_high_count") or 0),
            "engagement_medium_count": int(summary.get("engagement_medium_count") or 0),
            "engagement_low_count": int(summary.get("engagement_low_count") or 0),
            "sleepiness_alert_count": int(summary.get("sleepiness_alert_count") or 0),
            "sleepiness_drowsy_count": int(summary.get("sleepiness_drowsy_count") or 0),
            "dominant_emotion": summary.get("dominant_emotion"),
            "dominant_engagement": summary.get("dominant_engagement"),
            "dominant_sleepiness": summary.get("dominant_sleepiness"),
            "raw_summary_json": _json_dumps(summary),
            "created_at": record["created_at"],
        }
        existing = self.db.get(SmartDeskFinalStateBlockRecord, values["id"])
        if existing is None:
            self.db.add(SmartDeskFinalStateBlockRecord(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        self.db.commit()
        return record

    def upsert_reporting_block(self, record: dict[str, Any]) -> dict[str, Any]:
        summary = record.get("summary") or record
        values = {
            "id": record["id"],
            "user_id": record["user_id"],
            "session_id": record["session_id"],
            "block_start_time": summary["block_start_time"],
            "block_end_time": summary["block_end_time"],
            "window_seconds": float(summary.get("window_seconds") or 0.0),
            "final_state_block_count": int(summary.get("final_state_block_count") or 0),
            "focused_ratio": float(summary.get("focused_ratio") or 0.0),
            "struggling_ratio": float(summary.get("struggling_ratio") or 0.0),
            "disengaged_ratio": float(summary.get("disengaged_ratio") or 0.0),
            "fatigued_ratio": float(summary.get("fatigued_ratio") or 0.0),
            "overloaded_ratio": float(summary.get("overloaded_ratio") or 0.0),
            "dominant_state": summary.get("dominant_state"),
            "ready": bool(summary.get("ready", False)),
            "raw_summary_json": _json_dumps(summary),
            "created_at": record["created_at"],
        }
        existing = self.db.get(SmartDeskReportingBlockRecord, values["id"])
        if existing is None:
            self.db.add(SmartDeskReportingBlockRecord(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        self.db.commit()
        return record

    def latest_session(self, user_id: str) -> dict[str, Any] | None:
        row = (
            self.db.query(SmartDeskDetectionSessionRecord)
            .filter(SmartDeskDetectionSessionRecord.user_id == user_id)
            .order_by(SmartDeskDetectionSessionRecord.real_start_time.desc())
            .first()
        )
        return self._session_to_dict(row) if row else None

    def session_by_id(self, session_id: str) -> dict[str, Any] | None:
        row = self.db.get(SmartDeskDetectionSessionRecord, session_id)
        return self._session_to_dict(row) if row else None

    def signal_blocks_for_session(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(SmartDeskSignalBlockRecord).filter(
            SmartDeskSignalBlockRecord.session_id == session_id
        )
        if user_id:
            query = query.filter(SmartDeskSignalBlockRecord.user_id == user_id)
        rows = query.order_by(SmartDeskSignalBlockRecord.block_start_time).all()
        return [self._signal_block_to_dict(row) for row in rows]

    def final_state_blocks_between(self, user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._rows_between(
            SmartDeskFinalStateBlockRecord,
            user_id,
            start,
            end,
        )
        return [self._final_state_block_to_dict(row) for row in rows]

    def reporting_blocks_between(self, user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = self._rows_between(
            SmartDeskReportingBlockRecord,
            user_id,
            start,
            end,
        )
        return [self._reporting_block_to_dict(row) for row in rows]

    def final_state_blocks_for_session(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(SmartDeskFinalStateBlockRecord).filter(
            SmartDeskFinalStateBlockRecord.session_id == session_id
        )
        if user_id:
            query = query.filter(SmartDeskFinalStateBlockRecord.user_id == user_id)
        rows = query.order_by(SmartDeskFinalStateBlockRecord.block_start_time).all()
        return [self._final_state_block_to_dict(row) for row in rows]

    def reporting_blocks_for_session(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(SmartDeskReportingBlockRecord).filter(
            SmartDeskReportingBlockRecord.session_id == session_id
        )
        if user_id:
            query = query.filter(SmartDeskReportingBlockRecord.user_id == user_id)
        rows = query.order_by(SmartDeskReportingBlockRecord.block_start_time).all()
        return [self._reporting_block_to_dict(row) for row in rows]
    def _rows_between(self, model, user_id: str, start: datetime, end: datetime) -> list[Any]:
        rows = (
            self.db.query(model)
            .filter(
                model.user_id == user_id,
                model.block_start_time >= (start - _ZONE_PADDING).isoformat(),
                model.block_start_time <= (end + _ZONE_PADDING).isoformat(),
            )
            .order_by(model.block_start_time)
            .all()
        )

        filtered = []
        for row in rows:
            try:
                block_start = parse_iso(row.block_start_time)
            except (ValueError, TypeError):
                continue
            if start <= block_start <= end:
                filtered.append(row)
        return filtered

    @staticmethod
    def _session_to_dict(row: SmartDeskDetectionSessionRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "status": row.status,
            "program_start_time": row.program_start_time,
            "warmup_end_time": row.warmup_end_time,
            "real_start_time": row.real_start_time,
            "actual_camera_end_time": row.actual_camera_end_time,
            "usable_block_end_time": row.usable_block_end_time,
            "discarded_tail_seconds": row.discarded_tail_seconds,
            "startup_wait_seconds_after_warmup": row.startup_wait_seconds_after_warmup,
            "official_seconds_requested": row.official_seconds_requested,
            "sample_fps": row.sample_fps,
            "frames_read": row.frames_read,
            "samples_processed": row.samples_processed,
            "face_detected_samples": row.face_detected_samples,
            "completed_counts": _json_loads(row.completed_counts_json, {}),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _signal_block_to_dict(row: SmartDeskSignalBlockRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "block_type": row.block_type,
            "block_start_time": row.block_start_time,
            "block_end_time": row.block_end_time,
            "window_seconds": row.window_seconds,
            "total_time": row.total_time,
            "ready": row.ready,
            "summary": _json_loads(row.raw_summary_json, {}),
            "created_at": row.created_at,
        }

    @staticmethod
    def _final_state_block_to_dict(row: SmartDeskFinalStateBlockRecord) -> dict[str, Any]:
        data = _json_loads(row.raw_summary_json, {})
        data.update(
            {
                "id": row.id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "block_start_time": row.block_start_time,
                "block_end_time": row.block_end_time,
                "state": row.state,
                "ready": row.ready,
            }
        )
        return data

    @staticmethod
    def _reporting_block_to_dict(row: SmartDeskReportingBlockRecord) -> dict[str, Any]:
        data = _json_loads(row.raw_summary_json, {})
        data.update(
            {
                "id": row.id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "block_start_time": row.block_start_time,
                "block_end_time": row.block_end_time,
                "dominant_state": row.dominant_state,
                "ready": row.ready,
            }
        )
        return data


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default

