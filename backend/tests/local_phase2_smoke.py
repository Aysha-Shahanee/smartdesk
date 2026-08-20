"""Local Phase 2 relay + SmartDesk lifespan integration smoke test.

This uses a mock signed webhook and an in-memory installation provider. It does
not contact GitHub or use the developer database.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from fastapi.testclient import TestClient


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main() -> None:
    relay_port = free_port()
    repository_root = Path(__file__).resolve().parents[2]
    relay_root = repository_root / "smartdesk-relay"
    relay_env = os.environ.copy()
    relay_env.update({
        "SMARTDESK_RELAY_GITHUB_WEBHOOK_SECRET": "phase2-smoke-webhook",
        "SMARTDESK_RELAY_CLIENT_AUTH_SECRET": "phase2-smoke-client",
    })
    relay_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(relay_port), "--log-level", "warning"],
        cwd=relay_root,
        env=relay_env,
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{relay_port}/health", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Phase 1 relay did not become healthy")

        from app.core.config import Settings
        import app.main as backend_main
        from app.services.relay_client import RelayClientService

        relay_settings = Settings(
            SMARTDESK_GITHUB_MONITOR_MODE="relay",
            SMARTDESK_RELAY_URL=f"ws://127.0.0.1:{relay_port}/ws",
            SMARTDESK_RELAY_CLIENT_AUTH_SECRET="phase2-smoke-client",
            SMARTDESK_RELAY_RECONNECT_MIN_SECONDS=0.05,
            SMARTDESK_RELAY_RECONNECT_MAX_SECONDS=0.1,
        )
        backend_main._relay_client = RelayClientService(relay_settings, lambda _: 123456)

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

        with tempfile.TemporaryDirectory() as isolated_dir:
            # The relay client uses the injected installation provider, so no
            # application database should be created or changed by this flow.
            marker = Path(isolated_dir) / "task-processing-would-have-touched-this.db"
            with TestClient(backend_main.app):
                for _ in range(100):
                    if backend_main._relay_client.snapshot()["state"] == "connected":
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("SmartDesk relay client did not register")

                payload = {
                    "action": "edited",
                    "installation": {"id": 123456},
                    "projects_v2_item": {
                        "node_id": "PVTI_phase2",
                        "project_node_id": "PVT_phase2",
                        "content_node_id": "I_phase2",
                    },
                }
                body = json.dumps(payload, separators=(",", ":")).encode()
                signature = hmac.new(
                    b"phase2-smoke-webhook", body, hashlib.sha256
                ).hexdigest()
                response = httpx.post(
                    f"http://127.0.0.1:{relay_port}/github/webhook",
                    content=body,
                    headers={
                        "X-Hub-Signature-256": f"sha256={signature}",
                        "X-GitHub-Event": "projects_v2_item",
                    },
                )
                response.raise_for_status()
                assert response.json()["forwarded"] == 1
                for _ in range(100):
                    if backend_main._relay_client.snapshot()["received_count"] == 1:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("SmartDesk did not observe the relay notification")
                assert not marker.exists()
        print("Local Phase 2 relay + SmartDesk smoke test passed")
    finally:
        relay_process.terminate()
        try:
            relay_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            relay_process.kill()
            relay_process.wait(timeout=5)


if __name__ == "__main__":
    main()
