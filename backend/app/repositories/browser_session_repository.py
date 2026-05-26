"""Browser session repository — Phase 9."""

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
        """Return all completed browser sessions (no foreground/duration filter)."""
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

    def get_open_sessions_db(
        self,
        db: Session,
        user_id: str,
    ) -> list[BrowserSessionRecord]:
        """Return all currently open browser sessions."""
        return (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.is_(None),
            )
            .all()
        )
