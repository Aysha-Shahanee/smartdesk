import logging
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db_models import OSMinuteWindowRecord
from app.models.os_minute_window import OSMinuteWindowPayload

logger = logging.getLogger("smartdesk.repo.os")


def _server_timestamp() -> str:
    """Generate a server-side timestamp in ISO format with timezone."""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class OSMinuteWindowRepository:
    def __init__(self, db: Session | None = None):
        self.db = db
        self._owns_session = db is None

    def upsert(self, payload: OSMinuteWindowPayload):
        db = self.db or SessionLocal()
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

            now_iso = _server_timestamp()

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
                record.extra_data = payload.extra_data
                record.source = payload.source or "os_collector"
                record.schema_version = payload.schema_version
                # Always set updated_at server-side
                record.updated_at = now_iso
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
                extra_data=payload.extra_data,
                source=payload.source or "os_collector",
                schema_version=payload.schema_version,
                # Always set timestamps server-side
                created_at=now_iso,
                updated_at=now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "os_minute_windows", "id": record.id}
        finally:
            if self._owns_session:
                db.close()

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100):
        db = self.db or SessionLocal()
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
            if self._owns_session:
                db.close()
