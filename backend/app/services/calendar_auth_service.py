import json
import logging
from pathlib import Path
from uuid import uuid4

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger("smartdesk.calendar_auth")


class CalendarAuthService:
    def __init__(
        self,
        credentials_file: str,
        token_file: str,
        scopes: list[str],
        redirect_uri: str,
        state_file: str,
    ) -> None:
        self._credentials_file = Path(credentials_file)
        self._token_file = Path(token_file)
        self._scopes = scopes
        self._redirect_uri = redirect_uri
        self._state_file = Path(state_file)

    def token_present(self) -> bool:
        if not self._token_file.exists():
            return False
        try:
            data = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(data.get("refresh_token"))

    def get_authorization_url(self) -> str:
        flow = Flow.from_client_secrets_file(
            str(self._credentials_file),
            scopes=self._scopes,
            redirect_uri=self._redirect_uri,
        )
        state = uuid4().hex
        prompt = "consent" if not self.token_present() else None
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt=prompt,
            state=state,
        )
        self._save_state(state, flow.code_verifier)
        return auth_url

    def handle_callback(self, code: str, state: str | None) -> None:
        if not state:
            raise ValueError("Missing OAuth state.")

        code_verifier = self._load_state(state)
        if not code_verifier:
            raise ValueError("Invalid or expired OAuth state.")

        flow = Flow.from_client_secrets_file(
            str(self._credentials_file),
            scopes=self._scopes,
            redirect_uri=self._redirect_uri,
        )
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
        self._save_credentials(creds)
        self._delete_state(state)

    def get_credentials(self) -> Credentials | None:
        if not self._token_file.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(
                str(self._token_file),
                scopes=self._scopes,
            )
        except Exception:
            logger.exception("Failed to load calendar credentials.")
            return None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_credentials(creds)
            except RefreshError as exc:
                if "invalid_grant" in str(exc).lower():
                    logger.warning(
                        "Calendar refresh token invalid; reconnect required."
                    )
                    self.clear_token()
                    return None
                logger.exception("Failed to refresh calendar credentials.")
                return None
            except Exception:
                logger.exception("Failed to refresh calendar credentials.")
                return None
        return creds

    def clear_token(self) -> None:
        try:
            if self._token_file.exists():
                self._token_file.unlink()
        except OSError:
            logger.exception("Failed to delete calendar token file.")

    def _save_credentials(self, creds: Credentials) -> None:
        self._token_file.parent.mkdir(parents=True, exist_ok=True)
        self._token_file.write_text(creds.to_json(), encoding="utf-8")

    def _save_state(self, state: str, code_verifier: str | None) -> None:
        if not code_verifier:
            return
        data = self._load_state_file()
        data[state] = code_verifier
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state(self, state: str) -> str | None:
        data = self._load_state_file()
        return data.get(state)

    def _delete_state(self, state: str) -> None:
        data = self._load_state_file()
        if state in data:
            data.pop(state, None)
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state_file(self) -> dict:
        if not self._state_file.exists():
            return {}
        try:
            return json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
