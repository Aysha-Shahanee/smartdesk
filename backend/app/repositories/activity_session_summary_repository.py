import logging
from datetime import datetime, timezone

from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.db_models import ActivityTimelineIndex

logger = logging.getLogger("smartdesk.repo.timeline")


def _server_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class ActivityTimelineRepository:
    def delete_overlapping(self, user_id: str, start_time: str, end_time: str) -> int:
        db = SessionLocal()
        try:
            deleted = (
                db.query(ActivityTimelineIndex)
                .filter(
                    ActivityTimelineIndex.user_id == user_id,
                    ActivityTimelineIndex.window_start < end_time,
                    ActivityTimelineIndex.window_end > start_time,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted
        finally:
            db.close()

    def upsert(self, data: dict):
        db = SessionLocal()
        try:
            record = (
                db.query(ActivityTimelineIndex)
                .filter(
                    and_(
                        ActivityTimelineIndex.user_id == data["user_id"],
                        ActivityTimelineIndex.window_start == data["window_start"],
                        ActivityTimelineIndex.window_end == data["window_end"],
                    )
                )
                .one_or_none()
            )

            if record:
                for key, value in data.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                db.commit()
                return {"status": "updated", "collection": "activity_timeline_index", "id": record.id}

            record = ActivityTimelineIndex(
                **{k: v for k, v in data.items() if hasattr(ActivityTimelineIndex, k)}
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "activity_timeline_index", "id": record.id}
        finally:
            db.close()

    def list(
        self,
        user_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 200,
    ):
        db = SessionLocal()
        try:
            query = db.query(ActivityTimelineIndex)
            if user_id:
                query = query.filter(ActivityTimelineIndex.user_id == user_id)
            if start_time:
                query = query.filter(ActivityTimelineIndex.window_start >= start_time)
            if end_time:
                query = query.filter(ActivityTimelineIndex.window_end <= end_time)
            query = query.order_by(ActivityTimelineIndex.window_start.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            db.close()
