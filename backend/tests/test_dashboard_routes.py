"""Integration tests — all dashboard endpoints via FastAPI TestClient.

Seeds the in-memory DB with known data, then asserts the
aggregated responses are correct.
"""
from datetime import datetime, timedelta, timezone


FROM = "2026-01-01T00:00:00Z"
TO   = "2026-01-01T23:59:59Z"
USER = "test"


def _seed_os(client):
    """Open + close two OS sessions (github=IDE, youtube=Browser-ish)."""
    for app, cat, pid, t_start, t_end in [
        ("Code", "IDE", 1000, "2026-01-01T09:00:00Z", "2026-01-01T09:30:00Z"),
        ("Chrome", "Browser", 2000, "2026-01-01T10:00:00Z", "2026-01-01T10:15:00Z"),
    ]:
        client.post("/api/v1/ingest/os/event", json={
            "user_id": USER, "event": "focused",
            "timestamp": t_start, "app_name": app,
            "app_category": cat, "process_id": pid,
        })
        client.post("/api/v1/ingest/os/event", json={
            "user_id": USER, "event": "shutdown", "timestamp": t_end,
        })


def _seed_vscode(client):
    # Open an OS session with PID=5000 so the vscode session gets is_foreground=True
    client.post("/api/v1/ingest/os/event", json={
        "user_id": USER, "event": "focused",
        "timestamp": "2026-01-01T08:59:00Z",
        "app_name": "Code", "app_category": "IDE", "process_id": 5000,
    })
    client.post("/api/v1/ingest/vscode/event", json={
        "user_id": USER, "event": "started", "instance_id": "i1",
        "timestamp": "2026-01-01T09:00:00Z",
        "workspace_name": "smartdesk", "active_language": "python",
        "process_id": 5000,
    })
    client.post("/api/v1/ingest/vscode/event", json={
        "user_id": USER, "event": "ended", "instance_id": "i1",
        "timestamp": "2026-01-01T09:30:00Z",
        "counters": {"edit_count": 10, "save_count": 3, "lines_added": 50,
                     "lines_deleted": 5, "file_switch_count": 2,
                     "terminal_command_count": 1, "debug_run_count": 0, "idle_sec": 30},
    })


def _seed_browser(client):
    # Open an OS session with PID=6000 so browser sessions get is_foreground=True
    client.post("/api/v1/ingest/os/event", json={
        "user_id": USER, "event": "focused",
        "timestamp": "2026-01-01T09:59:00Z",
        "app_name": "Chrome", "app_category": "Browser", "process_id": 6000,
    })
    for domain, cat, tab, t_start, t_end in [
        ("github.com", "Focused",      1, "2026-01-01T10:00:00Z", "2026-01-01T10:10:00Z"),
        ("youtube.com", "Distracted",  2, "2026-01-01T10:10:00Z", "2026-01-01T10:15:00Z"),
        ("slack.com", "Communication", 3, "2026-01-01T10:15:00Z", "2026-01-01T10:20:00Z"),
    ]:
        client.post("/api/v1/ingest/browser/event", json={
            "user_id": USER, "event": "started", "browser_name": "Chrome",
            "timestamp": t_start, "browser_window_id": 1,
            "tab_id": tab, "domain": domain, "category": cat,
            "process_id": 6000,
        })
        client.post("/api/v1/ingest/browser/event", json={
            "user_id": USER, "event": "ended", "browser_name": "Chrome",
            "timestamp": t_end, "browser_window_id": 1, "tab_id": tab,
        })


class TestHealthDashboard:

    def test_health_ok(self, client):
        r = client.get("/health/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_ok(self, client):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"
        assert "os_collector" in data["background_jobs"]

    def test_dashboard_status(self, client):
        r = client.get("/dashboard/status")
        assert r.status_code == 200


class TestOSDashboard:

    def test_returns_200_empty(self, client):
        r = client.get(f"/dashboard/os?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        assert "active_time_sec" in data
        assert data["active_time_sec"] == 0

    def test_aggregates_active_time(self, client):
        _seed_os(client)
        r = client.get(f"/dashboard/os?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        # Code session = 30 min = 1800 sec, Chrome = 15 min = 900 sec
        assert data["active_time_sec"] >= 1800
        assert len(data["top_apps"]) >= 1


class TestIDEDashboard:

    def test_returns_200_empty(self, client):
        r = client.get(f"/dashboard/ide?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        assert data["coding_time_sec"] == 0
        assert data["edits"] == 0

    def test_aggregates_coding_stats(self, client):
        _seed_vscode(client)
        r = client.get(f"/dashboard/ide?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        assert data["edits"] == 10
        assert data["saves"] == 3
        assert data["lines_added"] == 50
        top_langs = [item["name"] for item in data["top_languages"]]
        assert "python" in top_langs


class TestBrowserDashboard:

    def test_returns_200_empty(self, client):
        r = client.get(f"/dashboard/browser?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        assert data["browser_active_time_sec"] == 0
        assert data["productive_time_sec"] == 0

    def test_aggregates_all_categories(self, client):
        _seed_browser(client)
        r = client.get(f"/dashboard/browser?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        data = r.json()
        assert data["productive_time_sec"] > 0      # github = Focused
        assert data["distracting_time_sec"] > 0     # youtube = Distracted
        assert data["communication_time_sec"] > 0   # slack = Communication
        domains = [d["name"] for d in data["top_domains"]]
        assert "github.com" in domains


class TestTimelineDashboard:

    def test_returns_200_empty(self, client):
        r = client.get(f"/dashboard/timeline?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        assert "work_periods" in r.json()

    def test_work_periods_is_list(self, client):
        data = client.get(f"/dashboard/timeline?user_id={USER}&from={FROM}&to={TO}").json()
        assert isinstance(data["work_periods"], list)


class TestSessionsDashboard:

    def test_returns_200_empty(self, client):
        r = client.get(f"/dashboard/sessions?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        assert r.json()["sessions"] == []

    def test_all_three_sources_appear(self, client):
        _seed_os(client)
        _seed_vscode(client)
        _seed_browser(client)
        r = client.get(f"/dashboard/sessions?user_id={USER}&from={FROM}&to={TO}")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        sources = {s["source"] for s in sessions}
        assert "os" in sources
        assert "vscode" in sources
        assert "browser" in sources

    def test_sessions_sorted_chronologically(self, client):
        _seed_os(client)
        _seed_browser(client)
        sessions = client.get(
            f"/dashboard/sessions?user_id={USER}&from={FROM}&to={TO}"
        ).json()["sessions"]
        starts = [s["started_at"] for s in sessions]
        assert starts == sorted(starts)

    def test_invalid_date_range_returns_422(self, client):
        r = client.get(f"/dashboard/sessions?user_id={USER}&from=not-a-date&to={TO}")
        assert r.status_code == 422
