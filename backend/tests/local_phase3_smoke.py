"""End-to-end Phase 3 smoke test with mock authoritative GitHub responses."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
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
    relay_env = os.environ.copy()
    relay_env.update({
        "SMARTDESK_RELAY_GITHUB_WEBHOOK_SECRET": "phase3-smoke-webhook",
        "SMARTDESK_RELAY_CLIENT_AUTH_SECRET": "phase3-smoke-client",
    })
    relay_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(relay_port), "--log-level", "warning"],
        cwd=repository_root / "smartdesk-relay",
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

        import app.main as backend_main
        from app.core.config import Settings
        from app.services.relay_client import RelayClientService
        from tests.test_github_relay_processing import RelayProcessingHarness

        harness = RelayProcessingHarness()
        harness.states.upsert("PVTI_phase3", "PVT_1", "Todo", "NOT_STARTED")

        def process(notification):
            return harness.dispatch(
                item_id=notification.project_item_node_id,
                project_id=notification.project_node_id,
            )

        relay_settings = Settings(
            SMARTDESK_GITHUB_MONITOR_MODE="relay",
            SMARTDESK_RELAY_URL=f"ws://127.0.0.1:{relay_port}/ws",
            SMARTDESK_RELAY_CLIENT_AUTH_SECRET="phase3-smoke-client",
            SMARTDESK_RELAY_RECONNECT_MIN_SECONDS=0.05,
            SMARTDESK_RELAY_RECONNECT_MAX_SECONDS=0.1,
        )
        backend_main._relay_client = RelayClientService(
            relay_settings, lambda _: 123, notification_handler=process
        )

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

        with TestClient(backend_main.app):
            for _ in range(100):
                if backend_main._relay_client.snapshot()["state"] == "connected":
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("SmartDesk relay client did not register")

            payload = {
                "action": "edited",
                "installation": {"id": 123},
                "projects_v2_item": {
                    "node_id": "PVTI_phase3",
                    "project_node_id": "PVT_1",
                    "content_node_id": "I_1",
                },
            }
            body = json.dumps(payload, separators=(",", ":")).encode()
            signature = hmac.new(
                b"phase3-smoke-webhook", body, hashlib.sha256
            ).hexdigest()
            for expected_receipts in (1, 2):
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
                    if backend_main._relay_client.snapshot()["received_count"] == expected_receipts:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("SmartDesk did not process the relay notification")

            assert len(harness.lifecycles()) == 1
            assert len(harness.predictions()) == 1
            assert harness.predictor.calls == 1
            assert "PVTI_phase3" in harness.active.rows
        print("Local Phase 3 relay -> lifecycle -> prediction smoke test passed")
    finally:
        relay_process.terminate()
        try:
            relay_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            relay_process.kill()
            relay_process.wait(timeout=5)


if __name__ == "__main__":
    main()
