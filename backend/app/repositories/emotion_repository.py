"""Read recorded emotion blocks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import parse_iso
from app.models.db.emotion import EmotionBlockRecord


# Block times are ISO strings carrying their own offset, so a lexicographic
# comparison is only exact when two rows share an offset. Widen the SQL window
# by more than any real offset spread and make the precise comparison in Python
# — same shape as the segment window in github_task_time_spent_service.
_ZONE_PADDING = timedelta(hours=30)


class EmotionRepository:
    def __init__(self, db: Session):
        self.db = db

    def blocks_between(
        self, user_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        rows = (
            self.db.query(EmotionBlockRecord)
            .filter(
                EmotionBlockRecord.user_id == user_id,
                EmotionBlockRecord.block_start_time >= (start - _ZONE_PADDING).isoformat(),
                EmotionBlockRecord.block_start_time <= (end + _ZONE_PADDING).isoformat(),
            )
            .order_by(EmotionBlockRecord.block_start_time)
            .all()
        )

        blocks: list[dict] = []
        for row in rows:
            try:
                block_start = parse_iso(row.block_start_time)
            except (ValueError, TypeError):
                continue
            if block_start < start or block_start > end:
                continue
            blocks.append(self._to_dict(row))
        return blocks

    @staticmethod
    def _to_dict(row: EmotionBlockRecord) -> dict:
        try:
            scores = json.loads(row.emotion_scores or "{}")
        except json.JSONDecodeError:
            scores = {}

        return {
            "id": row.id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "block_start_time": row.block_start_time,
            "block_end_time": row.block_end_time,
            "block_type": row.block_type,
            "duration_minutes": row.duration_minutes,
            "dominant_emotion": row.dominant_emotion,
            "emotion_scores": scores,
            "processed_frame_count": row.processed_frame_count,
        }
