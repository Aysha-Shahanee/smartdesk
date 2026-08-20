import asyncio
import hashlib
import hmac
import json
import logging
import time
from types import SimpleNamespace

from app.core.config import Settings
import app.services.relay_client as relay_client_module
from app.services.relay_client import RelayClientService, create_registration_token


def relay_settings(**overrides):
    values = {
        "SMARTDESK_GITHUB_MONITOR_MODE": "relay",
        "SMARTDESK_RELAY_URL": "ws://127.0.0.1:8080/ws",
        "SMARTDESK_RELAY_CLIENT_AUTH_SECRET": "client-secret",
        "SMARTDESK_RELAY_CONNECT_TIMEOUT_SECONDS": 1,
        "SMARTDESK_RELAY_RECONNECT_MIN_SECONDS": 0.001,
        "SMARTDESK_RELAY_RECONNECT_MAX_SECONDS": 0.004,
    }
    values.update(overrides)
    return Settings(**values)


class FakeSocket:
    def __init__(self, installation_id=123, messages=()):
        self.installation_id = installation_id
        self.messages = list(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return json.dumps({"type": "registered", "installation_id": self.installation_id})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FakeConnection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *args):
        return None


def test_disabled_does_not_attempt_connection():
    attempted = False

    def connector(*args, **kwargs):
        nonlocal attempted
        attempted = True

    service = RelayClientService(
        relay_settings(SMARTDESK_GITHUB_MONITOR_MODE="webhook"), lambda _: 123, connector
    )
    service.start()
    assert not attempted
    assert service.snapshot()["state"] == "disabled"


def test_enabled_missing_url_is_safe_configuration_failure(caplog):
    settings = relay_settings(SMARTDESK_RELAY_URL="")
    service = RelayClientService(settings, lambda _: 123)
    with caplog.at_level(logging.ERROR):
        service.start()
    assert service.snapshot()["state"] == "configuration_error"
    assert settings.SMARTDESK_RELAY_CLIENT_AUTH_SECRET not in caplog.text


def test_phase_one_registration_signature_and_installation_identity():
    socket = FakeSocket(installation_id=456)
    seen_user_ids = []
    service = RelayClientService(
        relay_settings(),
        lambda user_id: seen_user_ids.append(user_id) or 456,
        lambda *args, **kwargs: FakeConnection(socket),
    )
    assert asyncio.run(service._connect_and_listen(456))
    registration = socket.sent[0]
    assert registration.keys() == {"type", "installation_id", "token"}
    assert registration["installation_id"] == 456
    version, expiry, digest = registration["token"].split(".")
    expected = hmac.new(
        b"client-secret", f"v1:456:{expiry}".encode(), hashlib.sha256
    ).hexdigest()
    assert version == "v1" and hmac.compare_digest(digest, expected)
    assert "github_login" not in registration


def test_no_installation_causes_no_registration_attempt():
    async def exercise():
        attempted = False

        def connector(*args, **kwargs):
            nonlocal attempted
            attempted = True

        service = RelayClientService(relay_settings(), lambda _: None, connector)
        waits = []

        async def wait(delay):
            waits.append(delay)
            service._stop_event.set()

        service._wait_or_stop = wait
        await service._run()
        assert not attempted
        assert waits
        assert service.snapshot()["state"] == "waiting_for_installation"

    asyncio.run(exercise())


def test_installation_source_requires_connected_record_and_uses_numeric_id(monkeypatch):
    class Query:
        def __init__(self, row):
            self.row = row

        def filter_by(self, **values):
            assert values == {"user_id": "local_user"}
            return self

        def first(self):
            return self.row

    class Session:
        def __init__(self, row):
            self.row = row

        def query(self, _model):
            return Query(self.row)

        def close(self):
            pass

    connected = SimpleNamespace(
        connection_status="connected", installation_id=321, github_login="not-an-id"
    )
    monkeypatch.setattr(relay_client_module, "SessionLocal", lambda: Session(connected))
    assert relay_client_module.current_installation_id("local_user") == 321
    connected.connection_status = "disconnected"
    assert relay_client_module.current_installation_id("local_user") is None


def test_message_validation_accepts_only_matching_minimal_event(caplog):
    service = RelayClientService(relay_settings())
    valid = json.dumps({
        "type": "github_project_item_changed",
        "installation_id": 123,
        "project_item_node_id": "PVTI_1",
        "project_node_id": "PVT_1",
        "content_node_id": "I_1",
        "action": "edited",
    })
    assert service.handle_message(valid, 123)
    assert service.snapshot()["received_count"] == 1
    assert not service.handle_message(valid.replace('"installation_id": 123', '"installation_id": 456'), 123)
    assert not service.handle_message("not-json", 123)
    assert not service.handle_message(valid.replace("github_project_item_changed", "unknown"), 123)
    assert service.snapshot()["received_count"] == 1
    assert "client-secret" not in caplog.text


def test_registration_token_is_short_lived_and_contains_no_secret():
    expiry = int(time.time()) + 60
    token = create_registration_token(123, "client-secret", expires_at=expiry)
    assert token.startswith(f"v1.{expiry}.")
    assert "client-secret" not in token


def test_retry_backoff_is_bounded_and_temporary_failure_retries():
    async def exercise():
        service = RelayClientService(relay_settings(), lambda _: 123)
        attempts = 0
        waits = []

        async def fail(_installation_id):
            nonlocal attempts
            attempts += 1
            raise OSError("temporary")

        async def wait(delay):
            waits.append(delay)
            if len(waits) == 5:
                service._stop_event.set()

        service._connect_and_listen = fail
        service._wait_or_stop = wait
        await service._run()
        assert attempts == 5
        assert waits == [0.001, 0.002, 0.004, 0.004, 0.004]

    asyncio.run(exercise())


def test_successful_connection_resets_backoff():
    async def exercise():
        service = RelayClientService(relay_settings(), lambda _: 123)
        attempts = 0
        waits = []

        async def connect(_installation_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return False
            service._status.state = "connected"
            raise OSError("connection dropped after registration")

        async def wait(delay):
            waits.append(delay)
            if len(waits) == 2:
                service._stop_event.set()

        service._connect_and_listen = connect
        service._wait_or_stop = wait
        await service._run()
        assert waits == [0.001, 0.001]

    asyncio.run(exercise())


def test_startup_task_is_cancelled_cleanly_on_shutdown():
    async def exercise():
        service = RelayClientService(relay_settings(), lambda _: None)
        entered = asyncio.Event()

        async def run_forever():
            entered.set()
            await asyncio.Event().wait()

        service._run = run_forever
        service.start()
        await entered.wait()
        assert service._task is not None and not service._task.done()
        await service.stop()
        assert service._task is None
        assert service.snapshot()["state"] == "disconnected"

    asyncio.run(exercise())


def test_receipt_does_not_import_or_call_task_processing():
    service = RelayClientService(relay_settings())
    assert service.handle_message(json.dumps({
        "type": "github_project_item_changed",
        "installation_id": 123,
        "project_item_node_id": "PVTI_only",
        "project_node_id": None,
        "content_node_id": None,
        "action": "edited",
    }), 123)
    assert service.snapshot()["last_project_item_node_id"] == "PVTI_only"
