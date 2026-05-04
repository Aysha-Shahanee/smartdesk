import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from app.core.google_calendar_client import get_calendar_data
from app.models.calendar_event import CalendarEventPayload
from app.services.calendar_event_service import CalendarEventService


COLOMBO_TZ = ZoneInfo("Asia/Colombo")


class CalendarSyncTask:
    """Background task that periodically pulls Google Calendar events and
    stores them in the calendar_events table using the structured schema.
    """

    def __init__(self, interval_minutes: int = 15):
        self.interval_minutes = interval_minutes
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._event_service = CalendarEventService()
        self._user_id = os.getenv("USER_ID", "demo_user")

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
        collected_at = datetime.now(COLOMBO_TZ)
        now_iso = collected_at.replace(microsecond=0).isoformat()

        for ev in events:
            event_id = ev.get("event_id")
            if not event_id:
                continue

            payload = CalendarEventPayload(
                user_id=self._user_id,
                event_id=str(event_id),
                title=ev.get("title"),
                start_time=ev.get("start_time"),
                end_time=ev.get("end_time"),
                timezone=ev.get("timezone") or "Asia/Colombo",
                attendees_count=ev.get("attendees_count"),
                is_recurring=bool(ev.get("is_recurring")),
                source="google_calendar",
                schema_version="1.0",
                created_at=now_iso,
                updated_at=now_iso,
            )
            try:
                self._event_service.process_and_save(payload)
            except Exception as exc:
                print(f"[Calendar Collector] Failed to save event {event_id}: {exc}")
            else:
                print(f"[Calendar Collector] Event stored: {event_id}")


calendar_sync = CalendarSyncTask()
