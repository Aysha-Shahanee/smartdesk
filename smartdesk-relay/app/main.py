import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .config import Settings
from .connection_manager import ConnectionManager
from .schemas import RegistrationMessage, notification_from_payload
from .security import verify_github_signature, verify_registration_token


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="SmartDesk GitHub Relay", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.connections = ConnectionManager()
    logger = logging.getLogger("smartdesk_relay")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/github/webhook")
    async def github_webhook(request: Request) -> dict[str, object]:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_webhook_bytes:
                    raise HTTPException(status_code=413, detail="Webhook payload too large")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > settings.max_webhook_bytes:
                raise HTTPException(status_code=413, detail="Webhook payload too large")
        if not verify_github_signature(
            bytes(body), request.headers.get("X-Hub-Signature-256"), settings.github_webhook_secret
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Webhook payload must be an object")

        event_name = request.headers.get("X-GitHub-Event", "")
        if event_name != "projects_v2_item":
            return {"accepted": True, "forwarded": 0, "reason": "unsupported_event"}
        try:
            notification = notification_from_payload(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Invalid projects_v2_item payload") from exc
        delivered = await app.state.connections.send(
            notification.installation_id, notification.model_dump()
        )
        if delivered == 0:
            logger.info("No connected client for installation_id=%s", notification.installation_id)
        return {"accepted": True, "forwarded": delivered}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if settings.allowed_origins and origin not in settings.allowed_origins:
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        await websocket.accept()
        installation_id: int | None = None
        try:
            raw = await asyncio.wait_for(
                websocket.receive_json(), timeout=settings.registration_timeout_seconds
            )
            registration = RegistrationMessage.model_validate(raw)
            if not verify_registration_token(
                registration.installation_id,
                registration.token,
                settings.client_auth_secret,
            ):
                await websocket.close(code=1008, reason="Authentication failed")
                return
            installation_id = registration.installation_id
            await app.state.connections.register(installation_id, websocket)
            await websocket.send_json({"type": "registered", "installation_id": installation_id})
            while True:
                await websocket.receive_text()
        except (ValidationError, json.JSONDecodeError, asyncio.TimeoutError):
            await websocket.close(code=1008, reason="Invalid registration")
        except WebSocketDisconnect:
            pass
        finally:
            if installation_id is not None:
                await app.state.connections.disconnect(installation_id, websocket)

    return app


app = create_app()

