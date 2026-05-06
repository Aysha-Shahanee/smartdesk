import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.config import settings
from app.core.google_calendar_client import get_calendar_data
from app.models.calendar_event import CalendarEventPayload
from app.services.calendar_event_service import CalendarEventService

logger = logging.getLogger("smartdesk.collector.calendar")


def _server_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


class CalendarSyncTask:
    """Background task that periodically pulls Google Calendar events and
    stores them in the calendar_events table using the structured schema.
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._event_service = CalendarEventService()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._collect_and_save()
            except Exception as exc:
                logger.error("Error during calendar sync: %s", exc)

            wait_seconds = max(60, settings.CALENDAR_SYNC_INTERVAL_SEC)
            for _ in range(int(wait_seconds)):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _collect_and_save(self) -> None:
        events: List[Dict[str, Any]] = get_calendar_data()
        now_iso = _server_timestamp()

        for ev in events:
            event_id = ev.get("event_id")
            if not event_id:
                continue

            payload = CalendarEventPayload(
                user_id=settings.DEFAULT_USER_ID,
                event_id=str(event_id),
                title=ev.get("title"),
                start_time=ev.get("start_time"),
                end_time=ev.get("end_time"),
                timezone=ev.get("timezone"),
                attendees_count=ev.get("attendees_count"),
                is_recurring=bool(ev.get("is_recurring")),
                source="google_calendar",
            )
            try:
                self._event_service.process_and_save(payload)
            except Exception as exc:
                logger.error("Failed to save event %s: %s", event_id, exc)
            else:
                logger.debug("Event stored: %s", event_id)


calendar_sync = CalendarSyncTask()
