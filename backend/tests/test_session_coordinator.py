"""Unit tests — SessionCoordinator.

Tests the open/close lifecycle and PID-based foreground matching
without a real HTTP server — just the coordinator + in-memory DB.
"""
from datetime import datetime, timezone

import pytest

from app.models.schemas.ingest import (
    BrowserEventPayload,
    BrowserEventType,
    OSEventPayload,
    OSEventType,
    VSCodeCounters,
    VSCodeEventPayload,
    VSCodeEventType,
)
from app.services.session_coordinator import SessionCoordinator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(s: str = "2026-01-01T10:00:00Z") -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


coordinator = SessionCoordinator()


# ── OS session tests ───────────────────────────────────────────────────────

class TestOSSessionLifecycle:

    def test_focused_opens_session(self, db):
        payload = OSEventPayload(
            user_id="test_user",
            event=OSEventType.FOCUSED,
            timestamp=_ts("2026-01-01T10:00:00Z"),
            app_name="Code",
            app_category="IDE",
            process_id=1234,
        )
        resp = coordinator.handle_os_event(payload, db)
        db.commit()

        assert resp.status == "opened"
        assert resp.session_id is not None

    def test_second_focused_closes_first(self, db):
        t1 = _ts("2026-01-01T10:00:00Z")
        t2 = _ts("2026-01-01T10:05:00Z")

        r1 = coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                           timestamp=t1, app_name="Chrome", process_id=100),
            db,
        )
        db.commit()

        r2 = coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                           timestamp=t2, app_name="Code", process_id=200),
            db,
        )
        db.commit()

        # Different session IDs
        assert r1.session_id != r2.session_id
        assert r2.status == "opened"

    def test_idle_start_marks_state(self, db):
        coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                           timestamp=_ts("2026-01-01T10:00:00Z"),
                           app_name="Code", process_id=1),
            db,
        )
        db.commit()

        resp = coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.IDLE_START,
                           timestamp=_ts("2026-01-01T10:02:00Z")),
            db,
        )
        db.commit()
        assert resp.status == "state_updated"

    def test_shutdown_closes_session(self, db):
        coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                           timestamp=_ts("2026-01-01T10:00:00Z"),
                           app_name="Code", process_id=1),
            db,
        )
        db.commit()

        resp = coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.SHUTDOWN,
                           timestamp=_ts("2026-01-01T10:10:00Z")),
            db,
        )
        db.commit()
        assert resp.status == "closed_by_os_signal"

    def test_blurred_ignored(self, db):
        resp = coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.BLURRED,
                           timestamp=_ts()),
            db,
        )
        assert resp.status == "ignored"
        assert resp.accepted is True

    def test_focused_without_app_name_raises(self, db):
        with pytest.raises(ValueError, match="app_name"):
            coordinator.handle_os_event(
                OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                               timestamp=_ts(), app_name=None),
                db,
            )


# ── VS Code session tests ──────────────────────────────────────────────────

class TestVSCodeSessionLifecycle:

    def _started(self, db, instance="inst-1", t="2026-01-01T10:00:00Z"):
        return coordinator.handle_vscode_event(
            VSCodeEventPayload(
                user_id="u", event=VSCodeEventType.STARTED,
                instance_id=instance, timestamp=_ts(t),
                workspace_name="myproject", active_language="python",
            ),
            db,
        )

    def _ended(self, db, instance="inst-1", t="2026-01-01T10:30:00Z"):
        return coordinator.handle_vscode_event(
            VSCodeEventPayload(
                user_id="u", event=VSCodeEventType.ENDED,
                instance_id=instance, timestamp=_ts(t),
                counters=VSCodeCounters(edit_count=10, save_count=3,
                                        lines_added=50, lines_deleted=5),
            ),
            db,
        )

    def test_started_opens_session(self, db):
        resp = self._started(db)
        db.commit()
        assert resp.status == "opened"
        assert resp.session_id is not None

    def test_ended_closes_session(self, db):
        r1 = self._started(db)
        db.commit()
        r2 = self._ended(db)
        db.commit()
        assert r2.status == "closed"
        assert r2.session_id == r1.session_id

    def test_counters_stored_on_end(self, db):
        from app.models.db import VSCodeSessionRecord
        self._started(db)
        db.commit()
        self._ended(db)
        db.commit()
        row = db.query(VSCodeSessionRecord).first()
        assert row.edit_count == 10
        assert row.save_count == 3
        assert row.lines_added == 50

    def test_foreground_flag_false_without_os_session(self, db):
        # No OS session → not foreground
        resp = self._started(db)
        db.commit()
        assert resp.is_foreground is False

    def test_foreground_flag_true_with_matching_pid(self, db):
        PID = 9876
        # Open an OS session for that PID first
        coordinator.handle_os_event(
            OSEventPayload(user_id="u", event=OSEventType.FOCUSED,
                           timestamp=_ts("2026-01-01T09:59:00Z"),
                           app_name="Code", process_id=PID),
            db,
        )
        db.commit()

        resp = coordinator.handle_vscode_event(
            VSCodeEventPayload(
                user_id="u", event=VSCodeEventType.STARTED,
                instance_id="inst-fg", timestamp=_ts("2026-01-01T10:00:00Z"),
                process_id=PID,
            ),
            db,
        )
        db.commit()
        assert resp.is_foreground is True


# ── Browser session tests ──────────────────────────────────────────────────

class TestBrowserSessionLifecycle:

    def _started(self, db, tab=1, t="2026-01-01T10:00:00Z"):
        return coordinator.handle_browser_event(
            BrowserEventPayload(
                user_id="u", event=BrowserEventType.STARTED,
                browser_name="Chrome", timestamp=_ts(t),
                browser_window_id=1, tab_id=tab,
                domain="github.com", category="Focused",
            ),
            db,
        )

    def _ended(self, db, tab=1, t="2026-01-01T10:10:00Z"):
        return coordinator.handle_browser_event(
            BrowserEventPayload(
                user_id="u", event=BrowserEventType.ENDED,
                browser_name="Chrome", timestamp=_ts(t),
                browser_window_id=1, tab_id=tab,
            ),
            db,
        )

    def test_started_opens_session(self, db):
        resp = self._started(db)
        db.commit()
        assert resp.status == "opened"

    def test_ended_closes_session(self, db):
        r1 = self._started(db)
        db.commit()
        r2 = self._ended(db)
        db.commit()
        assert r2.status == "closed"
        assert r2.session_id == r1.session_id

    def test_state_event_accepted(self, db):
        resp = coordinator.handle_browser_event(
            BrowserEventPayload(
                user_id="u", event=BrowserEventType.STATE,
                browser_name="Chrome", timestamp=_ts(),
                domain="github.com",
            ),
            db,
        )
        assert resp.status == "state_accepted"
