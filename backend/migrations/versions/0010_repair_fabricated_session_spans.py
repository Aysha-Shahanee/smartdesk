"""repair fabricated session spans

Sessions used to be closed at whatever moment the backend happened to notice
them — the next ``focused`` event, or the timeout job's ``now``.  When the
process was not running, that moment could be hours after the session stopped
being observed, and the entire outage was credited to whichever window was in
front.  For 2026-07-21..28 that inflated ``os_sessions`` from ~81 h to 177.6 h,
including a 17.89 h "active" VS Code block spanning a night during which not one
row was written to any table.

This migration bounds each historical session by the evidence that the observer
was still running: the ``created_at`` / ``updated_at`` stamps written by *other*
session rows.  An end is clamped to the last such stamp inside the session, plus
a grace period.

Grace is deliberately generous (30 min, matching ``BROKEN_SESSION_TIMEOUT_SEC``).
A genuine focus block writes no events at all — someone typing in one window for
20 minutes produces no window switches and no idle transitions — so a short
grace would delete exactly the real work this is meant to protect.  The cost is
that up to 30 min of each outage survives; that is the right way to be wrong.

Original values are preserved in ``extra_data.span_repair`` so the change is
auditable and reversible.

Revision ID: 0010_repair_fabricated_spans
Revises: 0009_create_service_heartbeat
Create Date: 2026-07-28

"""
import bisect
import json
from datetime import datetime, timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010_repair_fabricated_spans'
down_revision: Union[str, Sequence[str], None] = '0009_create_service_heartbeat'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('os_sessions', 'ide_sessions', 'browser_sessions')

# Only spans long enough for an outage to hide in are considered. Anything
# shorter cannot be meaningfully wrong.
MIN_SPAN_SEC = 300

# See module docstring — matches BROKEN_SESSION_TIMEOUT_SEC.
GRACE_SEC = 1800


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def upgrade() -> None:
    conn = op.get_bind()

    # Liveness evidence: every timestamp any session row wrote. Tagged with its
    # origin so a row is never treated as evidence of its own end.
    evidence: list[tuple[str, str, str]] = []
    for table in TABLES:
        for row in conn.execute(sa.text(f"SELECT id, created_at, updated_at FROM {table}")):
            for stamp in (row[1], row[2]):
                if stamp:
                    evidence.append((stamp, table, row[0]))
    evidence.sort()
    stamps = [e[0] for e in evidence]

    def last_evidence_before(start: str, end: str, table: str, row_id: str) -> str | None:
        lo = bisect.bisect_left(stamps, start)
        hi = bisect.bisect_left(stamps, end)
        for k in range(hi - 1, lo - 1, -1):
            if evidence[k][1] == table and evidence[k][2] == row_id:
                continue
            return evidence[k][0]
        return None

    total_repaired = 0
    total_hours_removed = 0.0

    for table in TABLES:
        rows = conn.execute(sa.text(
            f"SELECT id, session_start, session_end, duration_sec, closed_by, extra_data "
            f"FROM {table} "
            f"WHERE session_end IS NOT NULL AND duration_sec >= :min_span"
        ), {"min_span": MIN_SPAN_SEC}).fetchall()

        for row_id, start_s, end_s, duration, closed_by, extra_raw in rows:
            start_dt, end_dt = _parse(start_s), _parse(end_s)
            if start_dt is None or end_dt is None:
                continue

            anchor_s = last_evidence_before(start_s, end_s, table, row_id) or start_s
            anchor_dt = _parse(anchor_s)
            if anchor_dt is None:
                continue

            new_end = min(end_dt, anchor_dt + timedelta(seconds=GRACE_SEC))
            if new_end <= start_dt:
                new_end = start_dt
            new_duration = max(0, int((new_end - start_dt).total_seconds()))
            if new_duration >= (duration or 0):
                continue

            try:
                extra = json.loads(extra_raw) if extra_raw else {}
                if not isinstance(extra, dict):
                    extra = {"_original": extra}
            except (ValueError, TypeError):
                extra = {"_original": extra_raw}
            extra["span_repair"] = {
                "original_session_end": end_s,
                "original_duration_sec": duration,
                "original_closed_by": closed_by,
                "last_evidence_at": anchor_s,
                "grace_sec": GRACE_SEC,
            }

            conn.execute(sa.text(
                f"UPDATE {table} SET session_end = :end, duration_sec = :dur, "
                f"closed_by = 'recovered', updated_at = :end, extra_data = :extra "
                f"WHERE id = :id"
            ), {
                "end": new_end.isoformat(),
                "dur": new_duration,
                "extra": json.dumps(extra, separators=(",", ":"), sort_keys=True),
                "id": row_id,
            })
            total_repaired += 1
            total_hours_removed += ((duration or 0) - new_duration) / 3600.0

    print(
        f"[0010] repaired {total_repaired} session span(s), "
        f"removed {total_hours_removed:.1f} h of unobserved time"
    )


def downgrade() -> None:
    """Restore original spans from the preserved extra_data.span_repair block."""
    conn = op.get_bind()
    for table in TABLES:
        rows = conn.execute(sa.text(
            f"SELECT id, extra_data FROM {table} WHERE closed_by = 'recovered'"
        )).fetchall()
        for row_id, extra_raw in rows:
            try:
                extra = json.loads(extra_raw) if extra_raw else {}
            except (ValueError, TypeError):
                continue
            repair = extra.pop("span_repair", None) if isinstance(extra, dict) else None
            if not repair:
                continue
            conn.execute(sa.text(
                f"UPDATE {table} SET session_end = :end, duration_sec = :dur, "
                f"closed_by = :cb, updated_at = :end, extra_data = :extra WHERE id = :id"
            ), {
                "end": repair["original_session_end"],
                "dur": repair["original_duration_sec"],
                "cb": repair["original_closed_by"],
                "extra": json.dumps(extra, separators=(",", ":"), sort_keys=True) if extra else None,
                "id": row_id,
            })
