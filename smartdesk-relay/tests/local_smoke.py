"""Start a real local server and verify health -> WebSocket -> signed webhook."""

import asyncio
import hashlib
import hmac
import json
import socket
import threading
import time

import httpx
import uvicorn
import websockets

from app.config import Settings
from app.main import create_app
from app.security import create_registration_token


async def exercise(port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if httpx.get(f"{base_url}/health", timeout=0.2).json() == {"status": "ok"}:
                break
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(0.05)
    else:
        raise RuntimeError("Relay did not become healthy")

    installation_id = 123456
    token = create_registration_token(
        installation_id, "smoke-client-secret", expires_at=int(time.time()) + 60
    )
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as websocket:
        await websocket.send(json.dumps({
            "type": "register", "installation_id": installation_id, "token": token
        }))
        assert json.loads(await websocket.recv())["type"] == "registered"
        payload = {
            "action": "edited",
            "installation": {"id": installation_id},
            "projects_v2_item": {
                "node_id": "PVTI_smoke",
                "project_node_id": "PVT_smoke",
                "content_node_id": "I_smoke",
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        digest = hmac.new(b"smoke-webhook-secret", body, hashlib.sha256).hexdigest()
        response = httpx.post(
            f"{base_url}/github/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={digest}",
                "X-GitHub-Event": "projects_v2_item",
            },
        )
        response.raise_for_status()
        assert response.json()["forwarded"] == 1
        message = json.loads(await websocket.recv())
        assert message["project_item_node_id"] == "PVTI_smoke"
        assert "title" not in message


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(Settings("smoke-webhook-secret", "smoke-client-secret"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        asyncio.run(exercise(port))
        print("Local relay smoke test passed")
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
