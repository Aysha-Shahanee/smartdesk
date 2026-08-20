"""Calendar auto-sync job.

Runs every CALENDAR_SYNC_INTERVAL_MIN minutes (15 by default) in a background
daemon thread and keeps Google Calendar events flowing into calendar_events.

Why this is a loop thread rather than a chain of threading.Timer objects
----------------------------------------------------------------------
The previous version scheduled the next tick from inside the current one. That
makes the schedule only as durable as the last tick: any path that skipped
``_schedule()`` ended collection permanently, with nothing in the logs above
DEBUG to say so. A single long-lived thread parked on ``Event.wait(timeout)``
cannot lose its own chain, and the watchdog below restarts it if the thread dies
for any reason at all.

Failure handling
----------------
* transient (network, 5xx, token-endpoint blips) - retry with exponential
  backoff, keep the token, keep the connection.
* fatal (refresh token revoked or expired) - flag ``needs_reconnect`` in the
  service connection state so Settings can show a Reconnect button, then keep
  polling cheaply so collection resumes by itself once the user reconnects.
"""

import logging
import threading

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.calendar_service import CalendarNotConfiguredError
from app.services.calendar_service import CalendarNotConnectedError
from app.services.calendar_service import CalendarService
from app.services.calendar_service import CalendarSyncTransientError

logger = logging.getLogger("smartdesk.calendar_sync_job")

#: Wait before the first sync so startup is not competing with it, but do not
#: wait a full interval - a restart used to mean up to 15 minutes of no calendar.
FIRST_RUN_DELAY_SEC = 20

#: Backoff bounds for transient failures.
MIN_BACKOFF_SEC = 60
MAX_BACKOFF_SEC = 30 * 60

#: How often to re-check while disconnected / awaiting reconnect. Cheap (a file
#: existence check), and it means reconnecting in the UI resumes collection
#: within a minute instead of at the next full interval.
IDLE_POLL_SEC = 60

#: Only log the "not connected" line once every this many idle polls, so a
#: deliberately disconnected calendar does not flood the log - but never goes
#: completely silent either, which is how the last outage went unnoticed.
IDLE_LOG_EVERY = 30

#: How often the watchdog checks that the worker thread is still alive.
WATCHDOG_SEC = 120


class CalendarSyncJob:
    def __init__(self, user_id: str | None = None) -> None:
        self._user_id = user_id or settings.DEFAULT_USER_ID
        self._service = CalendarService()
        self._interval_sec = max(60, settings.CALENDAR_SYNC_INTERVAL_MIN * 60)

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._lock = threading.Lock()

        self._backoff_sec = 0
        self._idle_polls = 0
        self._last_result: str = "not started"

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("CalendarSyncJob already running - ignoring start().")
                return
            self._stop.clear()
            self._spawn_worker()
            if self._watchdog is None or not self._watchdog.is_alive():
                self._watchdog = threading.Thread(
                    target=self._watch, name="smartdesk-calendar-watchdog", daemon=True
                )
                self._watchdog.start()
        logger.info(
            "CalendarSyncJob started (interval=%ds, first run in %ds).",
            self._interval_sec,
            FIRST_RUN_DELAY_SEC,
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        logger.info("CalendarSyncJob stopped.")

    def sync_now(self) -> None:
        """Ask the loop to run immediately - used right after a reconnect."""
        self._backoff_sec = 0
        self._wake.set()

    def status(self) -> dict:
        thread = self._thread
        return {
            "running": bool(thread and thread.is_alive()),
            "interval_sec": self._interval_sec,
            "backoff_sec": self._backoff_sec,
            "last_result": self._last_result,
        }

    def _spawn_worker(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="smartdesk-calendar-sync", daemon=True
        )
        self._thread.start()

    def _watch(self) -> None:
        """Restart the worker if it ever dies.

        Nothing should kill it - ``_run`` catches everything - but a job whose
        whole purpose is "do not stop collecting" should not depend on that
        staying true forever.
        """
        while not self._stop.wait(WATCHDOG_SEC):
            with self._lock:
                if self._stop.is_set():
                    return
                thread = self._thread
                if thread is None or not thread.is_alive():
                    logger.error("Calendar sync thread was not alive - restarting it.")
                    self._spawn_worker()

    # ------------------------------------------------------------------ #
    # Loop                                                                 #
    # ------------------------------------------------------------------ #

    def _run(self) -> None:
        delay: float = FIRST_RUN_DELAY_SEC
        while not self._stop.is_set():
            # wait() returns True when woken early by sync_now(); either way the
            # loop proceeds to a tick, which is exactly what we want.
            self._wake.wait(timeout=delay)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                delay = self._tick()
            except Exception:
                # A bug in the tick must not take the schedule down with it.
                logger.exception("CalendarSyncJob tick raised; retrying later.")
                delay = self._interval_sec

    def _tick(self) -> int:
        """Run one sync attempt. Returns the seconds to wait before the next."""
        if not self._service.is_configured():
            self._note_idle(
                "Google Calendar is not configured (no client id/secret and no "
                "credentials.json) - auto-sync idle."
            )
            return IDLE_POLL_SEC

        if not self._service.is_connected(self._user_id):
            self._note_idle(
                "Google Calendar is not connected - auto-sync idle until it is "
                "connected from Settings."
            )
            return IDLE_POLL_SEC

        if self._service.needs_reconnect(self._user_id):
            self._note_idle(
                "Google Calendar access expired - auto-sync idle until it is "
                "reconnected from Settings."
            )
            return IDLE_POLL_SEC

        self._idle_polls = 0
        db = SessionLocal()
        try:
            stats = self._service.sync(self._user_id, db)
            self._backoff_sec = 0
            self._last_result = f"ok: {stats}"
            logger.info("Calendar auto-sync done: %s", stats)
            return self._interval_sec
        except CalendarSyncTransientError as exc:
            db.rollback()
            self._backoff_sec = (
                MIN_BACKOFF_SEC
                if not self._backoff_sec
                else min(self._backoff_sec * 2, MAX_BACKOFF_SEC)
            )
            self._last_result = f"transient: {exc}"
            logger.warning(
                "Calendar auto-sync failed (%s) - retrying in %ds.",
                exc,
                self._backoff_sec,
            )
            return self._backoff_sec
        except (CalendarNotConnectedError, CalendarNotConfiguredError) as exc:
            db.rollback()
            self._last_result = f"needs attention: {exc}"
            logger.warning("Calendar auto-sync cannot proceed: %s", exc)
            return IDLE_POLL_SEC
        except Exception as exc:
            db.rollback()
            self._last_result = f"error: {exc}"
            logger.exception("CalendarSyncJob encountered an error during tick.")
            return self._interval_sec
        finally:
            db.close()

    def _note_idle(self, message: str) -> None:
        """Log an idle reason, throttled but never silent."""
        if self._idle_polls % IDLE_LOG_EVERY == 0:
            logger.info(message)
        self._idle_polls += 1
        self._last_result = message
