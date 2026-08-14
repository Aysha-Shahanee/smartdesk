"""Calendar auto-sync job.

Runs every CALENDAR_SYNC_INTERVAL_MIN minutes (15 by default) in a
background daemon thread. Skips silently while the user has not connected
Google Calendar yet — the dashboard Sync button / connect flow handles the
first sync.
"""

import logging
import threading

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.calendar_service import CalendarService

logger = logging.getLogger("smartdesk.calendar_sync_job")


class CalendarSyncJob:
    def __init__(self, user_id: str | None = None) -> None:
        self._user_id = user_id or settings.DEFAULT_USER_ID
        self._service = CalendarService()
        self._timer: threading.Timer | None = None
        self._running = False
        self._interval_sec = max(60, settings.CALENDAR_SYNC_INTERVAL_MIN * 60)

    def start(self) -> None:
        if self._running:
            logger.warning("CalendarSyncJob already running — ignoring start().")
            return
        self._running = True
        logger.info("CalendarSyncJob started (interval=%ds).", self._interval_sec)
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
        self._timer = threading.Timer(self._interval_sec, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-calendar-sync"
        self._timer.start()

    def _tick(self) -> None:
        try:
            self.run_once()
        except Exception:
            logger.exception("CalendarSyncJob encountered an error during tick.")
        finally:
            self._schedule()

    def run_once(self) -> None:
        if not (self._service.is_configured() and self._service.is_connected(self._user_id)):
            logger.debug("Calendar not connected — skipping auto-sync.")
            return
        db = SessionLocal()
        try:
            stats = self._service.sync(self._user_id, db)
            logger.info("Calendar auto-sync done: %s", stats)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
