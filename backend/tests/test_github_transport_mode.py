import asyncio

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.relay_client import RelayClientService


def isolated_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_missing_mode_defaults_to_webhook(monkeypatch):
    monkeypatch.delenv("SMARTDESK_GITHUB_MONITOR_MODE", raising=False)
    assert isolated_settings().SMARTDESK_GITHUB_MONITOR_MODE == "webhook"


def test_invalid_mode_is_rejected_clearly():
    with pytest.raises(ValidationError, match="SMARTDESK_GITHUB_MONITOR_MODE"):
        isolated_settings(SMARTDESK_GITHUB_MONITOR_MODE="invalid")


def test_webhook_mode_does_not_start_relay_even_with_legacy_flag():
    attempted = False

    def connector(*_args, **_kwargs):
        nonlocal attempted
        attempted = True

    service = RelayClientService(
        isolated_settings(
            SMARTDESK_GITHUB_MONITOR_MODE="webhook",
            SMARTDESK_RELAY_ENABLED=True,
            SMARTDESK_RELAY_URL="ws://relay/ws",
            SMARTDESK_RELAY_CLIENT_AUTH_SECRET="secret",
        ),
        lambda _: 123,
        connector,
    )
    service.start()
    assert not attempted
    assert service.snapshot()["state"] == "disabled"


def test_relay_mode_with_complete_configuration_starts_and_stops():
    async def exercise():
        settings = isolated_settings(
            SMARTDESK_GITHUB_MONITOR_MODE="relay",
            SMARTDESK_RELAY_ENABLED=False,
            SMARTDESK_RELAY_URL="ws://relay/ws",
            SMARTDESK_RELAY_CLIENT_AUTH_SECRET="secret",
        )
        service = RelayClientService(settings)
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

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("url", "secret", "expected"),
    [
        ("", "secret", "relay URL is missing"),
        ("ws://relay/ws", "", "authentication secret is missing"),
    ],
)
def test_relay_mode_missing_configuration_fails_safely(url, secret, expected, caplog):
    service = RelayClientService(isolated_settings(
        SMARTDESK_GITHUB_MONITOR_MODE="relay",
        SMARTDESK_RELAY_URL=url,
        SMARTDESK_RELAY_CLIENT_AUTH_SECRET=secret,
    ))
    service.start()
    assert service.snapshot()["state"] == "configuration_error"
    assert expected in caplog.text
    assert secret not in caplog.text if secret else True


def test_mode_is_single_source_of_truth():
    webhook = isolated_settings(
        SMARTDESK_GITHUB_MONITOR_MODE="webhook", SMARTDESK_RELAY_ENABLED=True
    )
    relay = isolated_settings(
        SMARTDESK_GITHUB_MONITOR_MODE="relay", SMARTDESK_RELAY_ENABLED=False
    )
    assert RelayClientService(webhook).snapshot()["state"] == "disabled"
    assert RelayClientService(relay).snapshot()["state"] == "disconnected"
