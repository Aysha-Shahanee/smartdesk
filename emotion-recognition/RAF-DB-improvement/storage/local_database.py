from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db.emotion import EmotionBlockRecord, EmotionSessionRecord


class LocalEmotionDatabase:
    """SQLite-backed storage for emotion sessions and completed blocks."""

    def upsert_session(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._session() as db:
            existing = db.get(EmotionSessionRecord, record["id"])
            values = {
                "id": record["id"],
                "user_id": record["user_id"],
                "session_number": record.get("session_number"),
                "started_at": record["started_at"],
                "ended_at": record.get("ended_at"),
                "status": record["status"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            }
            if existing is None:
                db.add(EmotionSessionRecord(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            db.commit()
        return record

    def upsert_block(self, record: dict[str, Any]) -> dict[str, Any]:
        scores = record.get("emotion_scores") or {}
        with self._session() as db:
            existing = db.get(EmotionBlockRecord, record["id"])
            values = {
                "id": record["id"],
                "user_id": record["user_id"],
                "session_id": record["session_id"],
                "session_start_time": record["session_start_time"],
                "block_start_time": record["block_start_time"],
                "block_end_time": record["block_end_time"],
                "block_type": record["block_type"],
                "duration_minutes": float(record["duration_minutes"]),
                "dominant_emotion": record["dominant_emotion"],
                "happy_score": float(scores.get("Happy", 0.0)),
                "neutral_score": float(scores.get("Neutral", 0.0)),
                "angry_score": float(scores.get("Angry", 0.0)),
                "surprise_score": float(scores.get("Surprise", 0.0)),
                "emotion_scores": json.dumps(scores, separators=(",", ":"), sort_keys=True),
                "processed_frame_count": int(record.get("processed_frame_count") or 0),
                "created_at": record["created_at"],
            }
            if existing is None:
                db.add(EmotionBlockRecord(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            db.commit()
        return record

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._session() as db:
            row = db.get(EmotionSessionRecord, session_id)
            return self._session_to_dict(row) if row else None

    def get_session_blocks(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._session() as db:
            query = db.query(EmotionBlockRecord).filter(EmotionBlockRecord.session_id == session_id)
            if user_id:
                query = query.filter(EmotionBlockRecord.user_id == user_id)
            rows = query.order_by(EmotionBlockRecord.block_start_time).all()
            return [self._block_to_dict(row) for row in rows]

    def get_latest_session(self, user_id: str) -> dict[str, Any] | None:
        with self._session() as db:
            row = (
                db.query(EmotionSessionRecord)
                .filter(EmotionSessionRecord.user_id == user_id)
                .order_by(EmotionSessionRecord.started_at.desc())
                .first()
            )
            return self._session_to_dict(row) if row else None

    def _session(self) -> Session:
        return SessionLocal()

    @staticmethod
    def _session_to_dict(row: EmotionSessionRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "session_number": row.session_number,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _block_to_dict(row: EmotionBlockRecord) -> dict[str, Any]:
        try:
            scores = json.loads(row.emotion_scores or "{}")
        except json.JSONDecodeError:
            scores = {}

        return {
            "id": row.id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "session_start_time": row.session_start_time,
            "block_start_time": row.block_start_time,
            "block_end_time": row.block_end_time,
            "block_type": row.block_type,
            "duration_minutes": row.duration_minutes,
            "dominant_emotion": row.dominant_emotion,
            "happy_score": row.happy_score,
            "neutral_score": row.neutral_score,
            "angry_score": row.angry_score,
            "surprise_score": row.surprise_score,
            "emotion_scores": scores,
            "processed_frame_count": row.processed_frame_count,
            "created_at": row.created_at,
        }
