"""OS session repository — Phase 9.

Provides data-access methods for the ``os_sessions`` table that are used
by the Dashboard service.  All date parameters are ISO 8601 strings with
timezone information.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.time import is_between_iso
from app.core.time import parse_iso
from app.models.db import OSSessionRecord


class OSSessionRepository:
    """Read-only query helpers for ``os_sessions``."""

    def get_completed_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[OSSessionRecord]:
        """Sessions whose *start* falls in the range.  Used by the dashboard.

        Start-anchored on purpose: the dashboard counts sessions belonging to a
        day.  Do not use this to reconstruct a timeline — see
        ``get_sessions_overlapping_db``.
        """
        rows = (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.user_id == user_id,
                OSSessionRecord.session_end.isnot(None),
            )
            .all()
        )
        return sorted(
            [row for row in rows if is_between_iso(row.session_start, from_iso, to_iso)],
            key=lambda row: parse_iso(row.session_start),
        )

    def get_sessions_overlapping_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[OSSessionRecord]:
        """Sessions whose span *intersects* the range, including still-open ones.

        The segment builder needs overlap, not start-membership.  Selecting by
        start meant a session was only ever visible in the single 5-minute build
        window containing its start — and at that moment it was still open, so
        the ``session_end IS NOT NULL`` filter dropped it.  By the time it
        closed, no window contained its start any more.  The result was that
        only sessions starting *and* ending inside one ~4.5-minute window ever
        became segments: every one of the 2,899 segments ever built came from a
        session under 4.5 minutes, and the longer a block of focus was, the more
        certain it was to be discarded.

        Comparison is lexicographic, which is exact here because every stored
        timestamp is an ISO 8601 string sharing one UTC offset.
        """
        return (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.user_id == user_id,
                OSSessionRecord.session_start < to_iso,
                sa.or_(
                    OSSessionRecord.session_end.is_(None),
                    OSSessionRecord.session_end > from_iso,
                ),
            )
            .order_by(OSSessionRecord.session_start)
            .all()
        )
