"""Browser session repository — Phase 9."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.time import is_between_iso
from app.core.time import parse_iso
from app.models.db import BrowserSessionRecord


class BrowserSessionRepository:
    """Read-only query helpers for ``browser_sessions``."""

    def get_foreground_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
        min_duration_sec: int = 3,
    ) -> list[BrowserSessionRecord]:
        """Return completed foreground browser sessions in the time window.

        Sessions under ``min_duration_sec`` are excluded from duration totals
        (per the 3-second minimum rule in plan.md) so rapid tab-scans do not
        inflate productive/distracted time.
        """
        rows = (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.isnot(None),
                BrowserSessionRecord.is_foreground == 1,
                BrowserSessionRecord.duration_sec >= min_duration_sec,
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
    ) -> list[BrowserSessionRecord]:
        """Return all completed browser sessions (no foreground/duration filter).

        Start-anchored: it answers "which sessions belong to this day".
        Reconstructing a timeline needs ``get_sessions_overlapping_db``.
        """
        rows = (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.isnot(None),
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
    ) -> list[BrowserSessionRecord]:
        """Sessions whose span *intersects* the range, including open ones.

        The segment-builder counterpart to ``get_all_sessions_db``, for the
        same reason the OS and IDE repositories have one: a tab held open
        longer than a build tick has no window containing both its start and
        its close, so start-anchored loading never showed it to the builder.
        """
        return (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_start < to_iso,
                sa.or_(
                    BrowserSessionRecord.session_end.is_(None),
                    BrowserSessionRecord.session_end > from_iso,
                ),
            )
            .order_by(BrowserSessionRecord.session_start)
            .all()
        )
