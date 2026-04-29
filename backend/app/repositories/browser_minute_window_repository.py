from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_
from app.core.database import SessionLocal
from app.models.db_models import BrowserMinuteWindowRecord
from app.models.browser_minute_window import BrowserMinuteWindowPayload


class BrowserMinuteWindowRepository:
    def __init__(self, db=None):
        self.db = db
        self._owns_session = db is None

    def upsert(self, payload: BrowserMinuteWindowPayload):
        db = self.db or SessionLocal()
        try:
            record = (
                db.query(BrowserMinuteWindowRecord)
                .filter(
                    and_(
                        BrowserMinuteWindowRecord.user_id == payload.user_id,
                        BrowserMinuteWindowRecord.window_start == payload.window_start,
                        BrowserMinuteWindowRecord.window_end == payload.window_end,
                    )
                )
                .one_or_none()
            )

            if record:
                record.timezone = payload.timezone
                record.browser_name = payload.browser_name
                record.active_tab_domain = payload.active_tab_domain
                record.active_tab_url = payload.active_tab_url
                record.active_tab_title = payload.active_tab_title
                record.active_tab_category = payload.active_tab_category
                record.browser_active_time_sec = payload.browser_active_time_sec
                record.browser_idle_time_sec = payload.browser_idle_time_sec
                record.productive_time_sec = payload.productive_time_sec
                record.neutral_time_sec = payload.neutral_time_sec
                record.distracting_time_sec = payload.distracting_time_sec
                record.communication_time_sec = payload.communication_time_sec
                record.tab_switch_count = payload.tab_switch_count
                record.unique_domains_count = payload.unique_domains_count
                record.source = payload.source
                record.schema_version = payload.schema_version
                record.updated_at = datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()
                db.commit()
                return {"status": "updated", "collection": "browser_minute_windows", "id": record.id}

            created_at = payload.created_at or datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()
            updated_at = payload.updated_at or datetime.now(ZoneInfo("Asia/Colombo")).replace(microsecond=0).isoformat()

            record = BrowserMinuteWindowRecord(
                user_id=payload.user_id,
                window_start=payload.window_start,
                window_end=payload.window_end,
                timezone=payload.timezone,
                browser_name=payload.browser_name,
                active_tab_domain=payload.active_tab_domain,
                active_tab_url=payload.active_tab_url,
                active_tab_title=payload.active_tab_title,
                active_tab_category=payload.active_tab_category,
                browser_active_time_sec=payload.browser_active_time_sec,
                browser_idle_time_sec=payload.browser_idle_time_sec,
                productive_time_sec=payload.productive_time_sec,
                neutral_time_sec=payload.neutral_time_sec,
                distracting_time_sec=payload.distracting_time_sec,
                communication_time_sec=payload.communication_time_sec,
                tab_switch_count=payload.tab_switch_count,
                unique_domains_count=payload.unique_domains_count,
                source=payload.source,
                schema_version=payload.schema_version,
                created_at=created_at,
                updated_at=updated_at,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "browser_minute_windows", "id": record.id}
        finally:
            if self._owns_session:
                db.close()
