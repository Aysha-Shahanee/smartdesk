import json
import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.repositories.calendar_event_repository import CalendarEventRepository
from app.services.calendar_auth_service import CalendarAuthService

logger = logging.getLogger("smartdesk.calendar_sync")

DEFAULT_FUTURE_DAYS = 1


class CalendarSyncService:
    def __init__(
        self,
        auth_service: CalendarAuthService,
        sync_state_file: str,
    ) -> None:
        self._auth_service = auth_service
        self._sync_state_file = Path(sync_state_file)
        self._repo = CalendarEventRepository()

    def sync(
        self,
        db: Session,
        user_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        future_days: int | None = None,
    ) -> dict:
        creds = self._auth_service.get_credentials()
        if creds is None:
            raise ValueError("Calendar not authorized. Visit /api/v1/calendar/auth/start first.")

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        sync_state = self._load_sync_state().get(user_id, {})
        sync_token = sync_state.get("sync_token")

        now = datetime.now(timezone.utc)
        if time_min is None:
            time_min = now.isoformat()
        if time_max is None:
            days = future_days if future_days is not None else DEFAULT_FUTURE_DAYS
            time_max = (now + timedelta(days=days)).isoformat()

        items = []
        next_sync_token = None
        page_token = None

        def _list_events(params: dict) -> dict:
            return service.events().list(**params).execute()

        try:
            while True:
                params = {
                    "calendarId": "primary",
                    "singleEvents": True,
                    "showDeleted": True,
                    "maxResults": 2500,
                }
                if sync_token and time_min and time_max and sync_state.get("use_sync_token", True):
                    params["syncToken"] = sync_token
                else:
                    params["timeMin"] = time_min
                    params["timeMax"] = time_max
                if page_token:
                    params["pageToken"] = page_token

                response = _list_events(params)
                items.extend(response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    next_sync_token = response.get("nextSyncToken")
                    break
        except HttpError as exc:
            if exc.resp is not None and exc.resp.status == 410:
                logger.warning("Calendar sync token expired; falling back to full sync.")
                sync_state = {"use_sync_token": False}
                self._save_sync_state(user_id, sync_state)
                return self.sync(db, user_id, time_min=time_min, time_max=time_max)
            raise

        upserted = 0
        for event in items:
            event_id = event.get("id")
            if not event_id:
                continue

            mapped = self._map_event(event)
            self._repo.upsert_event(db, user_id, event_id, mapped)
            upserted += 1

        db.commit()
        if next_sync_token:
            sync_state["sync_token"] = next_sync_token
            sync_state["use_sync_token"] = True
        sync_state["last_sync"] = datetime.now(timezone.utc).isoformat()
        self._save_sync_state(user_id, sync_state)

        return {
            "upserted": upserted,
            "last_sync": sync_state.get("last_sync"),
            "time_min": time_min,
            "time_max": time_max,
        }

    def _map_event(self, event: dict) -> dict:
        start_raw = event.get("start", {})
        end_raw = event.get("end", {})
        start_time, tz = self._extract_time(start_raw)
        end_time, end_tz = self._extract_time(end_raw)
        if end_tz and not tz:
            tz = end_tz

        duration = None
        if start_time and end_time:
            duration = self._duration_seconds(start_time, end_time)

        return {
            "title": event.get("summary") or "(no title)",
            "start_time": start_time,
            "end_time": end_time,
            "timezone": tz,
            "duration_sec": duration,
            "status": event.get("status"),
            "extra_data": {
                "location": event.get("location"),
                "organizer": (event.get("organizer") or {}).get("email"),
                "hangout_link": event.get("hangoutLink"),
                "html_link": event.get("htmlLink"),
            },
            "source": "google_calendar",
        }

    def _extract_time(self, payload: dict) -> tuple[str | None, str | None]:
        if "dateTime" in payload:
            return payload.get("dateTime"), payload.get("timeZone")
        if "date" in payload:
            return f"{payload.get('date')}T00:00:00", payload.get("timeZone")
        return None, None

    def _duration_seconds(self, start_iso: str, end_iso: str) -> int | None:
        try:
            start = datetime.fromisoformat(start_iso)
            end = datetime.fromisoformat(end_iso)
        except ValueError:
            return None
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))

    def _load_sync_state(self) -> dict:
        if not self._sync_state_file.exists():
            return {}
        try:
            return json.loads(self._sync_state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_sync_state(self, user_id: str, state: dict) -> None:
        data = self._load_sync_state()
        data[user_id] = state
        self._sync_state_file.parent.mkdir(parents=True, exist_ok=True)
        self._sync_state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
