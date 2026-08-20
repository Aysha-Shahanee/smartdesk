import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import create_registration_token


@pytest.fixture
def app():
    return create_app(Settings("webhook-secret", "client-secret", registration_timeout_seconds=1))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_post(client):
    def post(payload, event="projects_v2_item"):
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        return client.post(
            "/github/webhook",
            content=body,
            headers={"X-Hub-Signature-256": f"sha256={signature}", "X-GitHub-Event": event},
        )
    return post


@pytest.fixture
def token():
    def make(installation_id):
        return create_registration_token(
            installation_id, "client-secret", expires_at=int(time.time()) + 60
        )
    return make


@pytest.fixture
def event():
    def make(installation_id=123):
        return {
            "action": "edited",
            "installation": {"id": installation_id, "extra": "ignored"},
            "projects_v2_item": {
                "node_id": "PVTI_1",
                "project_node_id": "PVT_1",
                "content_node_id": "I_1",
                "title": "must not be forwarded",
            },
        }
    return make

