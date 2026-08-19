"""SmartDesk orchestration over the independent GitHub collector package."""

import hashlib
import hmac
import secrets
from typing import Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.github_integration_repository import GitHubIntegrationRepository
from app.services.github_prediction_service import GitHubPredictionService
from github_data_collection import (
    build_installation_url,
    build_user_authorization_url,
    create_app_jwt,
    create_installation_token,
    discover_projects,
    exchange_user_code,
    get_event_identity,
    get_installation,
    get_authenticated_user,
    get_status_mapping,
    get_status_options,
    handle_github_webhook_event,
    initial_sync,
    set_status_mapping,
)
from github_data_collection.collectors.metadata_collector import collect as collect_metadata
from github_data_collection.task_metadata_service import TaskMetadataService


class GitHubIntegrationService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = GitHubIntegrationRepository(db)

    @staticmethod
    def _require_app_config() -> None:
        if not all((
            settings.SMARTDESK_GITHUB_APP_ID,
            settings.SMARTDESK_GITHUB_APP_SLUG,
            settings.SMARTDESK_GITHUB_APP_PRIVATE_KEY,
        )):
            raise RuntimeError("GitHub App configuration is missing")

    @staticmethod
    def _app_jwt() -> str:
        GitHubIntegrationService._require_app_config()
        private_key = settings.SMARTDESK_GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")
        return create_app_jwt(settings.SMARTDESK_GITHUB_APP_ID, private_key)

    @staticmethod
    def _state_hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def connection_status(self, user_id: str) -> dict:
        row = self.repository.get_connection(user_id)
        if row is None:
            return {"user_id": user_id, "connection_status": "disconnected"}
        status = row.connection_status
        return {
            "user_id": row.user_id,
            "github_login": row.github_login,
            "installation_account_login": row.installation_account_login,
            "installation_account_type": row.installation_account_type,
            "installation_id": row.installation_id,
            "connection_status": status,
            "selected_owner": row.selected_owner,
            "selected_project_number": row.selected_project_number,
            "selected_project_id": row.selected_project_id,
            "selected_project_title": row.selected_project_title,
        }

    def begin_installation(self, user_id: str) -> str:
        self._require_app_config()
        row = self.repository.get_connection(user_id)
        if (
            row is not None
            and row.connection_status in {
                "reauthorization_required", "pending_user_authorization"
            }
            and row.installation_id
        ):
            installation = get_installation(self._app_jwt(), row.installation_id)
            account = installation.get("account") or {}
            account_login = account.get("login")
            account_type = account.get("type")
            if account_type == "Organization" and account_login:
                if (
                    row.installation_account_login
                    and row.installation_account_login.casefold() != account_login.casefold()
                ):
                    raise RuntimeError(
                        "Preserved GitHub installation account does not match GitHub"
                    )
                return self._begin_organization_user_authorization(
                    user_id, row.installation_id, account_login, account_type
                )

        state = secrets.token_urlsafe(32)
        self.repository.create_state(user_id, self._state_hash(state))
        return build_installation_url(settings.SMARTDESK_GITHUB_APP_SLUG, state)

    @staticmethod
    def _require_user_oauth_config() -> None:
        if not all((
            settings.SMARTDESK_GITHUB_OAUTH_CLIENT_ID,
            settings.SMARTDESK_GITHUB_OAUTH_CLIENT_SECRET,
            settings.SMARTDESK_GITHUB_USER_CALLBACK_URL,
        )):
            raise RuntimeError(
                "GitHub user OAuth configuration is required for organization installations"
            )

    def _begin_organization_user_authorization(
        self, user_id: str, installation_id: int,
        account_login: str, account_type: str,
    ) -> str:
        self._require_user_oauth_config()
        self.repository.stage_organization_installation(
            user_id, installation_id, account_login, account_type
        )
        oauth_state = secrets.token_urlsafe(32)
        self.repository.create_state(user_id, self._state_hash(oauth_state))
        return build_user_authorization_url(
            settings.SMARTDESK_GITHUB_OAUTH_CLIENT_ID,
            settings.SMARTDESK_GITHUB_USER_CALLBACK_URL,
            oauth_state,
        )

    def complete_installation(self, installation_id: int, state: str) -> dict:
        self._require_app_config()
        if not installation_id or not state:
            raise ValueError("Installation ID and state are required")
        user_id = self.repository.consume_state(self._state_hash(state))
        installation = get_installation(self._app_jwt(), installation_id)
        account = installation.get("account") or {}
        account_login = account.get("login")
        account_type = account.get("type")
        if not account_login or account_type not in {"User", "Organization"}:
            raise RuntimeError("GitHub installation has no account identity")
        if account_type == "User":
            row = self.repository.connect(
                user_id, account_login, installation_id,
                installation_account_login=account_login,
                installation_account_type=account_type,
            )
            return {**self.connection_status(row.user_id), "user_authorization_url": None}

        user_authorization_url = self._begin_organization_user_authorization(
            user_id, installation_id, account_login, account_type
        )
        return {
            **self.connection_status(user_id),
            "user_authorization_url": user_authorization_url,
        }

    def complete_user_authorization(self, code: str, state: str) -> dict:
        self._require_user_oauth_config()
        if not code or not state:
            raise ValueError("GitHub user authorization code and state are required")
        user_id = self.repository.consume_state(self._state_hash(state))
        row = self.repository.get_connection(user_id)
        if row is None or row.connection_status != "pending_user_authorization":
            raise ValueError("No organization installation is awaiting user authorization")
        user_token = exchange_user_code(
            settings.SMARTDESK_GITHUB_OAUTH_CLIENT_ID,
            settings.SMARTDESK_GITHUB_OAUTH_CLIENT_SECRET,
            code,
            settings.SMARTDESK_GITHUB_USER_CALLBACK_URL,
        )
        login = get_authenticated_user(user_token).get("login")
        if not login:
            raise RuntimeError("GitHub user authorization returned no login")
        self.repository.complete_user_authorization(user_id, login)
        return self.connection_status(user_id)

    def _token(self, user_id: str) -> str:
        row = self.repository.get_connection(user_id)
        if row is None or row.connection_status != "connected" or not row.installation_id or not row.github_login:
            raise PermissionError("GitHub App is not installed for this SmartDesk user")
        return create_installation_token(self._app_jwt(), row.installation_id)

    def projects(self, user_id: str) -> list[dict]:
        row = self.repository.get_connection(user_id)
        if row is None or not row.github_login:
            raise PermissionError("GitHub App is not installed for this SmartDesk user")
        return discover_projects(self._token(user_id), row.installation_account_login)

    def select_project(self, user_id: str, selection) -> dict:
        accessible = self.projects(user_id)
        if not any(
            project.get("project_id") == selection.project_id
            and project.get("owner") == selection.owner
            and project.get("number") == selection.project_number
            for project in accessible
        ):
            raise ValueError("Selected project is not accessible to this GitHub connection")
        row = self.repository.select_project(
            user_id, selection.owner, selection.project_number,
            selection.project_id, selection.title,
        )
        return self.connection_status(row.user_id)

    def status_options(self, user_id: str) -> list[dict]:
        row = self.repository.get_connection(user_id)
        if row is None or not row.selected_project_id:
            raise LookupError("Select a GitHub project first")
        return get_status_options(row.selected_project_id, self._token(user_id))

    def save_mapping(self, user_id: str, mapping: Dict[str, str]) -> str:
        row = self.repository.get_connection(user_id)
        if row is None or not row.selected_project_id:
            raise LookupError("Select a GitHub project first")
        set_status_mapping(row.selected_project_id, mapping)
        # Mapping is required before a meaningful baseline can be established.
        return self.synchronize(user_id)

    def current_mapping(self, user_id: str) -> dict[str, str]:
        row = self.repository.get_connection(user_id)
        if row is None or not row.selected_project_id:
            return {}
        return get_status_mapping(row.selected_project_id)

    def _metadata_service(self, user_id: str, project_id: str,
                          github_login: str) -> TaskMetadataService:
        def fetcher(item_id: str, token: str | None = None):
            metadata = collect_metadata(item_id, token=token)
            metadata["smartdesk_user_id"] = user_id
            metadata["project_id"] = project_id
            return metadata
        prediction_service = GitHubPredictionService(self.db)
        return TaskMetadataService(
            fetcher=fetcher,
            on_lifecycle_started=prediction_service.predict_initial,
            connected_github_login=github_login,
        )

    def active_tasks(self, user_id: str) -> list[dict]:
        row = self.repository.get_connection(user_id)
        if row is None or row.connection_status != "connected":
            return []
        project_id = row.selected_project_id
        return GitHubPredictionService(self.db).active_tasks(user_id, project_id)

    def synchronize(self, user_id: str) -> str:
        row = self.repository.get_connection(user_id)
        if row is None or not row.selected_project_id or row.selected_project_number is None:
            raise LookupError("Select a GitHub project first")
        token = self._token(user_id)
        return initial_sync(
            owner=row.selected_owner,
            project_number=row.selected_project_number,
            token=token,
            metadata_service=self._metadata_service(
                user_id, row.selected_project_id, row.github_login
            ),
        )

    @staticmethod
    def verify_signature(body: bytes, signature: str | None) -> bool:
        secret = settings.SMARTDESK_GITHUB_WEBHOOK_SECRET
        if not secret or not signature or not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)

    def process_webhook(self, payload: dict, headers: dict) -> None:
        project_id, _ = get_event_identity(payload)
        if not project_id:
            return
        connection = self.repository.get_connection_by_project(project_id)
        if connection is None:
            return
        token = self._token(connection.user_id)
        handle_github_webhook_event(
            payload,
            headers,
            token=token,
            metadata_service=self._metadata_service(
                connection.user_id, project_id, connection.github_login
            ),
        )

    def disconnect(self, user_id: str) -> None:
        self.repository.disconnect(user_id)
