"""IDE session repository."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.time import is_between_iso
from app.core.time import parse_iso
from app.models.db import IDESessionRecord


class IDESessionRepository:
    """Read-only query helpers for ``ide_sessions``."""

    def get_foreground_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[IDESessionRecord]:
        """Return completed foreground IDE sessions in the time window.

        Only ``is_foreground = 1`` sessions are returned so the dashboard
        shows actual active coding time, not background window time.
        """
        rows = (
            db.query(IDESessionRecord)
            .filter(
                IDESessionRecord.user_id == user_id,
                IDESessionRecord.session_end.isnot(None),
                IDESessionRecord.is_foreground == 1,
            )
            .all()
        )
        return sorted(
            [row for row in rows if is_between_iso(row.session_start, from_iso, to_iso)],
            key=lambda row: parse_iso(row.session_start),
        )

    def get_all_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[IDESessionRecord]:
        """Return all (foreground + background) completed sessions.

        Start-anchored, like ``get_completed_sessions_db`` on the OS side: it
        answers "which sessions belong to this day". Reconstructing a timeline
        needs ``get_sessions_overlapping_db`` instead.
        """
        rows = (
            db.query(IDESessionRecord)
            .filter(
                IDESessionRecord.user_id == user_id,
                IDESessionRecord.session_end.isnot(None),
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
    ) -> list[IDESessionRecord]:
        """Sessions whose span *intersects* the range, including open ones.

        The segment builder needs overlap, not start-membership — the same
        distinction ``OSSessionRepository.get_sessions_overlapping_db`` exists
        for, which the IDE side never got. Loading by start meant an IDE
        session was visible only in the one 5-minute build window containing
        its start, and at that moment it was still open, so the
        ``session_end IS NOT NULL`` filter dropped it. Any coding block longer
        than a build tick therefore never reached ``_enrich_with_overlaps``,
        and the segments over it stayed ``primary_source='os'`` with a null
        ``ide_session_id``: on 2026-08-10 only 2185 s of the 6597 s spent in
        the editor was attributed to the IDE, so the Timeline's IDE tab drew
        36 minutes of a 1h50m day.

        Comparison is lexicographic, which is exact here because every stored
        timestamp is an ISO 8601 string sharing one UTC offset.
        """
        return (
            db.query(IDESessionRecord)
            .filter(
                IDESessionRecord.user_id == user_id,
                IDESessionRecord.session_start < to_iso,
                sa.or_(
                    IDESessionRecord.session_end.is_(None),
                    IDESessionRecord.session_end > from_iso,
                ),
            )
            .order_by(IDESessionRecord.session_start)
            .all()
        )
