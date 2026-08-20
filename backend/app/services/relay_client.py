"""Outbound SmartDesk client for the production GitHub relay.

Phase 2 deliberately stops at validating and observing notifications. Nothing
in this module imports or invokes GitHub metadata, lifecycle, or prediction code.
"""

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import websockets

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models.db.github import GitHubConnectionRecord

logger = logging.getLogger("smartdesk.relay_client")


class RelayNotification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: str
    installation_id: int = Field(gt=0)
    project_item_node_id: str = Field(
        min_length=1, max_length=256, pattern=r"^PVTI_[A-Za-z0-9_-]+$"
    )
    project_node_id: str | None = Field(
        default=None, max_length=256, pattern=r"^PVT_[A-Za-z0-9_-]+$"
    )
    content_node_id: str | None = Field(
        default=None, max_length=256, pattern=r"^(?:I|PR|DI)_[A-Za-z0-9_-]+$"
    )
    action: str = Field(min_length=1, max_length=64)


@dataclass
class RelayClientStatus:
    state: str = "disabled"
    connected_installation_id: int | None = None
    received_count: int = 0
    last_project_item_node_id: str | None = None


def current_installation_id(user_id: str) -> int | None:
    db = SessionLocal()
    try:
        row = db.query(GitHubConnectionRecord).filter_by(user_id=user_id).first()
        if row is None or row.connection_status != "connected":
            return None
        value = row.installation_id
        return value if isinstance(value, int) and value > 0 else None
    finally:
        db.close()


def create_registration_token(
    installation_id: int, secret: str, *, expires_at: int
) -> str:
    message = f"v1:{installation_id}:{expires_at}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"v1.{expires_at}.{digest}"


class RelayClientService:
    def __init__(
        self,
        settings: Settings,
        installation_provider: Callable[[str], int | None] = current_installation_id,
        connector: Callable[..., Any] = websockets.connect,
        notification_handler: Callable[[RelayNotification], object] | None = None,
    ) -> None:
        self.settings = settings
        self._installation_provider = installation_provider
        self._connector = connector
        self._notification_handler = notification_handler
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._status = RelayClientStatus(
            state="disabled" if not self._relay_mode_enabled() else "disconnected"
        )

    def _relay_mode_enabled(self) -> bool:
        return self.settings.SMARTDESK_GITHUB_MONITOR_MODE == "relay"

    def snapshot(self) -> dict[str, object]:
        return asdict(self._status)

    def configuration_error(self) -> str | None:
        if not self.settings.SMARTDESK_RELAY_URL:
            return "relay URL is missing"
        if not self.settings.SMARTDESK_RELAY_CLIENT_AUTH_SECRET:
            return "relay client authentication secret is missing"
        parsed = urlsplit(self.settings.SMARTDESK_RELAY_URL)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            return "relay URL must use ws:// or wss://"
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return "relay URL must not contain credentials, query parameters, or fragments"
        if self.settings.SMARTDESK_RELAY_RECONNECT_MIN_SECONDS <= 0:
            return "relay reconnect minimum must be positive"
        if (
            self.settings.SMARTDESK_RELAY_RECONNECT_MAX_SECONDS
            < self.settings.SMARTDESK_RELAY_RECONNECT_MIN_SECONDS
        ):
            return "relay reconnect maximum must be at least the minimum"
        return None

    def start(self) -> None:
        if not self._relay_mode_enabled():
            self._status.state = "disabled"
            return
        error = self.configuration_error()
        if error:
            self._status.state = "configuration_error"
            logger.error("Relay client configuration error: %s", error)
            return
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="smartdesk-relay-client")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status.connected_installation_id = None
        self._status.state = (
            "disabled" if not self._relay_mode_enabled() else "disconnected"
        )

    async def _wait_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def _run(self) -> None:
        delay = self.settings.SMARTDESK_RELAY_RECONNECT_MIN_SECONDS
        while not self._stop_event.is_set():
            installation_id = self._installation_provider(self.settings.DEFAULT_USER_ID)
            if installation_id is None:
                self._status.state = "waiting_for_installation"
                await self._wait_or_stop(delay)
                delay = min(delay * 2, self.settings.SMARTDESK_RELAY_RECONNECT_MAX_SECONDS)
                continue
            connected = False
            try:
                connected = await self._connect_and_listen(installation_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Registration may have succeeded before a later receive-side
                # network failure. That still counts as a successful connect
                # for backoff-reset purposes.
                connected = self._status.state == "connected"
                # Exception text from networking libraries can contain the URL.
                # Log only the state and bounded delay, never credentials/tokens.
                logger.warning("Relay connection unavailable; retrying in %.1f seconds", delay)
            finally:
                self._status.connected_installation_id = None
                if not self._stop_event.is_set():
                    self._status.state = "disconnected"
            if connected:
                delay = self.settings.SMARTDESK_RELAY_RECONNECT_MIN_SECONDS
            await self._wait_or_stop(delay)
            delay = min(delay * 2, self.settings.SMARTDESK_RELAY_RECONNECT_MAX_SECONDS)

    async def _connect_and_listen(self, installation_id: int) -> bool:
        async with self._connector(
            self.settings.SMARTDESK_RELAY_URL,
            open_timeout=self.settings.SMARTDESK_RELAY_CONNECT_TIMEOUT_SECONDS,
        ) as websocket:
            expiry = int(time.time()) + 60
            token = create_registration_token(
                installation_id,
                self.settings.SMARTDESK_RELAY_CLIENT_AUTH_SECRET,
                expires_at=expiry,
            )
            await websocket.send(json.dumps({
                "type": "register",
                "installation_id": installation_id,
                "token": token,
            }, separators=(",", ":")))
            raw_ack = await websocket.recv()
            ack = json.loads(raw_ack)
            if ack != {"type": "registered", "installation_id": installation_id}:
                raise ValueError("relay registration was not acknowledged")
            self._status.state = "connected"
            self._status.connected_installation_id = installation_id
            logger.info("Relay client connected for installation %s", installation_id)
            async for raw_message in websocket:
                notification = self.handle_message(raw_message, installation_id)
                if notification is not None and self._notification_handler is not None:
                    try:
                        await asyncio.to_thread(self._notification_handler, notification)
                    except Exception:
                        # GitHub/API exceptions can contain sensitive request
                        # details. Keep the event retry-safe and log identifiers only.
                        logger.warning(
                            "Relay GitHub notification processing failed for installation %s, item %s",
                            installation_id,
                            notification.project_item_node_id,
                        )
            return True

    def handle_message(
        self, raw_message: object, installation_id: int
    ) -> RelayNotification | None:
        try:
            if not isinstance(raw_message, (str, bytes, bytearray)):
                return None
            payload = json.loads(raw_message)
            notification = RelayNotification.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
            logger.warning("Ignored malformed relay notification")
            return None
        if notification.type != "github_project_item_changed":
            logger.warning("Ignored unsupported relay notification type")
            return None
        if notification.installation_id != installation_id:
            logger.warning("Ignored relay notification for a different installation")
            return None
        self._status.received_count += 1
        self._status.last_project_item_node_id = notification.project_item_node_id
        logger.info(
            "Relay GitHub notification received for installation %s, item %s",
            installation_id,
            notification.project_item_node_id,
        )
        return notification
