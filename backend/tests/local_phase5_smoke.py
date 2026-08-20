"""Clean-process Task Duration startup smoke for webhook or relay mode."""

import math
import os
import sys

from fastapi.testclient import TestClient


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"webhook", "relay"}:
        raise SystemExit("usage: python -m tests.local_phase5_smoke webhook|relay")
    mode = sys.argv[1]
    os.environ["SMARTDESK_GITHUB_MONITOR_MODE"] = mode
    if mode == "relay":
        # Deliberately unreachable: model readiness must not depend on relay.
        os.environ["SMARTDESK_RELAY_URL"] = "ws://127.0.0.1:9/ws"
        os.environ["SMARTDESK_RELAY_CLIENT_AUTH_SECRET"] = "phase5-smoke-only"

    import app.main as backend_main
    from app.services.github_effort_inference_service import (
        get_github_effort_inference_service,
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
        readiness = backend_main.app.state.github_effort_readiness
        assert readiness["ready"] is True
        assert readiness["feature_count"] == 56
        prediction = get_github_effort_inference_service().predict({
            "title": "Fix production startup failure",
            "description": "Traceback while loading the packaged backend",
            "labels": ["bug", "priority: high"],
            "repository": "microsoft/vscode",
            "started_at": "2026-08-20T10:00:00Z",
        })
        for key in ("low_hours", "typical_hours", "high_hours"):
            assert math.isfinite(prediction[key])
            assert prediction[key] >= 0
    print(f"Local Phase 5 {mode}-mode model startup smoke test passed")


if __name__ == "__main__":
    main()
