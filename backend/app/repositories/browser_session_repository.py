"""Browser session repository — Phase 9."""

from sqlalchemy.orm import Session

from app.core.time import parse_iso_utc
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
        """Return completed foreground browser sessions in the time window."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.isnot(None),
                BrowserSessionRecord.is_foreground == 1,
                BrowserSessionRecord.duration_sec >= min_duration_sec,
                BrowserSessionRecord.session_start >= from_dt,
                BrowserSessionRecord.session_start <= to_dt,
            )
            .order_by(BrowserSessionRecord.session_start)
            .all()
        )

    def get_all_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[BrowserSessionRecord]:
        """Return all completed browser sessions (no foreground/duration filter)."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(BrowserSessionRecord)
            .filter(
                BrowserSessionRecord.user_id == user_id,
                BrowserSessionRecord.session_end.isnot(None),
                BrowserSessionRecord.session_start >= from_dt,
                BrowserSessionRecord.session_start <= to_dt,
            )
            .order_by(BrowserSessionRecord.session_start)
            .all()
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
