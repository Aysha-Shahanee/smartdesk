"""Calendar connection resilience.

These cover the failure that actually happened: the refresh token expired,
``_load_credentials`` ran ``disconnect()`` on the way past, and the 15-minute job
went back to skipping at DEBUG level. Nothing above it noticed for eleven days.

The rules being pinned down here:
  * a transient failure never costs the user their connection;
  * a fatal one is recorded and surfaced, not swallowed;
  * neither one silently deletes the token;
  * turning it back on clears the flag.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from google.auth.exceptions import RefreshError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.db import CalendarEventRecord
from app.services import calendar_service as cs
from app.services.calendar_service import CalendarNotConnectedError
from app.services.calendar_service import CalendarReconnectRequiredError
from app.services.calendar_service import CalendarService
from app.services.calendar_service import CalendarSyncTransientError
from app.services.calendar_sync_job import CalendarSyncJob
from app.services.calendar_sync_job import IDLE_POLL_SEC
from app.services.calendar_sync_job import MIN_BACKOFF_SEC

USER = "test_user"


class FakeCredentials:
    """Stands in for google.oauth2.credentials.Credentials."""

    def __init__(self, refresh_error: Exception | None = None):
        self.expired = True
        self.refresh_token = "refresh-token"
        self.expiry = None
        self._refresh_error = refresh_error
        self.refreshed = False

    def refresh(self, _request):
        if self._refresh_error is not None:
            raise self._refresh_error
        self.refreshed = True
        self.expired = False

    def to_json(self):
        return json.dumps({"token": "access-token", "refresh_token": self.refresh_token})


class CalendarConnectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name)

        self._patches = [
            patch.object(settings, "CALENDAR_STORE_DIR", str(self.store)),
            patch.object(settings, "GOOGLE_CLIENT_ID", "client-id"),
            patch.object(settings, "GOOGLE_CLIENT_SECRET", "client-secret"),
        ]
        for p in self._patches:
            p.start()

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[CalendarEventRecord.__table__])
        self.db = sessionmaker(bind=engine)()

        self.service = CalendarService()
        self.token_path = self.store / f"token_{USER}.json"
        self.token_path.write_text(
            json.dumps({"token": "t", "refresh_token": "r"}), encoding="utf-8"
        )

    def tearDown(self):
        self.db.close()
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _load_with(self, error: Exception | None):
        creds = FakeCredentials(error)
        return creds, patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=creds,
        )

    # ---------------------------------------------------------------- #
    # Transient failures                                                 #
    # ---------------------------------------------------------------- #

    def test_transient_refresh_failure_keeps_the_connection(self):
        """A blip at Google's token endpoint must not disconnect anybody."""
        _, patcher = self._load_with(RefreshError("Connection reset by peer"))
        with patcher:
            with self.assertRaises(CalendarSyncTransientError):
                self.service._load_credentials(USER)

        self.assertTrue(self.token_path.exists(), "token was deleted on a transient error")
        self.assertFalse(self.service.needs_reconnect(USER))
        self.assertTrue(self.service.is_connected(USER))
        status = self.service.status(USER, self.db)
        self.assertEqual(status["state"], "degraded")
        self.assertEqual(status["consecutive_failures"], 1)
        # Still collecting: the next tick retries and is expected to succeed.
        self.assertTrue(status["collecting"])

    def test_repeated_transient_failures_are_eventually_escalated(self):
        """An unrecognised permanent error must not retry in silence forever."""
        _, patcher = self._load_with(RefreshError("something we do not recognise"))
        with patcher:
            for _ in range(cs.MAX_TRANSIENT_REFRESH_FAILURES - 1):
                with self.assertRaises(CalendarSyncTransientError):
                    self.service._load_credentials(USER)
            with self.assertRaises(CalendarReconnectRequiredError):
                self.service._load_credentials(USER)

        self.assertTrue(self.service.needs_reconnect(USER))

    # ---------------------------------------------------------------- #
    # Fatal failures                                                     #
    # ---------------------------------------------------------------- #

    def test_expired_refresh_token_flags_reconnect_and_keeps_the_token(self):
        """The exact eleven-day outage: seven-day expiry on a Testing-status app."""
        _, patcher = self._load_with(
            RefreshError("invalid_grant: Token has been expired or revoked.")
        )
        with patcher:
            with self.assertRaises(CalendarReconnectRequiredError):
                self.service._load_credentials(USER)

        self.assertTrue(
            self.token_path.exists(),
            "token file was deleted, erasing the evidence the calendar was ever connected",
        )
        self.assertTrue(self.service.needs_reconnect(USER))

        status = self.service.status(USER, self.db)
        self.assertEqual(status["state"], "needs_reconnect")
        self.assertFalse(status["collecting"])
        self.assertTrue(status["connected"])
        self.assertIn("expired", (status["reconnect_reason"] or "").lower())

    def test_flagged_connection_stops_calling_google(self):
        """Once flagged, retrying is pointless — do not hammer the token endpoint."""
        self.service._mark_reconnect_required(USER, "expired")
        with patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file"
        ) as loader:
            with self.assertRaises(CalendarReconnectRequiredError):
                self.service._load_credentials(USER)
        loader.assert_not_called()

    def test_reconnect_required_is_a_not_connected_error(self):
        """Existing route handlers catch CalendarNotConnectedError; keep that working."""
        self.assertTrue(
            issubclass(CalendarReconnectRequiredError, CalendarNotConnectedError)
        )

    # ---------------------------------------------------------------- #
    # Healthy path and the on/off switch                                 #
    # ---------------------------------------------------------------- #

    def test_successful_refresh_clears_the_failure_count(self):
        self.service._mark_sync_failure(USER, "earlier blip")
        creds, patcher = self._load_with(None)
        with patcher:
            self.service._load_credentials(USER)
        self.assertTrue(creds.refreshed)
        self.assertEqual(self.service.status(USER, self.db)["consecutive_failures"], 0)

    def test_status_reports_collecting_when_healthy(self):
        self.service._mark_sync_success(USER, {"created": 3, "updated": 1})
        status = self.service.status(USER, self.db)
        self.assertEqual(status["state"], "collecting")
        self.assertTrue(status["collecting"])
        self.assertTrue(self.service.is_collecting(USER))

    def test_disconnect_turns_collection_off_but_keeps_events(self):
        """One click off: token gone, state clean, synced events untouched."""
        self.db.add(
            CalendarEventRecord(
                user_id=USER, event_id="evt-1", created_at="2026-08-19T10:00:00+05:30",
                updated_at="2026-08-19T10:00:00+05:30",
            )
        )
        self.db.commit()
        self.service._mark_sync_success(USER, {"created": 1})

        self.service.disconnect(USER)

        self.assertFalse(self.token_path.exists())
        self.assertFalse(self.service.is_connected(USER))
        self.assertFalse(self.service.needs_reconnect(USER))
        status = self.service.status(USER, self.db)
        self.assertEqual(status["state"], "disconnected")
        self.assertEqual(status["event_count"], 1, "synced events must survive a disconnect")

    def test_reconnecting_clears_a_previous_expiry(self):
        """One click on, after an expiry, must leave no trace of the old failure."""
        self.service._mark_reconnect_required(USER, "expired")
        self.assertTrue(self.service.needs_reconnect(USER))

        state = "state-token"
        cs._write_json(
            cs._oauth_state_file(),
            {state: {"user_id": USER, "code_verifier": "verifier"}},
        )

        flow = MagicMock()
        flow.credentials = FakeCredentials(None)
        flow.credentials.refresh_token = "fresh-refresh-token"
        with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
            returned = self.service.handle_oauth_callback(state, "auth-code")

        self.assertEqual(returned, USER)
        self.assertFalse(self.service.needs_reconnect(USER))
        self.assertTrue(self.service.is_collecting(USER))
        self.assertEqual(self.service.status(USER, self.db)["state"], "collecting")


