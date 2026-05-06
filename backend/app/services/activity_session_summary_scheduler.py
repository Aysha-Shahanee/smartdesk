import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services.activity_session_summary_service import ActivityTimelineService

logger = logging.getLogger("smartdesk.scheduler.timeline")


def _server_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _latest_window(now: datetime) -> tuple[str, str]:
    """Get the latest window boundary as ISO strings."""
    window_end = now.replace(second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=settings.SESSION_SCHEDULER_WINDOW_MINUTES)
    return (
        window_start.replace(microsecond=0).isoformat(),
        window_end.replace(microsecond=0).isoformat(),
    )


class ActivityTimelineScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._service = ActivityTimelineService()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Activity Timeline Scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("Activity Timeline Scheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._build_latest_window()
            except Exception as exc:
                logger.error("Error building timeline: %s", exc)

            for _ in range(settings.SESSION_SCHEDULER_INTERVAL_SEC):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _build_latest_window(self) -> None:
        now = datetime.now(timezone.utc).astimezone()
        start_iso, end_iso = _latest_window(now)
        logger.debug("Building timeline %s to %s", start_iso, end_iso)
        self._service.build(settings.DEFAULT_USER_ID, start_iso, end_iso)


activity_session_scheduler = ActivityTimelineScheduler()
