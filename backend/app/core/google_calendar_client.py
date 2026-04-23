import datetime
import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BASE_DELAY_SECONDS = 2.0


def _get_app_data_dir() -> Path:
    """Return a per-user directory for storing auth tokens.

    This avoids writing token files into the project folder and works
    across platforms. On Windows it prefers %APPDATA%/SmartDesk.
    """

    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / ".smartdesk"

    dir_path = base / "smartdesk-calendar"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def _get_token_path() -> Path:
    return _get_app_data_dir() / "token.json"


def _get_credentials_path() -> Path:
    """Resolve path to credentials.json.

    For now this falls back to the legacy calender/credentials.json file
    at the project root so your existing setup keeps working.
    In a packaged app you can replace this with a bundled client config
    or an environment-variable-driven path.
    """

    env_path = os.environ.get("SMARTDESK_CALENDAR_CREDENTIALS_PATH")
    if env_path:
        return Path(env_path)

    # Default: project-root/calender/credentials.json
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "calender" / "credentials.json"


def _iter_exception_chain(exc: BaseException):
    """Yield exception and linked causes/contexts without recursion loops."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_transient_network_error(exc: BaseException) -> bool:
    for item in _iter_exception_chain(exc):
        if isinstance(item, socket.gaierror):
            return True
        if isinstance(item, OSError) and getattr(item, "errno", None) in {11001, 11002, 11003, 11004}:
            return True

    msg = str(exc).lower()
    indicators = (
        "nameresolutionerror",
        "getaddrinfo failed",
        "max retries exceeded",
        "temporary failure in name resolution",
        "failed to resolve",
        "connection aborted",
        "connection reset",
        "connection refused",
        "timed out",
    )
    return any(token in msg for token in indicators)


def _run_with_network_retry(action_name: str, fn):
    delay_seconds = _NETWORK_RETRY_BASE_DELAY_SECONDS

    for attempt in range(1, _NETWORK_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            is_last_attempt = attempt == _NETWORK_RETRY_ATTEMPTS
            if not _is_transient_network_error(exc) or is_last_attempt:
                raise

            print(
                f"[Calendar Collector] Transient network error during {action_name} "
                f"(attempt {attempt}/{_NETWORK_RETRY_ATTEMPTS}): {exc}. "
                f"Retrying in {delay_seconds:.0f}s..."
            )
            time.sleep(delay_seconds)
            delay_seconds *= 2


def authenticate() -> Credentials:
    creds: Credentials | None = None
    token_path = _get_token_path()

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            _run_with_network_retry("token refresh", lambda: creds.refresh(Request()))
        else:
            credentials_path = _get_credentials_path()
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Persist for future runs
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def fetch_events(creds: Credentials, start_time: str, end_time: str) -> List[Dict[str, Any]]:
    service = build("calendar", "v3", credentials=creds)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_time,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return events_result.get("items", [])


def normalize_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for event in events:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")

        normalized.append(
            {
                "event_id": event.get("id"),
                "title": event.get("summary", "No Title"),
                "start_time": start,
                "end_time": end,
                "attendees_count": len(event.get("attendees", [])),
                "is_recurring": "recurringEventId" in event,
            }
        )

    return normalized


def get_calendar_data(hours_ahead: int = 24) -> list[dict[str, Any]]:
    """Fetch and normalize calendar events for the next `hours_ahead` hours."""

    try:
        creds = authenticate()
    except Exception as exc:
        if _is_transient_network_error(exc):
            print(f"[Calendar Collector] Skipping sync due to temporary network/DNS issue: {exc}")
            return []
        raise

    now = datetime.datetime.utcnow().isoformat() + "Z"
    end_dt = datetime.datetime.utcnow() + datetime.timedelta(hours=hours_ahead)
    end = end_dt.isoformat() + "Z"

    try:
        events = _run_with_network_retry(
            "calendar events fetch",
            lambda: fetch_events(creds, now, end),
        )
    except Exception as exc:
        if _is_transient_network_error(exc):
            print(f"[Calendar Collector] Skipping sync due to temporary network/DNS issue: {exc}")
            return []
        raise

    clean_data = normalize_events(events)
    return clean_data


if __name__ == "__main__":  # Manual debug helper
    data = get_calendar_data()
    print(json.dumps(data, indent=2))
