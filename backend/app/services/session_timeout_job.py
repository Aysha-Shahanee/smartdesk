"""Session timeout job — Phase 7.

Runs every 60 seconds in a background daemon thread.
Closes sessions that are clearly abandoned/broken (i.e. the normal
close event never arrived due to a crash, sleep, or hard shutdown).

Only sessions that have been open for longer than BROKEN_SESSION_TIMEOUT_SEC
WITHOUT any update are treated as stale.  Normal sessions update their
``updated_at`` timestamp on every state change, so they are never touched.
"""

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.core.database import SessionLocal
from app.core.time import ensure_aware
from app.core.time import local_now
from app.models.db import BrowserSessionRecord
from app.models.db import OSSessionRecord
from app.models.db import VSCodeSessionRecord

logger = logging.getLogger("smartdesk.timeout_job")

# A session must be open AND have had no ``updated_at`` activity for this long
# before the safety net will close it.
BROKEN_SESSION_TIMEOUT_SEC: int = 30 * 60  # 30 minutes

# How often the background thread wakes up to check.
JOB_INTERVAL_SEC: int = 60


def _seconds_between(start: datetime, end: datetime) -> int:
    """Return the whole-second difference between two datetime objects."""
    return max(0, int((ensure_aware(end) - ensure_aware(start)).total_seconds()))


class SessionTimeoutJob:
    """Background safety-net: closes abandoned/broken open sessions.

    Usage::

        job = SessionTimeoutJob()
        job.start()   # call once at application startup

    The job stops automatically when the process exits because the timer
    thread is a daemon thread.
    """

    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Start the recurring background timer."""
        if self._running:
            logger.warning("SessionTimeoutJob already running — ignoring start().")
            return
        self._running = True
        logger.info(
            "SessionTimeoutJob started (interval=%ds, timeout=%ds).",
            JOB_INTERVAL_SEC,
            BROKEN_SESSION_TIMEOUT_SEC,
        )
        self._schedule()

    def stop(self) -> None:
        """Cancel the next scheduled run (best-effort, does not interrupt a running cycle)."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("SessionTimeoutJob stopped.")

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(JOB_INTERVAL_SEC, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-timeout-job"
        self._timer.start()

    def _tick(self) -> None:
        """One cycle: close stale sessions, then reschedule."""
        try:
            self._close_stale_sessions()
        except Exception:
            logger.exception("SessionTimeoutJob encountered an error during tick.")
        finally:
            self._schedule()

    def _close_stale_sessions(self) -> None:
        db: DbSession = SessionLocal()
        try:
            now = local_now()
            threshold_dt = now - timedelta(seconds=BROKEN_SESSION_TIMEOUT_SEC)

            total_closed = 0
            for Model in (OSSessionRecord, VSCodeSessionRecord, BrowserSessionRecord):
                open_rows = db.query(Model).filter(Model.session_end.is_(None)).all()
                stale_rows = [
                    row for row in open_rows if ensure_aware(row.updated_at) < threshold_dt
                ]
                for row in stale_rows:
                    row.session_end = now
                    row.duration_sec = _seconds_between(row.session_start, now)
                    row.closed_by = "timeout"
                    row.updated_at = now
                    total_closed += 1

            if total_closed:
                db.commit()
                logger.info("SessionTimeoutJob closed %d stale session(s).", total_closed)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Manual trigger (useful for testing without waiting for the interval) #
    # ------------------------------------------------------------------ #

    def run_once(self) -> int:
        """Close stale sessions immediately and return the count closed.

        Call this from a test or a debug endpoint — no background thread needed.
        """
        db: DbSession = SessionLocal()
        now = local_now()
        threshold_dt = now - timedelta(seconds=BROKEN_SESSION_TIMEOUT_SEC)

        total_closed = 0
        try:
            for Model in (OSSessionRecord, VSCodeSessionRecord, BrowserSessionRecord):
                open_rows = db.query(Model).filter(Model.session_end.is_(None)).all()
                stale_rows = [
                    row for row in open_rows if ensure_aware(row.updated_at) < threshold_dt
                ]
                for row in stale_rows:
                    row.session_end = now
                    row.duration_sec = _seconds_between(row.session_start, now)
                    row.closed_by = "timeout"
                    row.updated_at = now
                    total_closed += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        return total_closed
