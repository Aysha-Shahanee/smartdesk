"""Work period scheduler — Phase 8.

Runs every 60 seconds in a background daemon thread.

Logic:
  - Query all three session tables for any activity in the last IDLE_GAP_SEC.
  - If activity found:
      · Ensure an open work_periods row exists for the current block.
      · Update source-availability flags (has_os_data, has_vscode_data, etc.).
  - If NO activity for IDLE_GAP_SEC:
      · Close the current open work period (if any).
      · The next period will be created automatically when activity resumes.

A "work period" is defined as a continuous stretch of activity with no gap
longer than IDLE_GAP_SEC (30 minutes by default).
"""

import logging
import threading
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy.orm import Session as DbSession

from app.core.database import SessionLocal
from app.models.db import BrowserSessionRecord
from app.models.db import CalendarEventRecord
from app.models.db import OSSessionRecord
from app.models.db import VSCodeSessionRecord
from app.repositories.work_period_repository import WorkPeriodRepository

logger = logging.getLogger("smartdesk.work_period_scheduler")

# How long a gap in activity (across all sources) triggers a period close.
IDLE_GAP_SEC: int = 30 * 60  # 30 minutes

# How often the scheduler wakes up.
SCHEDULER_INTERVAL_SEC: int = 60

_repo = WorkPeriodRepository()


def _has_activity_since(db: DbSession, user_id: str, since_iso: str) -> dict[str, bool]:
    """Check which data sources have session/event activity since ``since_iso``."""
    has_os = (
        db.query(OSSessionRecord)
        .filter(
            OSSessionRecord.user_id == user_id,
            OSSessionRecord.session_start >= since_iso,
        )
        .first()
        is not None
    )
    has_vscode = (
        db.query(VSCodeSessionRecord)
        .filter(
            VSCodeSessionRecord.user_id == user_id,
            VSCodeSessionRecord.session_start >= since_iso,
        )
        .first()
        is not None
    )
    has_browser = (
        db.query(BrowserSessionRecord)
        .filter(
            BrowserSessionRecord.user_id == user_id,
            BrowserSessionRecord.session_start >= since_iso,
        )
        .first()
        is not None
    )
    has_calendar = (
        db.query(CalendarEventRecord)
        .filter(
            CalendarEventRecord.user_id == user_id,
            CalendarEventRecord.start_time >= since_iso,
        )
        .first()
        is not None
    )
    return {
        "os": has_os,
        "vscode": has_vscode,
        "browser": has_browser,
        "calendar": has_calendar,
    }


def _primary_source(db: DbSession, user_id: str, since_iso: str) -> str | None:
    """Return whichever source contributed the most session duration."""
    totals: dict[str, int] = {}

    def _sum(Model, col_name: str) -> int:
        rows = (
            db.query(Model)
            .filter(
                Model.user_id == user_id,
                Model.session_start >= since_iso,
                Model.session_end.isnot(None),
            )
            .all()
        )
        return sum(getattr(r, col_name) or 0 for r in rows)

    totals["os"] = _sum(OSSessionRecord, "duration_sec")
    totals["vscode"] = _sum(VSCodeSessionRecord, "duration_sec")
    totals["browser"] = _sum(BrowserSessionRecord, "duration_sec")

    if not any(totals.values()):
        return None
    return max(totals, key=lambda k: totals[k])


def _seconds_between(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


# Default user_id used when no multi-user support is in place yet.
DEFAULT_USER_ID = "local_user"


class WorkPeriodScheduler:
    """Background job that groups sessions into logical work periods.

    Usage::

        scheduler = WorkPeriodScheduler()
        scheduler.start()   # call once at application startup
    """

    def __init__(self, user_id: str = DEFAULT_USER_ID) -> None:
        self._user_id = user_id
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            logger.warning("WorkPeriodScheduler already running — ignoring start().")
            return
        self._running = True
        logger.info(
            "WorkPeriodScheduler started (interval=%ds, idle_gap=%ds).",
            SCHEDULER_INTERVAL_SEC,
            IDLE_GAP_SEC,
        )
        self._schedule()

    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        logger.info("WorkPeriodScheduler stopped.")

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(SCHEDULER_INTERVAL_SEC, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-work-period-scheduler"
        self._timer.start()

    def _tick(self) -> None:
        try:
            self._process()
        except Exception:
            logger.exception("WorkPeriodScheduler encountered an error during tick.")
        finally:
            self._schedule()

    def _process(self) -> None:
        db: DbSession = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            since_dt = now - timedelta(seconds=IDLE_GAP_SEC)
            since_iso = since_dt.isoformat()

            activity = _has_activity_since(db, self._user_id, since_iso)
            any_activity = any(activity.values())

            open_period = _repo.get_open_period_db(db, self._user_id)

            if any_activity:
                if open_period is None:
                    # Start a new work period
                    open_period = _repo.open_period_db(
                        db,
                        user_id=self._user_id,
                        period_start=now_iso,
                        now_iso=now_iso,
                    )
                    logger.info("WorkPeriodScheduler opened new work period %s.", open_period.id)

                # Refresh source flags
                primary = _primary_source(db, self._user_id, open_period.period_start)
                _repo.update_flags_db(
                    db,
                    period=open_period,
                    has_os=activity["os"],
                    has_vscode=activity["vscode"],
                    has_browser=activity["browser"],
                    has_calendar=activity["calendar"],
                    primary_source=primary,
                    now_iso=now_iso,
                )
            else:
                # No activity in the last IDLE_GAP_SEC — close the open period
                if open_period is not None:
                    duration = _seconds_between(open_period.period_start, now_iso)
                    _repo.close_period_db(
                        db,
                        period=open_period,
                        period_end=now_iso,
                        duration_sec=duration,
                        now_iso=now_iso,
                    )
                    logger.info(
                        "WorkPeriodScheduler closed work period %s (%ds).",
                        open_period.id,
                        duration,
                    )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Manual trigger                                                       #
    # ------------------------------------------------------------------ #

    def run_once(self) -> str:
        """Process one scheduler cycle immediately (for testing / debug routes)."""
        self._process()
        return "ok"
