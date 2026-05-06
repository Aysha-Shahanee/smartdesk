import logging
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.db_models import BrowserMinuteWindowRecord
from app.models.browser_minute_window import BrowserMinuteWindowPayload

logger = logging.getLogger("smartdesk.repo.browser")


def _server_timestamp() -> str:
    """Generate a server-side timestamp in ISO format with timezone."""
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class BrowserMinuteWindowRepository:
    def __init__(self, db: Session | None = None):
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

            now_iso = _server_timestamp()

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
                record.extra_data = payload.extra_data
                record.source = payload.source or "browser_extension"
                record.schema_version = payload.schema_version
                # Always set updated_at server-side
                record.updated_at = now_iso
                db.commit()
                return {"status": "updated", "collection": "browser_minute_windows", "id": record.id}

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
                extra_data=payload.extra_data,
                source=payload.source or "browser_extension",
                schema_version=payload.schema_version,
                # Always set timestamps server-side
                created_at=now_iso,
                updated_at=now_iso,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return {"status": "inserted", "collection": "browser_minute_windows", "id": record.id}
        finally:
            if self._owns_session:
                db.close()
