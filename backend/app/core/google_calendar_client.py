import datetime
import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional during minimal installs
    load_dotenv = None


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

COLOMBO_TZ = ZoneInfo("Asia/Colombo")

_NETWORK_RETRY_ATTEMPTS = 3
_NETWORK_RETRY_BASE_DELAY_SECONDS = 2.0
_REAUTH_REQUIRED = False
_REAUTH_NOTICE_LOGGED = False
_CREDENTIALS_MISSING_NOTICE_LOGGED = False
_AUTH_LOCK = threading.Lock()


def _load_env_files() -> None:
    """Load local .env files so calendar OAuth config works during normal startup."""

    if load_dotenv is None:
        return

    current_file = Path(__file__).resolve()
    backend_root = current_file.parents[2]
    project_root = current_file.parents[3]

    load_dotenv(project_root / ".env", override=False)
    load_dotenv(backend_root / ".env", override=False)


_load_env_files()


class CalendarReauthRequiredError(RuntimeError):
    """Raised when OAuth token is invalid and manual re-auth is required."""


class CalendarNotConnectedError(RuntimeError):
    """Raised when the user has not completed the one-time calendar setup."""


def _get_app_data_dir() -> Path:
    """Return a per-user directory for storing auth tokens."""

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


def _get_runtime_oauth_client_path() -> Path:
    return _get_app_data_dir() / "oauth-client.json"


def _get_default_credentials_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "calender" / "credentials.json"


def _get_bundled_client_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "google_calendar_client.json"


