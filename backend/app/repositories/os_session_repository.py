"""OS session repository — Phase 9."""

from sqlalchemy.orm import Session

from app.core.time import parse_iso_utc
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
        """Return all closed sessions that started within [from_iso, to_iso]."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.user_id == user_id,
                OSSessionRecord.session_end.isnot(None),
                OSSessionRecord.session_start >= from_dt,
                OSSessionRecord.session_start <= to_dt,
            )
            .order_by(OSSessionRecord.session_start)
            .all()
        )

    def get_open_session(
        self,
        db: Session,
        user_id: str,
    ) -> OSSessionRecord | None:
        """Return the currently open OS session, if any."""
        return (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.user_id == user_id,
                OSSessionRecord.session_end.is_(None),
            )
            .order_by(OSSessionRecord.session_start.desc())
            .first()
        )
