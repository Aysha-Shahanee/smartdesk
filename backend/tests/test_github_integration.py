import hashlib
import hmac
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.db_models import Base
from app.models.github_integration import GitHubProjectSelection
from app.routes.github_integration import setup_page
from app.services.github_integration_service import GitHubIntegrationService


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.service = GitHubIntegrationService(self.db)

    def tearDown(self):
        self.db.close()

    def test_installation_state_is_single_use_and_binds_local_user(self):
        raw_state = "valid-state"
        self.service.repository.create_state(
            "user-one", hashlib.sha256(raw_state.encode()).hexdigest()
        )
        with patch("app.services.github_integration_service.get_installation", return_value={"account": {"login": "octocat"}}), \
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