def _build_client_config_from_env_fields() -> Dict[str, Any] | None:
    client_id = os.environ.get("SMARTDESK_GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("SMARTDESK_GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    project_id = os.environ.get("SMARTDESK_GOOGLE_PROJECT_ID", "smartdesk")

    return {
        "installed": {
            "client_id": client_id,
            "project_id": project_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [
                "http://localhost",
            ],
        }
    }


def _get_client_config_details() -> Dict[str, Any]:
    bundled_path = _get_bundled_client_config_path()
    legacy_path = _get_default_credentials_path()
    inline_json = os.environ.get("SMARTDESK_CALENDAR_CLIENT_CONFIG_JSON")
    env_fields_config = _build_client_config_from_env_fields()
    legacy_env_path = os.environ.get("SMARTDESK_CALENDAR_CREDENTIALS_PATH")

    if inline_json:
        try:
            data = json.loads(inline_json)
            return {
                "available": True,
                "source": "env_json",
                "path": str(_get_runtime_oauth_client_path()),
                "warning": None,
                "data": data,
            }
        except json.JSONDecodeError as exc:
            return {
                "available": False,
                "source": "env_json_invalid",
                "path": str(_get_runtime_oauth_client_path()),
                "warning": f"SMARTDESK_CALENDAR_CLIENT_CONFIG_JSON is invalid JSON: {exc}",
                "data": None,
            }

    if env_fields_config:
        return {
            "available": True,
            "source": "env_fields",
            "path": str(_get_runtime_oauth_client_path()),
            "warning": None,
            "data": env_fields_config,
        }

    if bundled_path.exists():
        try:
            return {
                "available": True,
                "source": "bundled_file",
                "path": str(bundled_path),
                "warning": None,
                "data": json.loads(bundled_path.read_text(encoding="utf-8")),
            }
        except Exception as exc:
            return {
                "available": False,
                "source": "bundled_file_invalid",
                "path": str(bundled_path),
                "warning": f"Bundled Google OAuth config could not be read: {exc}",
                "data": None,
            }

    if legacy_env_path:
        legacy_env_candidate = Path(legacy_env_path)
        if legacy_env_candidate.exists():
            try:
                return {
                    "available": True,
                    "source": "legacy_env_path",
                    "path": str(legacy_env_candidate),
                    "warning": (
                        "Using legacy SMARTDESK_CALENDAR_CREDENTIALS_PATH. "
                        "Prefer bundled app config or env-based client settings."
                    ),
                    "data": json.loads(legacy_env_candidate.read_text(encoding="utf-8")),
                }
            except Exception as exc:
                return {
                    "available": False,
                    "source": "legacy_env_path_invalid",
                    "path": str(legacy_env_candidate),
                    "warning": f"Legacy credentials file could not be read: {exc}",
                    "data": None,
                }

    if legacy_path.exists():
        try:
            return {
                "available": True,
                "source": "legacy_project_file",
                "path": str(legacy_path),
                "warning": (
                    "Using legacy calender/credentials.json. "
                    "Prefer bundled app config for production."
                ),
                "data": json.loads(legacy_path.read_text(encoding="utf-8")),
            }
        except Exception as exc:
            return {
                "available": False,
                "source": "legacy_project_file_invalid",
                "path": str(legacy_path),
                "warning": f"Legacy project credentials file could not be read: {exc}",
                "data": None,
            }

    return {
        "available": False,
        "source": "missing",
        "path": str(bundled_path),
        "warning": (
            "No bundled Google OAuth client config was found. "
            "Configure the app once during packaging or deployment."
        ),
        "data": None,
    }


def _get_credentials_details() -> Dict[str, Any]:
    details = _get_client_config_details()
    return {
        "available": details["available"],
        "path": Path(details["path"]),
        "source": details["source"],
        "warning": details["warning"],
    }


def _get_credentials_path() -> Path:
    details = _get_client_config_details()
    if details["available"] and details["data"] is not None:
        runtime_path = _get_runtime_oauth_client_path()
        runtime_path.write_text(json.dumps(details["data"], indent=2), encoding="utf-8")
        return runtime_path

    raise FileNotFoundError(
        "Google Calendar client configuration not found. Expected bundled app "
        f"configuration or valid environment-based client settings. Last checked: "
        f"'{details['path']}'."
    )


def _log_missing_credentials_once(exc: BaseException) -> None:
    global _CREDENTIALS_MISSING_NOTICE_LOGGED

    if _CREDENTIALS_MISSING_NOTICE_LOGGED:
        return

    print(
        "[Calendar Collector] Calendar setup required: missing Google OAuth client config. "
        f"{exc}"
    )
    _CREDENTIALS_MISSING_NOTICE_LOGGED = True


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
        if isinstance(item, OSError) and getattr(item, "errno", None) in {
            11001,
            11002,
            11003,
            11004,
        }:
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


def _is_invalid_grant_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    indicators = (
        "invalid_grant",
        "token has been expired or revoked",
        "error_description",
    )
    return any(token in msg for token in indicators)


def _mark_reauth_required(exc: BaseException) -> None:
    global _REAUTH_REQUIRED
    global _REAUTH_NOTICE_LOGGED

    _REAUTH_REQUIRED = True
    if _REAUTH_NOTICE_LOGGED:
        return

    token_path = _get_token_path()
    print(
        "[Calendar Collector] Google token is invalid (expired/revoked). "
        "Calendar sync will pause until re-authentication. "
        f"Delete token file '{token_path}' and restart backend to re-connect. "
        f"Original error: {exc}"
    )
    _REAUTH_NOTICE_LOGGED = True


def _clear_runtime_auth_flags() -> None:
    global _REAUTH_REQUIRED
    global _REAUTH_NOTICE_LOGGED
    global _CREDENTIALS_MISSING_NOTICE_LOGGED

    _REAUTH_REQUIRED = False
    _REAUTH_NOTICE_LOGGED = False
    _CREDENTIALS_MISSING_NOTICE_LOGGED = False


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


def _load_token_credentials() -> Credentials | None:
    token_path = _get_token_path()
    if not token_path.exists():
        return None

    try:
        return Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception:
        return None


def get_calendar_connection_status() -> Dict[str, Any]:
    credentials = _get_credentials_details()
    token_path = _get_token_path()
    token_exists = token_path.exists()
    token_error = None
    token_valid = False
    token_refreshable = False

    creds = _load_token_credentials()
    if creds:
        token_valid = bool(creds.valid)
        token_refreshable = bool(creds.refresh_token)
    elif token_exists:
        token_error = "Saved token could not be read."

    if not credentials["available"]:
        state = "credentials_missing"
        ready = False
        action = (
            "This app is missing its bundled Google OAuth client configuration. "
            "Add it once as the app owner, then users can connect without placing files manually."
        )
    elif _REAUTH_REQUIRED:
        state = "reauth_required"
        ready = False
        action = "Reconnect Google Calendar to refresh the saved token."
    elif token_exists and (token_valid or token_refreshable):
        state = "connected"
        ready = True
        action = "Calendar is connected. Sync runs automatically in the background."
    else:
        state = "not_connected"
        ready = False
        action = "Connect Google Calendar once to enable automatic background sync."

    return {
        "state": state,
        "ready": ready,
        "action": action,
        "credentials": {
            "available": credentials["available"],
            "path": str(credentials["path"]),
            "source": credentials["source"],
            "warning": credentials["warning"],
        },
        "token": {
            "exists": token_exists,
            "path": str(token_path),
            "valid": token_valid,
            "refreshable": token_refreshable,
            "error": token_error,
        },
    }


def authenticate(
    allow_interactive: bool = False,
    force_reauth: bool = False,
) -> Credentials:
    with _AUTH_LOCK:
        if force_reauth:
            disconnect_calendar()

        if _REAUTH_REQUIRED and not allow_interactive:
            raise CalendarReauthRequiredError("Calendar re-authentication required")

        creds: Credentials | None = _load_token_credentials()
        token_path = _get_token_path()

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                _run_with_network_retry("token refresh", lambda: creds.refresh(Request()))
                token_path.write_text(creds.to_json(), encoding="utf-8")
                _clear_runtime_auth_flags()
                return creds
            except Exception as exc:
                if _is_invalid_grant_error(exc):
                    try:
                        if token_path.exists():
                            token_path.unlink()
                    except OSError:
                        pass
                    _mark_reauth_required(exc)
                    raise CalendarReauthRequiredError(
                        "Calendar re-authentication required"
                    ) from exc
                raise

        if not allow_interactive:
            raise CalendarNotConnectedError("Calendar is not connected")

        credentials_path = _get_credentials_path()
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        _clear_runtime_auth_flags()
        return creds


def connect_calendar(force_reauth: bool = False) -> Dict[str, Any]:
    creds = authenticate(allow_interactive=True, force_reauth=force_reauth)
    return {
        "connected": True,
        "account": getattr(creds, "account", None),
        "status": get_calendar_connection_status(),
    }


def disconnect_calendar() -> Dict[str, Any]:
    token_path = _get_token_path()
    removed = False
    try:
        if token_path.exists():
            token_path.unlink()
            removed = True
    finally:
        _clear_runtime_auth_flags()

    return {
        "disconnected": True,
        "removed_token": removed,
        "status": get_calendar_connection_status(),
    }


def fetch_events(
    creds: Credentials, start_time: str, end_time: str
) -> List[Dict[str, Any]]:
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


def _parse_event_datetime(value: str | None) -> datetime.datetime | None:
    if not value:
        return None

    normalized_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(normalized_value)
    except ValueError:
        try:
            parsed_date = datetime.date.fromisoformat(value)
            parsed = datetime.datetime.combine(parsed_date, datetime.time.min)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)

    return parsed.astimezone(COLOMBO_TZ)


