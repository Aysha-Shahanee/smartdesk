import logging
import threading
from datetime import datetime
from datetime import timezone

from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.calendar_sync_service import CalendarSyncService

logger = logging.getLogger("smartdesk.calendar_sync_job")

SYNC_INTERVAL_SEC = 10 * 60
DAILY_FUTURE_DAYS = 30
FREQUENT_FUTURE_DAYS = 1


class CalendarSyncJob:
    def __init__(self, service: CalendarSyncService) -> None:
        self._service = service
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            logger.warning("CalendarSyncJob already running — ignoring start().")
            return
        self._running = True
        logger.info("CalendarSyncJob started (interval=%ds).", SYNC_INTERVAL_SEC)
        self._schedule()

    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("CalendarSyncJob stopped.")

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(SYNC_INTERVAL_SEC, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-calendar-sync"
        self._timer.start()

    def _tick(self) -> None:
        try:
            self._run_once()
        except Exception:
            logger.exception("CalendarSyncJob encountered an error during tick.")
        finally:
            self._schedule()

    def _run_once(self) -> None:
        db: DbSession = SessionLocal()
        try:
            self._run_daily_wide_sync(db)
            result = self._service.sync(
                db,
                settings.DEFAULT_USER_ID,
                future_days=FREQUENT_FUTURE_DAYS,
            )
            logger.info(
                "CalendarSyncJob synced %d event(s) at %s.",
                result.get("upserted", 0),
                datetime.now(timezone.utc).isoformat(),
            )
        except ValueError as exc:
            logger.warning("Calendar sync skipped: %s", exc)
        finally:
            db.close()

    def _run_daily_wide_sync(self, db: DbSession) -> None:
        sync_state = self._service._load_sync_state().get(settings.DEFAULT_USER_ID, {})
        today = datetime.now(timezone.utc).date().isoformat()
        if sync_state.get("last_full_sync") == today:
            return

        result = self._service.sync(
            db,
            settings.DEFAULT_USER_ID,
            future_days=DAILY_FUTURE_DAYS,
        )
        sync_state["last_full_sync"] = today
        self._service._save_sync_state(settings.DEFAULT_USER_ID, sync_state)
        logger.info(
            "CalendarSyncJob daily wide sync upserted %d event(s) for next %d days.",
            result.get("upserted", 0),
            DAILY_FUTURE_DAYS,
        )
