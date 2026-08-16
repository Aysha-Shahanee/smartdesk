"""Observer liveness — the bound on how much time a session may claim.

A session's end timestamp used to be whatever moment the backend happened to
notice it (the next ``focused`` event, or the timeout job's ``now``).  When the
process was not running, that moment could be many hours after the session
really stopped being observed, and the whole outage was credited to whichever
window was in front — 123 h of the 177 h recorded for 2026-07-21..28 was time
nobody watched.

The fix is to record when the backend was last alive and refuse to stamp an end
beyond it.  ``SessionTimeoutJob`` beats every ``JOB_INTERVAL_SEC``; a frozen
heartbeat is therefore the moment the observer stopped.
"""

import logging
from datetime import datetime
from datetime import timedelta

from sqlalchemy.orm import Session as DbSession

from app.core.time import ensure_aware
from app.core.time import local_now
from app.core.time import parse_iso
from app.core.time import to_local_iso
from app.models.db import BrowserSessionRecord
from app.models.db import IDESessionRecord
from app.models.db import OSSessionRecord
from app.models.db import ServiceHeartbeatRecord

logger = logging.getLogger("smartdesk.liveness")

# The single row's primary key. One backend, one heartbeat.
HEARTBEAT_ID = "backend"

# How far past the last heartbeat an end may still be stamped.  Must exceed the
# heartbeat interval (60 s) or a live session gets truncated between beats.
LIVENESS_GRACE_SEC: int = 150

# Marks a session whose end was clamped because the observer had stopped. Kept
# distinct from "timeout" so repaired rows stay identifiable after the fact.
CLOSED_BY_RECOVERED = "recovered"


def record_heartbeat(db: DbSession, now: datetime | None = None) -> str:
    """Stamp the backend as alive.  Returns the ISO timestamp written."""
    beat_at = to_local_iso(now or local_now())
    row = db.get(ServiceHeartbeatRecord, HEARTBEAT_ID)
    if row is None:
        db.add(ServiceHeartbeatRecord(id=HEARTBEAT_ID, beat_at=beat_at))
    else:
        row.beat_at = beat_at
    return beat_at


def get_last_heartbeat(db: DbSession) -> datetime | None:
    """The last moment the backend recorded itself alive, or None if never."""
    row = db.get(ServiceHeartbeatRecord, HEARTBEAT_ID)
    if row is None or not row.beat_at:
        return None
    try:
        return parse_iso(row.beat_at)
    except (ValueError, TypeError):
        logger.warning("Unparseable heartbeat value: %r", row.beat_at)
        return None


def clamp_to_liveness(
    proposed_end: datetime,
    last_alive: datetime | None,
    grace_sec: int = LIVENESS_GRACE_SEC,
) -> tuple[datetime, bool]:
    """Bound ``proposed_end`` by how long the observer was actually running.

    Returns ``(end, was_clamped)``.  With no heartbeat on record (a fresh DB, or
    the first run after this change ships) the proposed end is trusted — there
    is no evidence of an outage to act on.
    """
    if last_alive is None:
        return proposed_end, False

    horizon = ensure_aware(last_alive) + timedelta(seconds=grace_sec)
    proposed_end = ensure_aware(proposed_end)
    if proposed_end > horizon:
        return horizon, True
    return proposed_end, False


def reconcile_open_sessions(db: DbSession, last_alive: datetime | None) -> int:
    """Close sessions left open by a previous process lifetime.

    Must run at startup *before* the collector posts its first ``focused``
    event, which would otherwise close them at ``now`` and manufacture the whole
    downtime as activity.  The timeout job cannot do this — it runs on a 60 s
    timer and loses the race.

    Returns the number of sessions closed.
    """
    if last_alive is None:
        logger.info("No prior heartbeat — nothing to reconcile.")
        return 0

    now = local_now()
    closed = 0
    for Model in (OSSessionRecord, IDESessionRecord, BrowserSessionRecord):
        for row in db.query(Model).filter(Model.session_end.is_(None)).all():
            start = parse_iso(row.session_start)
            end, _ = clamp_to_liveness(now, last_alive)
            if end < start:
                end = start
            end_iso = to_local_iso(end)
            row.session_end = end_iso
            row.duration_sec = max(0, int((end - start).total_seconds()))
            row.closed_by = CLOSED_BY_RECOVERED
            row.updated_at = end_iso
            closed += 1

    if closed:
        db.commit()
        logger.info(
            "Reconciled %d session(s) left open by a previous run; "
            "ends clamped to last heartbeat %s.",
            closed,
            to_local_iso(last_alive),
        )
    return closed
