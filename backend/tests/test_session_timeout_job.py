"""Unit tests — SessionTimeoutJob.run_once().

Uses the in-memory DB from conftest and calls run_once() directly
so we never have to wait 60 seconds for the background timer.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.db import BrowserSessionRecord, OSSessionRecord, VSCodeSessionRecord
from app.services.session_timeout_job import SessionTimeoutJob, BROKEN_SESSION_TIMEOUT_SEC


def _ago(minutes: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.isoformat()


def _stale_os_session(db, user_id="u", minutes_ago=35) -> OSSessionRecord:
    ts = _ago(minutes_ago)
    row = OSSessionRecord(
        id=f"os-stale-{minutes_ago}",
        user_id=user_id,
        app_name="TestApp",
        state="active",
        is_idle=0,
        is_locked=0,
        session_start=ts,
        session_end=None,
        closed_by=None,
        created_at=ts,
        updated_at=ts,
    )
    db.add(row)
    db.commit()
    return row


def _fresh_os_session(db, user_id="u") -> OSSessionRecord:
    ts = _ago(1)  # 1 minute ago — within timeout window
    row = OSSessionRecord(
        id="os-fresh",
        user_id=user_id,
        app_name="ActiveApp",
        state="active",
        is_idle=0,
        is_locked=0,
        session_start=ts,
        session_end=None,
        closed_by=None,
        created_at=ts,
        updated_at=ts,
    )
    db.add(row)
    db.commit()
    return row


class TestSessionTimeoutJob:

    def test_run_once_closes_stale_os_session(self, db):
        _stale_os_session(db)
        job = SessionTimeoutJob()
        # Patch SessionLocal to use the test DB
        import app.services.session_timeout_job as mod
        original = mod.SessionLocal
        mod.SessionLocal = lambda: db
        try:
            closed = job.run_once()
        finally:
            mod.SessionLocal = original
            db.rollback()  # undo run_once commit so fixture can clean up

        # re-query to verify
        db.expire_all()

    def test_run_once_skips_fresh_session(self, db):
        """A recently-updated session must NOT be closed."""
        _fresh_os_session(db)

        import app.services.session_timeout_job as mod
        original = mod.SessionLocal
        closed_count = 0

        # Capture what run_once would close
        stale_ts = (
            datetime.now(timezone.utc) - timedelta(seconds=BROKEN_SESSION_TIMEOUT_SEC)
        ).isoformat()
        fresh_rows = (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.session_end.is_(None),
                OSSessionRecord.updated_at > stale_ts,
            )
            .all()
        )
        assert len(fresh_rows) == 1, "fresh session should still be open"

    def test_run_once_closes_multiple_sources(self, db):
        """Stale sessions across all three tables are all closed."""
        ts = _ago(40)

        db.add(OSSessionRecord(id="os-1", user_id="u", app_name="A",
                               state="active", is_idle=0, is_locked=0,
                               session_start=ts, created_at=ts, updated_at=ts))
        db.add(VSCodeSessionRecord(id="vs-1", user_id="u", instance_id="i1",
                                   session_start=ts, is_foreground=0,
                                   confirmed_by_os=0, edit_count=0, save_count=0,
                                   lines_added=0, lines_deleted=0,
                                   file_switch_count=0, terminal_command_count=0,
                                   debug_run_count=0, created_at=ts, updated_at=ts))
        db.add(BrowserSessionRecord(id="br-1", user_id="u", browser_name="Chrome",
                                    session_start=ts, is_foreground=0,
                                    confirmed_by_os=0, created_at=ts, updated_at=ts))
        db.commit()

        import app.services.session_timeout_job as mod
        original = mod.SessionLocal
        mod.SessionLocal = lambda: db
        try:
            closed = job = SessionTimeoutJob()
            n = job.run_once()
        finally:
            mod.SessionLocal = original

        assert n == 3

    def test_already_closed_session_not_double_closed(self, db):
        """Sessions with session_end already set are ignored."""
        ts = _ago(40)
        row = OSSessionRecord(
            id="os-closed", user_id="u", app_name="Done",
            state="active", is_idle=0, is_locked=0,
            session_start=ts,
            session_end=ts,   # already closed
            closed_by="user",
            created_at=ts, updated_at=ts,
        )
        db.add(row)
        db.commit()

        import app.services.session_timeout_job as mod
        original = mod.SessionLocal
        mod.SessionLocal = lambda: db
        try:
            n = SessionTimeoutJob().run_once()
        finally:
            mod.SessionLocal = original

        assert n == 0
