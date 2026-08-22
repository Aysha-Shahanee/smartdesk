import hashlib
import hmac
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.db.github import GitHubConnectionRecord, GitHubOAuthStateRecord
from app.models.github_integration import GitHubProjectSelection
from app.routes.github_integration import callback, setup_page, user_callback
from app.services.github_integration_service import GitHubIntegrationService


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                GitHubConnectionRecord.__table__,
                GitHubOAuthStateRecord.__table__,
            ],
        )
        self.db = sessionmaker(bind=engine)()
        self.service = GitHubIntegrationService(self.db)

    def tearDown(self):
        self.db.close()

    def test_installation_state_is_single_use_and_binds_local_user(self):
        raw_state = "valid-state"
        self.service.repository.create_state(
            "user-one", hashlib.sha256(raw_state.encode()).hexdigest()
        )
        with patch("app.services.github_integration_service.get_installation", return_value={"account": {"login": "octocat", "type": "User"}}), \
             patch("app.services.github_integration_service.create_app_jwt", return_value="jwt"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"):
            result = self.service.complete_installation(123, raw_state)
            self.assertEqual(result["user_id"], "user-one")
            with self.assertRaisesRegex(ValueError, "Invalid or expired"):
                self.service.complete_installation(123, raw_state)

    def test_invalid_installation_state_is_rejected(self):
        with patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"):
            with self.assertRaisesRegex(ValueError, "Invalid or expired"):
                self.service.complete_installation(123, "unknown")

    def test_begin_installation_returns_app_url_with_single_use_state(self):
        with patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk-development"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"):
            installation_url = self.service.begin_installation("user-one")

        parsed = urlparse(installation_url)
        state = parse_qs(parsed.query).get("state", [""])[0]
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "github.com")
        self.assertEqual(parsed.path, "/apps/smartdesk-development/installations/new")
        self.assertTrue(state)

    def test_reauthorization_required_organization_starts_user_oauth_directly(self):
        self.service.repository.connect(
            "user-one", "legacy-org", 123,
            installation_account_login="example-org",
            installation_account_type=None,
        )
        self.service.repository.select_project(
            "user-one", "example-org", 7, "PVT_7", "Roadmap"
        )
        row = self.service.repository.get_connection("user-one")
        original_row_id = row.id
        row.github_login = None
        row.connection_status = "reauthorization_required"
        self.db.commit()

        with patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"), \
             patch.object(settings, "SMARTDESK_GITHUB_OAUTH_CLIENT_ID", "client-id"), \
             patch.object(settings, "SMARTDESK_GITHUB_OAUTH_CLIENT_SECRET", "client-secret"), \
             patch.object(settings, "SMARTDESK_GITHUB_USER_CALLBACK_URL", "http://localhost/user-callback"), \
             patch("app.services.github_integration_service.create_app_jwt", return_value="jwt"), \
             patch("app.services.github_integration_service.get_installation", return_value={
                 "id": 123,
                 "account": {"login": "example-org", "type": "Organization"},
             }), \
             patch("app.services.github_integration_service.build_installation_url") as install_url:
            authorization_url = self.service.begin_installation("user-one")

        parsed = urlparse(authorization_url)
        self.assertEqual(parsed.path, "/login/oauth/authorize")
        self.assertEqual(parse_qs(parsed.query)["client_id"], ["client-id"])
        install_url.assert_not_called()
        preserved = self.service.repository.get_connection("user-one")
        self.assertEqual(preserved.id, original_row_id)
        self.assertEqual(preserved.installation_id, 123)
        self.assertEqual(preserved.installation_account_login, "example-org")
        self.assertEqual(preserved.installation_account_type, "Organization")
        self.assertEqual(preserved.selected_project_id, "PVT_7")
        self.assertEqual(preserved.connection_status, "pending_user_authorization")

    def test_callback_redirects_to_hash_router_settings(self):
        class Service:
            def complete_installation(self, installation_id, state):
                self.args = (installation_id, state)
                return {"user_authorization_url": None}

        service = Service()
        with patch.object(settings, "SMARTDESK_FRONTEND_URL", "http://localhost:5173"):
            response = callback(installation_id=123, state="valid-state", service=service)

        self.assertEqual(service.args, (123, "valid-state"))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "http://localhost:5173/#/settings?github=connected",
        )

    def test_project_selection_is_stored_for_correct_user(self):
        self.service.repository.connect("user-one", "octocat", 123)
        with patch.object(self.service, "_token", return_value="token"), \
             patch("app.services.github_integration_service.discover_projects", return_value=[{
            "owner": "example-org", "number": 7,
            "project_id": "PVT_7", "title": "Roadmap",
        }]):
            result = self.service.select_project("user-one", GitHubProjectSelection(
                owner="example-org", project_number=7, project_id="PVT_7", title="Roadmap"
            ))
        self.assertEqual(result["user_id"], "user-one")
        self.assertEqual(result["selected_project_id"], "PVT_7")

    def test_webhook_signature_validation(self):
        body = b'{"action":"edited"}'
        with patch.object(settings, "SMARTDESK_GITHUB_WEBHOOK_SECRET", "webhook-secret"):
            digest = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
            self.assertTrue(self.service.verify_signature(body, f"sha256={digest}"))
            self.assertFalse(self.service.verify_signature(body, "sha256=invalid"))
            self.assertFalse(self.service.verify_signature(body, None))

    def test_disconnect_hides_active_integration_data(self):
        self.service.repository.connect("user-one", "octocat", 123)
        self.service.disconnect("user-one")
        self.assertEqual(self.service.connection_status("user-one")["connection_status"], "disconnected")
        self.assertEqual(self.service.active_tasks("user-one"), [])

    def test_disconnect_then_reconnect_reuses_local_row_and_restores_connection(self):
        self.service.repository.connect("user-one", "octocat", 123)
        self.service.repository.select_project(
            "user-one", "octocat", 7, "PVT_7", "Roadmap"
        )
        original_row_id = self.service.repository.get_connection("user-one").id
        self.service.disconnect("user-one")

        disconnected = self.service.connection_status("user-one")
        self.assertEqual(disconnected["connection_status"], "disconnected")
        self.assertEqual(disconnected["installation_id"], 123)
        self.assertEqual(disconnected["selected_project_id"], "PVT_7")

        with patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk-development"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"), \
             patch("app.services.github_integration_service.create_app_jwt", return_value="jwt"), \
             patch("app.services.github_integration_service.get_installation", return_value={
                 "account": {"login": "octocat", "type": "User"}
             }):
            installation_url = self.service.begin_installation("user-one")
            state = parse_qs(urlparse(installation_url).query)["state"][0]
            reconnected = self.service.complete_installation(456, state)

        self.assertEqual(reconnected["connection_status"], "connected")
        self.assertEqual(reconnected["installation_id"], 456)
        self.assertEqual(reconnected["selected_project_id"], "PVT_7")
        self.assertEqual(
            self.service.repository.get_connection("user-one").id,
            original_row_id,
        )

    def test_organization_installation_uses_authoritative_oauth_user(self):
        raw_state = "install-state"
        self.service.repository.create_state(
            "user-one", hashlib.sha256(raw_state.encode()).hexdigest()
        )
        config = (
            patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"),
            patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk"),
            patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"),
            patch.object(settings, "SMARTDESK_GITHUB_OAUTH_CLIENT_ID", "client-id"),
            patch.object(settings, "SMARTDESK_GITHUB_OAUTH_CLIENT_SECRET", "client-secret"),
            patch.object(settings, "SMARTDESK_GITHUB_USER_CALLBACK_URL", "http://localhost/user-callback"),
            patch("app.services.github_integration_service.create_app_jwt", return_value="jwt"),
            patch("app.services.github_integration_service.get_installation", return_value={
                "account": {"login": "example-org", "type": "Organization"}
            }),
        )
        for item in config:
            item.start()
            self.addCleanup(item.stop)

        staged = self.service.complete_installation(123, raw_state)
        oauth_state = parse_qs(urlparse(staged["user_authorization_url"]).query)["state"][0]
        row = self.service.repository.get_connection("user-one")
        self.assertEqual(row.installation_account_login, "example-org")
        self.assertIsNone(row.github_login)
        self.assertEqual(row.connection_status, "pending_user_authorization")

        with patch("app.services.github_integration_service.exchange_user_code", return_value="user-token"), \
             patch("app.services.github_integration_service.get_authenticated_user", return_value={"login": "octocat"}):
            connected = self.service.complete_user_authorization("code", oauth_state)

        self.assertEqual(connected["github_login"], "octocat")
        self.assertEqual(connected["installation_account_login"], "example-org")
        self.assertEqual(connected["connection_status"], "connected")

    def test_organization_user_callback_redirects_after_authorization(self):
        class Service:
            def complete_user_authorization(self, code, state):
                self.args = (code, state)

        service = Service()
        with patch.object(settings, "SMARTDESK_FRONTEND_URL", "http://localhost:5173"):
            response = user_callback(code="code", state="state", service=service)
        self.assertEqual(service.args, ("code", "state"))
        self.assertEqual(response.status_code, 303)

    def test_personal_installation_preserves_one_step_identity(self):
        raw_state = "personal-state"
        self.service.repository.create_state(
            "user-one", hashlib.sha256(raw_state.encode()).hexdigest()
        )
        with patch.object(settings, "SMARTDESK_GITHUB_APP_ID", "1"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_SLUG", "smartdesk"), \
             patch.object(settings, "SMARTDESK_GITHUB_APP_PRIVATE_KEY", "private-key"), \
             patch("app.services.github_integration_service.create_app_jwt", return_value="jwt"), \
             patch("app.services.github_integration_service.get_installation", return_value={
                 "account": {"login": "octocat", "type": "User"}
             }):
            connected = self.service.complete_installation(123, raw_state)
        self.assertEqual(connected["github_login"], "octocat")
        self.assertEqual(connected["installation_account_login"], "octocat")
        self.assertIsNone(connected["user_authorization_url"])

    def test_webhook_for_unselected_project_is_ignored_without_github_access(self):
        payload = {
            "projects_v2_item": {
                "node_id": "PVTI_unknown",
                "project_node_id": "PVT_unknown",
            }
        }
        with patch.object(self.service, "_token") as token:
            self.service.process_webhook(payload, {"X-GitHub-Event": "projects_v2_item"})

        token.assert_not_called()

    def test_metadata_service_uses_canonical_connected_github_login(self):
        metadata_service = self.service._metadata_service(
            "user-one", "PVT_1", "Rashmi"
        )

        self.assertEqual(metadata_service.connected_github_login, "rashmi")

    def test_setup_project_selector_uses_title_id_and_expected_payload(self):
        html = setup_page()
        self.assertIn("o.textContent=p.title", html)
        self.assertIn("o.value=id", html)
        self.assertIn("loadedProjects.set(id,p)", html)
        self.assertIn(
            "payload={owner:p.owner,project_number:p.number,"
            "project_id:p.project_id??p.id,title:p.title}",
            html,
        )


if __name__ == "__main__":
    unittest.main()
