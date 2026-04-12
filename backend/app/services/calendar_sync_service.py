import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.google_calendar_client import get_calendar_data
from app.models.calendar import CalendarPayload
from app.repositories.calendar_repository import CalendarRepository


class CalendarSyncTask:
    """Background task that periodically pulls Google Calendar events and
    stores them in the local database using the existing repository layer.
    """

    def __init__(self, interval_minutes: int = 15):
        self.interval_minutes = interval_minutes
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._repository = CalendarRepository()

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
            except Exception as exc:  # defensive logging; don't crash the loop
                print(f"[Calendar Collector] Error during sync: {exc}")

            # Wait for the next interval, but allow early exit
            wait_seconds = max(60, self.interval_minutes * 60)
            for _ in range(int(wait_seconds)):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _collect_and_save(self) -> None:
        events: List[Dict[str, Any]] = get_calendar_data()
        collected_at = datetime.now(timezone.utc)

        for ev in events:
            payload = CalendarPayload(
                timestamp=collected_at,
                event_type="calendar_event",
                data=ev,
            )
            try:
                self._repository.save(payload)
            except Exception as exc:
                print(f"[Calendar Collector] Failed to save event {ev.get('event_id')}: {exc}")
            else:
                print(f"[Calendar Collector] Event stored: {ev.get('event_id')}")


calendar_sync = CalendarSyncTask()