class CalendarSyncJobTests(unittest.TestCase):
    """The job must keep its own schedule alive under every outcome."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(settings, "CALENDAR_STORE_DIR", self._tmp.name)
        self._patch.start()
        self.job = CalendarSyncJob(user_id=USER)

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_idles_instead_of_stopping_when_not_connected(self):
        with patch.object(self.job._service, "is_configured", return_value=True), \
             patch.object(self.job._service, "is_connected", return_value=False):
            delay = self.job._tick()
        self.assertEqual(delay, IDLE_POLL_SEC)
        # A short idle poll is what lets a reconnect resume collection by itself.
        self.assertLess(delay, self.job._interval_sec)

    def test_idles_while_awaiting_reconnect(self):
        with patch.object(self.job._service, "is_configured", return_value=True), \
             patch.object(self.job._service, "is_connected", return_value=True), \
             patch.object(self.job._service, "needs_reconnect", return_value=True), \
             patch.object(self.job._service, "sync") as sync:
            delay = self.job._tick()
        sync.assert_not_called()
        self.assertEqual(delay, IDLE_POLL_SEC)

    def test_transient_failure_backs_off_then_recovers(self):
        with patch.object(self.job._service, "is_configured", return_value=True), \
             patch.object(self.job._service, "is_connected", return_value=True), \
             patch.object(self.job._service, "needs_reconnect", return_value=False), \
             patch.object(self.job._service, "sync",
                          side_effect=CalendarSyncTransientError("offline")):
            first = self.job._tick()
            second = self.job._tick()

        self.assertEqual(first, MIN_BACKOFF_SEC)
        self.assertEqual(second, MIN_BACKOFF_SEC * 2, "backoff should grow, not stall")

        with patch.object(self.job._service, "is_configured", return_value=True), \
             patch.object(self.job._service, "is_connected", return_value=True), \
             patch.object(self.job._service, "needs_reconnect", return_value=False), \
             patch.object(self.job._service, "sync", return_value={"created": 0}):
            delay = self.job._tick()
        self.assertEqual(delay, self.job._interval_sec, "backoff should reset on success")

    def test_an_unexpected_error_still_returns_a_next_delay(self):
        """The old chain lost its schedule on any unhandled path. This one cannot."""
        with patch.object(self.job._service, "is_configured", return_value=True), \
             patch.object(self.job._service, "is_connected", return_value=True), \
             patch.object(self.job._service, "needs_reconnect", return_value=False), \
             patch.object(self.job._service, "sync", side_effect=RuntimeError("boom")):
            delay = self.job._tick()
        self.assertEqual(delay, self.job._interval_sec)


if __name__ == "__main__":
    unittest.main()
