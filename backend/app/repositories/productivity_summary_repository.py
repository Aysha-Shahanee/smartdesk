from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.db_models import ProductivitySummary10MinRecord


class ProductivitySummaryRepository:
    def upsert(self, data: dict):
        db = SessionLocal()
        try:
            record = (
                db.query(ProductivitySummary10MinRecord)
                .filter(
                    and_(
                        ProductivitySummary10MinRecord.user_id == data["user_id"],
                        ProductivitySummary10MinRecord.window_start == data["window_start"],
                        ProductivitySummary10MinRecord.window_end == data["window_end"],
                    )
                )
                .one_or_none()
            )

            now_iso = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            if record:
                for key, value in data.items():
                    setattr(record, key, value)
                record.updated_at = now_iso
                db.commit()
                return {"status": "updated", "collection": "productivity_summary_10min", "id": record.id}

            record = ProductivitySummary10MinRecord(**data)
            record.created_at = data.get("created_at") or now_iso
            record.updated_at = data.get("updated_at") or now_iso
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "productivity_summary_10min", "id": record.id}
        finally:
            db.close()

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100):
        db = SessionLocal()
        try:
            query = db.query(ProductivitySummary10MinRecord)
            if user_id:
                query = query.filter(ProductivitySummary10MinRecord.user_id == user_id)
            if start_time:
                query = query.filter(ProductivitySummary10MinRecord.window_start >= start_time)
            if end_time:
                query = query.filter(ProductivitySummary10MinRecord.window_end <= end_time)
            query = query.order_by(ProductivitySummary10MinRecord.window_start.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            db.close()
