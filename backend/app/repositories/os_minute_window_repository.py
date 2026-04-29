from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.db_models import OSMinuteWindowRecord
from app.models.os_minute_window import OSMinuteWindowPayload


class OSMinuteWindowRepository:
    def upsert(self, payload: OSMinuteWindowPayload):
        db = SessionLocal()
        try:
            record = (
                db.query(OSMinuteWindowRecord)
                .filter(
                    and_(
                        OSMinuteWindowRecord.user_id == payload.user_id,
                        OSMinuteWindowRecord.window_start == payload.window_start,
                        OSMinuteWindowRecord.window_end == payload.window_end,
                    )
                )
                .one_or_none()
            )

            now_iso = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            if record:
                record.active_time_sec = payload.active_time_sec
                record.idle_time_sec = payload.idle_time_sec
                record.locked_time_sec = payload.locked_time_sec
                record.context_switch_count = payload.context_switch_count
                record.top_app = payload.top_app
                record.top_app_sec = payload.top_app_sec
                record.dominant_app_category = payload.dominant_app_category
                record.dominant_app_category_sec = payload.dominant_app_category_sec
                record.active_app_durations_json = payload.active_app_durations_json
                record.category_durations_json = payload.category_durations_json
                record.source = payload.source
                record.schema_version = payload.schema_version
                record.updated_at = payload.updated_at or now_iso
                db.commit()
                return {"status": "updated", "collection": "os_minute_windows", "id": record.id}

            record = OSMinuteWindowRecord(
                user_id=payload.user_id,
                window_start=payload.window_start,
                window_end=payload.window_end,
                timezone=payload.timezone,
                active_time_sec=payload.active_time_sec,
                idle_time_sec=payload.idle_time_sec,
                locked_time_sec=payload.locked_time_sec,
                context_switch_count=payload.context_switch_count,
                top_app=payload.top_app,
                top_app_sec=payload.top_app_sec,
                dominant_app_category=payload.dominant_app_category,
                dominant_app_category_sec=payload.dominant_app_category_sec,
                active_app_durations_json=payload.active_app_durations_json,
                category_durations_json=payload.category_durations_json,
                source=payload.source,
                schema_version=payload.schema_version,
                created_at=payload.created_at or now_iso,
                updated_at=payload.updated_at or now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "os_minute_windows", "id": record.id}
        finally:
            db.close()

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100):
        db = SessionLocal()
        try:
            query = db.query(OSMinuteWindowRecord)
            if user_id:
                query = query.filter(OSMinuteWindowRecord.user_id == user_id)
            if start_time:
                query = query.filter(OSMinuteWindowRecord.window_start >= start_time)
            if end_time:
                query = query.filter(OSMinuteWindowRecord.window_end <= end_time)
            query = query.order_by(OSMinuteWindowRecord.window_start.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        finally:
            db.close()
