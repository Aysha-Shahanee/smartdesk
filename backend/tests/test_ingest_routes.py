"""Integration tests — all ingest endpoints via FastAPI TestClient."""


class TestIngestStatus:
    def test_status_200(self, client):
        r = client.get("/api/v1/ingest/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ready"
        assert "/api/v1/ingest/os/event" in data["endpoints"]


class TestOSIngest:

    def test_focused_returns_opened(self, client):
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "focused",
            "timestamp": "2026-01-01T10:00:00Z",
            "app_name": "Code", "app_category": "IDE", "process_id": 1234,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "opened"
        assert r.json()["session_id"] is not None

    def test_focused_missing_app_name_returns_400(self, client):
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "focused",
            "timestamp": "2026-01-01T10:00:00Z",
        })
        assert r.status_code == 400

    def test_blurred_returns_ignored(self, client):
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "blurred",
            "timestamp": "2026-01-01T10:00:00Z",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_idle_start_updates_state(self, client):
        client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "focused",
            "timestamp": "2026-01-01T10:00:00Z", "app_name": "Code",
        })
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "idle_start",
            "timestamp": "2026-01-01T10:02:00Z",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "state_updated"

    def test_shutdown_closes_session(self, client):
        client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "focused",
            "timestamp": "2026-01-01T10:00:00Z", "app_name": "Code",
        })
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "shutdown",
            "timestamp": "2026-01-01T10:10:00Z",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "closed_by_os_signal"

    def test_invalid_event_type_returns_422(self, client):
        r = client.post("/api/v1/ingest/os/event", json={
            "user_id": "test", "event": "not_real",
            "timestamp": "2026-01-01T10:00:00Z",
        })
        assert r.status_code == 422

    def test_missing_user_id_returns_422(self, client):
        r = client.post("/api/v1/ingest/os/event", json={
            "event": "focused", "timestamp": "2026-01-01T10:00:00Z", "app_name": "Code",
        })
        assert r.status_code == 422


class TestVSCodeIngest:

    def test_started_returns_opened(self, client):
        r = client.post("/api/v1/ingest/vscode/event", json={
            "user_id": "test", "event": "started",
            "instance_id": "inst-abc", "timestamp": "2026-01-01T10:00:00Z",
            "workspace_name": "smartdesk", "active_language": "python",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "opened"
        assert r.json()["is_foreground"] is False

    def test_ended_with_counters(self, client):
        r1 = client.post("/api/v1/ingest/vscode/event", json={
            "user_id": "test", "event": "started",
            "instance_id": "inst-xyz", "timestamp": "2026-01-01T10:00:00Z",
        })
        r2 = client.post("/api/v1/ingest/vscode/event", json={
            "user_id": "test", "event": "ended",
            "instance_id": "inst-xyz", "timestamp": "2026-01-01T10:30:00Z",
            "counters": {"edit_count": 42, "save_count": 7, "lines_added": 100,
                         "lines_deleted": 20, "file_switch_count": 5,
                         "terminal_command_count": 2, "debug_run_count": 1, "idle_sec": 60},
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "closed"
        assert r2.json()["session_id"] == r1.json()["session_id"]

    def test_missing_instance_id_returns_422(self, client):
        r = client.post("/api/v1/ingest/vscode/event", json={
            "user_id": "test", "event": "started", "timestamp": "2026-01-01T10:00:00Z",
        })
        assert r.status_code == 422


class TestBrowserIngest:

    def test_started_returns_opened(self, client):
        r = client.post("/api/v1/ingest/browser/event", json={
            "user_id": "test", "event": "started",
            "browser_name": "Chrome", "timestamp": "2026-01-01T10:00:00Z",
            "browser_window_id": 1, "tab_id": 42,
            "domain": "github.com", "category": "Focused",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "opened"

    def test_ended_closes_session(self, client):
        r1 = client.post("/api/v1/ingest/browser/event", json={
            "user_id": "test", "event": "started",
            "browser_name": "Chrome", "timestamp": "2026-01-01T10:00:00Z",
            "browser_window_id": 1, "tab_id": 10, "domain": "github.com",
        })
        r2 = client.post("/api/v1/ingest/browser/event", json={
            "user_id": "test", "event": "ended",
            "browser_name": "Chrome", "timestamp": "2026-01-01T10:10:00Z",
            "browser_window_id": 1, "tab_id": 10,
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "closed"
        assert r2.json()["session_id"] == r1.json()["session_id"]

    def test_state_event_accepted(self, client):
        r = client.post("/api/v1/ingest/browser/event", json={
            "user_id": "test", "event": "state",
            "browser_name": "Chrome", "timestamp": "2026-01-01T10:05:00Z",
            "domain": "github.com",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "state_accepted"

    def test_missing_browser_name_returns_422(self, client):
        r = client.post("/api/v1/ingest/browser/event", json={
            "user_id": "test", "event": "started", "timestamp": "2026-01-01T10:00:00Z",
        })
        assert r.status_code == 422


class TestLegacyEndpoints:

    def test_ide_minute_window_returns_410(self, client):
        r = client.post("/api/v1/ide/minute-window", json={})
        assert r.status_code == 410
        assert r.json()["deprecated_endpoint"] is True

    def test_browser_minute_window_returns_410(self, client):
        r = client.post("/api/v1/browser/minute-window", json={})
        assert r.status_code == 410

    def test_os_minute_window_returns_410(self, client):
        r = client.post("/api/v1/os/minute-window", json={})
        assert r.status_code == 410
