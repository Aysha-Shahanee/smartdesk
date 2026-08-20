"""Webhook-mode smoke: signed direct route with relay inactive."""

import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient


def main() -> None:
    import app.main as backend_main
    from app.core.config import Settings, settings
    from app.routes import github_integration
    from app.services.relay_client import RelayClientService
    from github_data_collection.webhook_handler import handle_github_webhook_event
    from tests.test_github_relay_processing import RelayProcessingHarness

    harness = RelayProcessingHarness()
    harness.states.upsert("PVTI_phase4", "PVT_1", "Todo", "NOT_STARTED")
    backend_main._relay_client = RelayClientService(Settings(
        SMARTDESK_GITHUB_MONITOR_MODE="webhook",
        SMARTDESK_RELAY_URL="ws://must-not-connect/ws",
        SMARTDESK_RELAY_CLIENT_AUTH_SECRET="unused",
    ))

    class NoOpJob:
        def start(self):
            pass

        def stop(self):
            pass

    for name in (
        "_timeout_job", "_work_scheduler", "_os_collector", "_calendar_sync_job",
        "_activity_segment_builder", "_recommendation_job",
    ):
        setattr(backend_main, name, NoOpJob())
    backend_main.reconcile_open_sessions = lambda *_: None
    backend_main.get_last_heartbeat = lambda *_: None
    backend_main.emotion.stop_emotion_service_if_running = lambda: None

    class DummySession:
        def rollback(self):
            pass

        def close(self):
            pass

    backend_main.SessionLocal = DummySession
    original_secret = settings.SMARTDESK_GITHUB_WEBHOOK_SECRET
    settings.SMARTDESK_GITHUB_WEBHOOK_SECRET = "phase4-direct-secret"
    backend_main.app.dependency_overrides[github_integration.get_service] = lambda: harness.service

    def shared_handler(payload, headers, token=None, metadata_service=None):
        return handle_github_webhook_event(
            payload,
            headers,
            token=token,
            metadata_service=metadata_service,
            state_repository=harness.states,
            delivery_repository=harness.deliveries,
            status_mapper=harness.mapping,
            status_fetcher=lambda *_: "Doing",
        )

    try:
        payload = {
            "action": "edited",
            "projects_v2_item": {
                "node_id": "PVTI_phase4",
                "project_node_id": "PVT_1",
                "content_node_id": "I_1",
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        digest = hmac.new(
            b"phase4-direct-secret", body, hashlib.sha256
        ).hexdigest()
        with patch(
            "app.services.github_integration_service.handle_github_webhook_event",
            side_effect=shared_handler,
        ), TestClient(backend_main.app) as client:
            assert backend_main._relay_client.snapshot()["state"] == "disabled"
            response = client.post(
                "/api/v1/integrations/github/webhook",
                content=body,
                headers={
                    "X-Hub-Signature-256": f"sha256={digest}",
                    "X-GitHub-Event": "projects_v2_item",
                    "X-GitHub-Delivery": "phase4-direct-1",
                },
            )
            response.raise_for_status()
        assert len(harness.lifecycles()) == 1
        assert len(harness.predictions()) == 1
        assert harness.predictor.calls == 1
        print("Local Phase 4 webhook-mode smoke test passed")
    finally:
        settings.SMARTDESK_GITHUB_WEBHOOK_SECRET = original_secret
        backend_main.app.dependency_overrides.pop(github_integration.get_service, None)


if __name__ == "__main__":
    main()
