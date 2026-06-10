"""Tests for the DateTime column migration.

Verifies that:
  - All timestamp fields return Python datetime objects (not strings).
  - Time-range queries work correctly via SQLAlchemy DateTime comparisons.
  - Timezone-aware inputs (+05:30) are accepted and stored as UTC.
  - work_periods rows store and return datetimes correctly.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.db.sessions import OSSessionRecord, VSCodeSessionRecord, BrowserSessionRecord
from app.models.db.work_period import WorkPeriodRecord
from app.models.db.calendar_event import CalendarEventRecord
from app.models.schemas.ingest import OSEventPayload, OSEventType
from app.services.session_coordinator import SessionCoordinator
from app.repositories.work_period_repository import WorkPeriodRepository
from app.repositories.os_session_repository import OSSessionRepository
from app.repositories.calendar_event_repository import CalendarEventRepository

_UTC = timezone.utc
_COLOMBO = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_os(db, user_id: str, app: str, pid: int, ts: datetime) -> str:
    coord = SessionCoordinator()
    payload = OSEventPayload(
        user_id=user_id, event=OSEventType.FOCUSED,
        app_name=app, window_title=app, process_id=pid, timestamp=ts,
    )
    r = coord.handle_os_event(payload, db)
    db.commit()
    return r.session_id


# ---------------------------------------------------------------------------
# OS session — datetime field types
# ---------------------------------------------------------------------------

class TestOSSessionDatetimeTypes:
    def test_session_start_is_datetime(self, db_session):
        sid = _open_os(db_session, "u1", "App", 1, datetime.now(_UTC))
        row = db_session.query(OSSessionRecord).filter_by(id=sid).first()
        assert isinstance(row.session_start, datetime)

    def test_created_at_is_datetime(self, db_session):
        sid = _open_os(db_session, "u1", "App", 1, datetime.now(_UTC))
        row = db_session.query(OSSessionRecord).filter_by(id=sid).first()
        assert isinstance(row.created_at, datetime)

    def test_updated_at_is_datetime(self, db_session):
        sid = _open_os(db_session, "u1", "App", 1, datetime.now(_UTC))
        row = db_session.query(OSSessionRecord).filter_by(id=sid).first()
        assert isinstance(row.updated_at, datetime)

    def test_session_end_is_datetime_after_close(self, db_session):
        t0 = datetime(2026, 6, 1, 10, 0, 0, tzinfo=_UTC)
        t1 = t0 + timedelta(seconds=60)
        _open_os(db_session, "u_close", "AppA", 10, t0)
        _open_os(db_session, "u_close", "AppB", 11, t1)  # triggers close of AppA

        row = db_session.query(OSSessionRecord).filter_by(
            user_id="u_close", app_name="AppA"
        ).first()
        assert isinstance(row.session_end, datetime)


# ---------------------------------------------------------------------------
# OS session — datetime range query
# ---------------------------------------------------------------------------

class TestOSSessionRangeQuery:
    def test_range_query_returns_sessions_in_window(self, db_session):
        base = datetime(2026, 6, 1, 9, 0, 0, tzinfo=_UTC)
        _open_os(db_session, "rq_user", "EarlyApp", 20, base)
        _open_os(db_session, "rq_user", "InWindowApp", 21, base + timedelta(hours=1))
        _open_os(db_session, "rq_user", "LateApp", 22, base + timedelta(hours=5))

        repo = OSSessionRepository()
        from_iso = (base + timedelta(minutes=30)).isoformat()
        to_iso = (base + timedelta(hours=2)).isoformat()
        results = repo.get_completed_sessions_db(db_session, "rq_user", from_iso, to_iso)

        app_names = {r.app_name for r in results}
        assert "InWindowApp" in app_names
        assert "EarlyApp" not in app_names
        assert "LateApp" not in app_names

    def test_range_query_accepts_colombo_offset(self, db_session):
        # 10:00 +05:30 == 04:30 UTC — _dt() stores this as UTC hour values
        ts_colombo = datetime(2026, 6, 2, 10, 0, 0, tzinfo=_COLOMBO)
        _open_os(db_session, "co_user", "ColombApp", 30, ts_colombo)

        row = db_session.query(OSSessionRecord).filter_by(
            user_id="co_user", app_name="ColombApp"
        ).first()
        assert row is not None
        # SQLite returns naive datetimes; we stored UTC hours so treat it as UTC.
        s = row.session_start
        stored_utc = s.replace(tzinfo=_UTC) if s.tzinfo is None else s.astimezone(_UTC)
        assert stored_utc.hour == 4 and stored_utc.minute == 30


# ---------------------------------------------------------------------------
# WorkPeriod — datetime field types
# ---------------------------------------------------------------------------

class TestWorkPeriodDatetimeTypes:
    def test_open_period_stores_datetime(self, db_session):
        repo = WorkPeriodRepository()
        now = datetime.now(_UTC)
        period = repo.open_period_db(db_session, "wp_user", period_start=now, now_dt=now)
        db_session.commit()

        row = db_session.query(WorkPeriodRecord).filter_by(id=period.id).first()
        assert isinstance(row.period_start, datetime)
        assert isinstance(row.created_at, datetime)
        assert isinstance(row.updated_at, datetime)
        assert row.period_end is None

    def test_close_period_stores_datetime(self, db_session):
        repo = WorkPeriodRepository()
        t0 = datetime(2026, 6, 3, 8, 0, 0, tzinfo=_UTC)
        t1 = t0 + timedelta(minutes=30)

        period = repo.open_period_db(db_session, "wp_close", period_start=t0, now_dt=t0)
        repo.close_period_db(db_session, period, period_end=t1, duration_sec=1800, now_dt=t1)
        db_session.commit()

        row = db_session.query(WorkPeriodRecord).filter_by(id=period.id).first()
        assert isinstance(row.period_end, datetime)
        assert row.duration_sec == 1800

    def test_get_periods_db_range_filter(self, db_session):
        repo = WorkPeriodRepository()
        base = datetime(2026, 6, 4, 6, 0, 0, tzinfo=_UTC)

        early = repo.open_period_db(db_session, "rng_user", period_start=base - timedelta(hours=2), now_dt=base)
        inside = repo.open_period_db(db_session, "rng_user", period_start=base, now_dt=base)
        late = repo.open_period_db(db_session, "rng_user", period_start=base + timedelta(hours=5), now_dt=base)
        db_session.commit()

        from_iso = (base - timedelta(minutes=1)).isoformat()
        to_iso = (base + timedelta(hours=1)).isoformat()
        results = repo.get_periods_db(db_session, "rng_user", from_iso, to_iso)
        ids = {r.id for r in results}
        assert inside.id in ids
        assert early.id not in ids
        assert late.id not in ids


# ---------------------------------------------------------------------------
# CalendarEvent — datetime field types
# ---------------------------------------------------------------------------

class TestCalendarEventDatetimeTypes:
    def test_upsert_stores_datetimes(self, db_session):
        repo = CalendarEventRepository()
        data = {
            "title": "Meeting",
            "start_time": "2026-06-06T09:00:00+05:30",
            "end_time": "2026-06-06T10:00:00+05:30",
            "timezone": "Asia/Colombo",
            "duration_sec": 3600,
            "status": "confirmed",
        }
        row = repo.upsert_event(db_session, "cal_user", "evt_001", data)
        db_session.commit()

        fetched = db_session.query(CalendarEventRecord).filter_by(
            user_id="cal_user", event_id="evt_001"
        ).first()
        assert isinstance(fetched.start_time, datetime)
        assert isinstance(fetched.end_time, datetime)
        assert isinstance(fetched.created_at, datetime)

        # _parse_dt normalises to UTC: 09:00 +05:30 == 03:30 UTC
        # SQLite returns naive; treat it as UTC since that's what we stored.
        s = fetched.start_time
        stored_utc = s.replace(tzinfo=_UTC) if s.tzinfo is None else s.astimezone(_UTC)
        assert stored_utc.hour == 3 and stored_utc.minute == 30

    def test_list_events_range_filter(self, db_session):
        repo = CalendarEventRepository()
        base = datetime(2026, 6, 5, 0, 0, 0, tzinfo=_UTC)

        repo.upsert_event(db_session, "list_user", "early", {
            "start_time": (base - timedelta(hours=2)).isoformat(),
            "end_time": (base - timedelta(hours=1)).isoformat(),
            "status": "confirmed",
        })
        repo.upsert_event(db_session, "list_user", "inside", {
            "start_time": base.isoformat(),
            "end_time": (base + timedelta(hours=1)).isoformat(),
            "status": "confirmed",
        })
        repo.upsert_event(db_session, "list_user", "late", {
            "start_time": (base + timedelta(hours=5)).isoformat(),
            "end_time": (base + timedelta(hours=6)).isoformat(),
            "status": "confirmed",
        })
        db_session.commit()

        results = repo.list_events(
            db_session, "list_user",
            time_min=(base - timedelta(minutes=1)).isoformat(),
            time_max=(base + timedelta(hours=2)).isoformat(),
        )
        event_ids = {r.event_id for r in results}
        assert "inside" in event_ids
        assert "early" not in event_ids
        assert "late" not in event_ids
