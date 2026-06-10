from datetime import datetime, timezone

import pytest

from app.models.schemas.ingest import OSEventPayload, OSEventType
from app.services.session_coordinator import SessionCoordinator


def _ts(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def test_os_session_open_and_close(db_session):
    coordinator = SessionCoordinator()

    start_payload = OSEventPayload(
        user_id="test_user",
        event=OSEventType.FOCUSED,
        app_name="TestApp",
        window_title="Test Window",
        process_id=1234,
        timestamp=_ts(datetime.now(timezone.utc)),
    )

    response = coordinator.handle_os_event(start_payload, db_session)
    assert response.status == "opened"
    assert response.session_id is not None

    # Send another focused event to trigger close of previous session
    next_payload = OSEventPayload(
        user_id="test_user",
        event=OSEventType.FOCUSED,
        app_name="App2",
        window_title="Window 2",
        process_id=5678,
        timestamp=_ts(datetime.now(timezone.utc)),
    )

    response_next = coordinator.handle_os_event(next_payload, db_session)
    assert response_next.status == "opened"


def test_session_start_is_datetime_not_string(db_session):
    """session_start must be stored and returned as a Python datetime object."""
    coordinator = SessionCoordinator()

    payload = OSEventPayload(
        user_id="type_test_user",
        event=OSEventType.FOCUSED,
        app_name="TypeCheckApp",
        window_title="Window",
        process_id=9999,
        timestamp=datetime.now(timezone.utc),
    )
    response = coordinator.handle_os_event(payload, db_session)
    assert response.session_id is not None

    from app.models.db.sessions import OSSessionRecord
    row = db_session.query(OSSessionRecord).filter_by(id=response.session_id).first()
    assert row is not None
    assert isinstance(row.session_start, datetime), (
        f"session_start should be datetime, got {type(row.session_start)}"
    )
    assert isinstance(row.created_at, datetime), (
        f"created_at should be datetime, got {type(row.created_at)}"
    )
    assert isinstance(row.updated_at, datetime), (
        f"updated_at should be datetime, got {type(row.updated_at)}"
    )


def test_timezone_aware_input_accepted(db_session):
    """Timestamps with +05:30 offset are accepted and stored as UTC."""
    from datetime import timezone, timedelta
    colombo = timezone(timedelta(hours=5, minutes=30))
    ts_colombo = datetime(2026, 6, 6, 10, 0, 0, tzinfo=colombo)

    coordinator = SessionCoordinator()
    payload = OSEventPayload(
        user_id="tz_test_user",
        event=OSEventType.FOCUSED,
        app_name="TZApp",
        window_title="TZ Window",
        process_id=1111,
        timestamp=ts_colombo,
    )
    response = coordinator.handle_os_event(payload, db_session)
    assert response.status == "opened"

    from app.models.db.sessions import OSSessionRecord
    row = db_session.query(OSSessionRecord).filter_by(id=response.session_id).first()
    assert row is not None
    assert isinstance(row.session_start, datetime)
    # _dt() normalises to UTC before storing.
    # SQLite returns naive datetimes; treat them as UTC (that's what we stored).
    stored_naive = row.session_start
    stored_utc = stored_naive.replace(tzinfo=timezone.utc) if stored_naive.tzinfo is None else stored_naive.astimezone(timezone.utc)
    # 10:00 +05:30 == 04:30 UTC
    assert stored_utc.hour == 4
    assert stored_utc.minute == 30


def test_session_duration_computed_correctly(db_session):
    """Duration in seconds is correct even when close timestamp > open timestamp."""
    from datetime import timedelta
    t0 = datetime(2026, 6, 6, 8, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=90)

    coordinator = SessionCoordinator()

    open_payload = OSEventPayload(
        user_id="dur_user",
        event=OSEventType.FOCUSED,
        app_name="App",
        window_title="W",
        process_id=42,
        timestamp=t0,
    )
    coordinator.handle_os_event(open_payload, db_session)

    # Closing is triggered by a second FOCUSED event
    close_payload = OSEventPayload(
        user_id="dur_user",
        event=OSEventType.FOCUSED,
        app_name="App2",
        window_title="W2",
        process_id=43,
        timestamp=t1,
    )
    coordinator.handle_os_event(close_payload, db_session)

    from app.models.db.sessions import OSSessionRecord
    closed = (
        db_session.query(OSSessionRecord)
        .filter_by(user_id="dur_user", app_name="App")
        .first()
    )
    assert closed is not None
    assert closed.duration_sec == 90
    assert isinstance(closed.session_end, datetime)
