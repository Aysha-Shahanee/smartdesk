from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.db_models import ActivitySessionSummaryRecord


class ActivitySessionSummaryRepository:
    def delete_overlapping(self, user_id: str, start_time: str, end_time: str) -> int:
        db = SessionLocal()
        try:
            deleted = (
                db.query(ActivitySessionSummaryRecord)
                .filter(
                    ActivitySessionSummaryRecord.user_id == user_id,
                    ActivitySessionSummaryRecord.session_start < end_time,
                    ActivitySessionSummaryRecord.session_end > start_time,
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
                db.query(ActivitySessionSummaryRecord)
                .filter(
                    and_(
                        ActivitySessionSummaryRecord.user_id == data["user_id"],
                        ActivitySessionSummaryRecord.session_start == data["session_start"],
                        ActivitySessionSummaryRecord.session_end == data["session_end"],
                    )
                )
                .one_or_none()
            )

            now_iso = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            if record:
                for key, value in data.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                record.updated_at = data.get("updated_at") or now_iso
                db.commit()
                return {"status": "updated", "collection": "activity_session_summary", "id": record.id}

            record = ActivitySessionSummaryRecord(
                **{k: v for k, v in data.items() if hasattr(ActivitySessionSummaryRecord, k)}
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "activity_session_summary", "id": record.id}
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
            query = db.query(ActivitySessionSummaryRecord)
            if user_id:
                query = query.filter(ActivitySessionSummaryRecord.user_id == user_id)
            if start_time:
                query = query.filter(ActivitySessionSummaryRecord.session_start >= start_time)
            if end_time:
                query = query.filter(ActivitySessionSummaryRecord.session_end <= end_time)
            query = query.order_by(ActivitySessionSummaryRecord.session_start.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            db.close()