def normalize_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for event in events:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get(
            "date"
        )
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        tz_name = event.get("start", {}).get("timeZone") or event.get("end", {}).get("timeZone")
        attendees = event.get("attendees", [])
        duration_minutes = None
        start_dt = _parse_event_datetime(start)
        end_dt = _parse_event_datetime(end)

        if start_dt and end_dt:
            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)

        normalized.append(
            {
                "event_id": event.get("id"),
                "title": event.get("summary", "No Title"),
                "start_time": start_dt.replace(microsecond=0).isoformat() if start_dt else start,
                "end_time": end_dt.replace(microsecond=0).isoformat() if end_dt else end,
                "timezone": tz_name or "Asia/Colombo",
                "duration_minutes": duration_minutes,
                "attendees_count": len(attendees),
                "is_solo": len(attendees) <= 1,
                "is_recurring": "recurringEventId" in event,
            }
        )

    return normalized


def get_calendar_data(
    hours_ahead: int = 24,
    allow_interactive: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch and normalize calendar events for the next `hours_ahead` hours."""

    try:
        creds = authenticate(allow_interactive=allow_interactive)
    except CalendarNotConnectedError:
        return []
    except CalendarReauthRequiredError:
        return []
    except FileNotFoundError as exc:
        _log_missing_credentials_once(exc)
        return []
    except Exception as exc:
        if _is_invalid_grant_error(exc):
            _mark_reauth_required(exc)
            return []
        if _is_transient_network_error(exc):
            print(
                "[Calendar Collector] Skipping sync due to temporary network/DNS issue: "
                f"{exc}"
            )
            return []
        raise

    now_dt = datetime.datetime.now(COLOMBO_TZ)
    now = now_dt.replace(microsecond=0).isoformat()
    end_dt = now_dt + datetime.timedelta(hours=hours_ahead)
    end = end_dt.replace(microsecond=0).isoformat()

    try:
        events = _run_with_network_retry(
            "calendar events fetch",
            lambda: fetch_events(creds, now, end),
        )
    except Exception as exc:
        if _is_invalid_grant_error(exc):
            _mark_reauth_required(exc)
            return []
        if _is_transient_network_error(exc):
            print(
                "[Calendar Collector] Skipping sync due to temporary network/DNS issue: "
                f"{exc}"
            )
            return []
        raise

    clean_data = normalize_events(events)
    return clean_data


if __name__ == "__main__":  # Manual debug helper
    data = get_calendar_data()
    print(json.dumps(data, indent=2))
