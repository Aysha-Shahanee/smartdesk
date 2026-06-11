"""Google Calendar integration.

Connection flows
----------------
* End users: one-click — GET /api/v1/calendar/connect redirects to Google's
  consent screen; the OAuth callback lands on this backend, stores the token,
  and triggers the first sync.
* Developers: supply credentials via env vars (GOOGLE_CLIENT_ID /
  GOOGLE_CLIENT_SECRET) or a credentials.json file (GOOGLE_CREDENTIALS_FILE).
  Env vars win when both are present.

Sync semantics
--------------
Events are upserted by (user_id, event_id): a re-sync UPDATES the existing
row when Google's ``updated`` stamp changed and never inserts a duplicate.
Deleted/cancelled events are kept and flagged status="cancelled".
Incremental sync uses Google's nextSyncToken; a 410 response triggers a
clean full re-sync. All stored times are Asia/Colombo ISO strings.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import APP_TZ
from app.core.time import local_now_iso
from app.core.time import parse_iso
from app.core.time import to_local_iso
from app.models.db import CalendarEventRecord

logger = logging.getLogger("smartdesk.calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
SCHEMA_VERSION = "2"

# Google may return more scopes than requested (e.g. when the account
# already granted this app other scopes in the past). Without this flag
# oauthlib raises "Scope has changed" and the callback 500s.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _store_dir() -> Path:
    path = Path(settings.CALENDAR_STORE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _token_file(user_id: str) -> Path:
    return _store_dir() / f"token_{user_id}.json"


def _oauth_state_file() -> Path:
    return _store_dir() / "oauth_state.json"


def _sync_state_file() -> Path:
    return _store_dir() / "sync_state.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class CalendarNotConfiguredError(Exception):
    """No Google client credentials available (env vars or credentials file)."""


class CalendarNotConnectedError(Exception):
    """The user has not completed the OAuth consent flow yet."""


class CalendarService:

    # ------------------------------------------------------------------ #
    # Credentials / configuration                                          #
    # ------------------------------------------------------------------ #

    def client_config(self) -> dict:
        """Resolve the OAuth client config: env vars first, then file."""
        if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
            return {
                "installed": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }

        creds_path = Path(settings.GOOGLE_CREDENTIALS_FILE)
        if creds_path.exists():
            config = _read_json(creds_path)
            if config:
                return config

        raise CalendarNotConfiguredError(
            "Google Calendar credentials not found. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in .env, or place a credentials.json at "
            f"{creds_path}."
        )

    def is_configured(self) -> bool:
        try:
            self.client_config()
            return True
        except CalendarNotConfiguredError:
            return False

    def _redirect_uri(self) -> str:
        return f"{settings.BACKEND_BASE_URL}/api/v1/calendar/oauth/callback"

    # ------------------------------------------------------------------ #
    # OAuth flow                                                           #
    # ------------------------------------------------------------------ #

    def build_auth_url(self, user_id: str) -> str:
        """Create the Google consent URL for the one-click connect flow."""
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(self.client_config(), scopes=SCOPES)
        flow.redirect_uri = self._redirect_uri()

        state = secrets.token_urlsafe(24)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
        )

        states = _read_json(_oauth_state_file())
        states[state] = {
            "user_id": user_id,
            # PKCE verifier must survive until the callback: the callback
            # builds a fresh Flow, and without the original verifier Google
            # rejects the exchange with "Missing code verifier".
            "code_verifier": flow.code_verifier,
            "created_at": local_now_iso(),
        }
        _write_json(_oauth_state_file(), states)
        return auth_url

    def handle_oauth_callback(self, state: str, code: str) -> str:
        """Exchange the auth code for a token. Returns the user_id."""
        from google_auth_oauthlib.flow import Flow

        states = _read_json(_oauth_state_file())
        entry = states.pop(state, None)
        if entry is None:
            raise ValueError("Unknown or expired OAuth state. Restart the connect flow.")
        _write_json(_oauth_state_file(), states)

        user_id = entry["user_id"]
        flow = Flow.from_client_config(self.client_config(), scopes=SCOPES, state=state)
        flow.redirect_uri = self._redirect_uri()
        if entry.get("code_verifier"):
            flow.code_verifier = entry["code_verifier"]
        flow.fetch_token(code=code)

        _token_file(user_id).write_text(flow.credentials.to_json(), encoding="utf-8")
        # New consent — start from a clean sync window.
        self._clear_sync_state(user_id)
        logger.info("Google Calendar connected for user %s.", user_id)
        return user_id

    def is_connected(self, user_id: str) -> bool:
        return _token_file(user_id).exists()

    def disconnect(self, user_id: str) -> None:
        _token_file(user_id).unlink(missing_ok=True)
        self._clear_sync_state(user_id)

    def _load_credentials(self, user_id: str):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        token_path = _token_file(user_id)
        if not token_path.exists():
            raise CalendarNotConnectedError(
                "Google Calendar is not connected. Use the Connect button first."
            )

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # Refresh token revoked or expired (7-day limit while the
                # OAuth app is in "Testing" status). Drop the dead token so
                # the dashboard shows "not connected" instead of failing
                # silently on every sync.
                logger.warning("Calendar token refresh failed (%s) — disconnecting.", exc)
                self.disconnect(user_id)
                raise CalendarNotConnectedError(
                    "Google token expired or was revoked. Click Connect again."
                ) from exc
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # ------------------------------------------------------------------ #
    # Sync                                                                 #
    # ------------------------------------------------------------------ #

    def sync(self, user_id: str, db: Session) -> dict[str, Any]:
        """Fetch events from Google and upsert them. Returns sync stats."""
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        creds = self._load_credentials(user_id)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        sync_state = _read_json(_sync_state_file())
        user_state = sync_state.get(user_id, {})
        sync_token = user_state.get("sync_token")

        list_kwargs: dict[str, Any] = {
            "calendarId": "primary",
            "singleEvents": True,
            "maxResults": 250,
            "showDeleted": True,
        }
        if sync_token:
            list_kwargs["syncToken"] = sync_token
        else:
            now = datetime.now(APP_TZ)
            list_kwargs["timeMin"] = (
                now - timedelta(days=settings.CALENDAR_SYNC_PAST_DAYS)
            ).isoformat()
            list_kwargs["timeMax"] = (
                now + timedelta(days=settings.CALENDAR_SYNC_FUTURE_DAYS)
            ).isoformat()

        stats = {"created": 0, "updated": 0, "cancelled": 0, "unchanged": 0}
        next_sync_token = None
        page_token = None

        while True:
            if page_token:
                list_kwargs["pageToken"] = page_token
            try:
                response = service.events().list(**list_kwargs).execute()
            except HttpError as exc:
                if exc.resp.status == 410 and sync_token:
                    # Sync token expired — drop it and run a full re-sync.
                    logger.info("Calendar sync token expired; running full re-sync.")
                    self._clear_sync_state(user_id)
                    return self.sync(user_id, db)
                raise

            for item in response.get("items", []):
                self._upsert_event(user_id, item, db, stats)

            page_token = response.get("nextPageToken")
            next_sync_token = response.get("nextSyncToken", next_sync_token)
            if not page_token:
                break

        db.commit()

        sync_state[user_id] = {
            "sync_token": next_sync_token,
            "last_sync": local_now_iso(),
        }
        _write_json(_sync_state_file(), sync_state)

        stats["total_in_db"] = (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == user_id)
            .count()
        )
        logger.info("Calendar sync for %s: %s", user_id, stats)
        return stats

    def _upsert_event(
        self, user_id: str, item: dict, db: Session, stats: dict[str, int]
    ) -> None:
        event_id = item.get("id")
        if not event_id:
            return

        now_iso = local_now_iso()
        record = (
            db.query(CalendarEventRecord)
            .filter(
                CalendarEventRecord.user_id == user_id,
                CalendarEventRecord.event_id == event_id,
            )
            .first()
        )

        status = item.get("status") or "confirmed"
        google_updated = item.get("updated")

        if status == "cancelled":
            if record is not None and record.status != "cancelled":
                record.status = "cancelled"
                record.google_updated_at = google_updated
                record.last_synced_at = now_iso
                record.updated_at = now_iso
                stats["cancelled"] += 1
            # Cancelled events we never stored are ignored.
            return

        if record is not None and record.google_updated_at == google_updated:
            record.last_synced_at = now_iso
            stats["unchanged"] += 1
            return

        fields = self._event_fields(item)
        if record is None:
            record = CalendarEventRecord(
                user_id=user_id,
                event_id=event_id,
                source="google",
                schema_version=SCHEMA_VERSION,
                created_at=now_iso,
                updated_at=now_iso,
                **fields,
            )
            record.google_updated_at = google_updated
            record.last_synced_at = now_iso
            db.add(record)
            stats["created"] += 1
        else:
            for key, value in fields.items():
                setattr(record, key, value)
            record.google_updated_at = google_updated
            record.last_synced_at = now_iso
            record.updated_at = now_iso
            stats["updated"] += 1

    def _event_fields(self, item: dict) -> dict[str, Any]:
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        is_all_day = "date" in start_raw

        start_iso = self._to_colombo(start_raw)
        end_iso = self._to_colombo(end_raw)

        duration_sec = None
        if start_iso and end_iso:
            duration_sec = max(
                0, int((parse_iso(end_iso) - parse_iso(start_iso)).total_seconds())
            )

        attendees = item.get("attendees") or []
        attendees_json = json.dumps(
            [
                {
                    "email": a.get("email"),
                    "response_status": a.get("responseStatus"),
                    "organizer": a.get("organizer", False),
                }
                for a in attendees
            ],
            separators=(",", ":"),
        ) if attendees else None

        return {
            "title": item.get("summary"),
            "description": item.get("description"),
            "location": item.get("location"),
            "start_time": start_iso,
            "end_time": end_iso,
            "timezone": start_raw.get("timeZone"),
            "is_all_day": 1 if is_all_day else 0,
            "duration_sec": duration_sec,
            "status": item.get("status") or "confirmed",
            "organizer_email": (item.get("organizer") or {}).get("email"),
            "attendees_count": len(attendees),
            "attendees_json": attendees_json,
            "is_recurring": 1 if (item.get("recurringEventId") or item.get("recurrence")) else 0,
            "recurring_event_id": item.get("recurringEventId"),
            "html_link": item.get("htmlLink"),
        }

    def _to_colombo(self, when: dict) -> str | None:
        """Convert a Google start/end object to an Asia/Colombo ISO string."""
        if "dateTime" in when:
            return to_local_iso(datetime.fromisoformat(when["dateTime"]))
        if "date" in when:
            # All-day events: midnight Colombo on that date.
            day = datetime.fromisoformat(when["date"])
            return day.replace(tzinfo=APP_TZ).isoformat()
        return None

    def _clear_sync_state(self, user_id: str) -> None:
        sync_state = _read_json(_sync_state_file())
        sync_state.pop(user_id, None)
        _write_json(_sync_state_file(), sync_state)

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def status(self, user_id: str, db: Session) -> dict[str, Any]:
        sync_state = _read_json(_sync_state_file()).get(user_id, {})
        return {
            "configured": self.is_configured(),
            "connected": self.is_connected(user_id),
            "last_sync": sync_state.get("last_sync"),
            "event_count": (
                db.query(CalendarEventRecord)
                .filter(CalendarEventRecord.user_id == user_id)
                .count()
            ),
        }

    def list_events(
        self, user_id: str, db: Session, from_iso: str | None, to_iso: str | None
    ) -> list[CalendarEventRecord]:
        """Return events ordered by start time (Colombo)."""
        rows = (
            db.query(CalendarEventRecord)
            .filter(CalendarEventRecord.user_id == user_id)
            .all()
        )
        if from_iso:
            rows = [r for r in rows if r.start_time and parse_iso(r.start_time) >= parse_iso(from_iso)]
        if to_iso:
            rows = [r for r in rows if r.start_time and parse_iso(r.start_time) <= parse_iso(to_iso)]
        return sorted(rows, key=lambda r: r.start_time or "")
