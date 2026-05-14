"""OS session repository — Phase 9.

Provides data-access methods for the ``os_sessions`` table that are used
by the Dashboard service.  All date parameters are ISO 8601 strings with
timezone information.
"""

from sqlalchemy.orm import Session

from app.models.db import OSSessionRecord


class OSSessionRepository:
    """Read-only query helpers for ``os_sessions``."""

    def get_completed_sessions(
        self,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[OSSessionRecord]:
        """Return all closed sessions that started within [from_iso, to_iso].

        ``session_end IS NOT NULL`` ensures only completed sessions are returned;
        the current open session is excluded so totals are not inflated.
        """
        raise NotImplementedError("Requires a db session — use get_completed_sessions_db()")

    def get_completed_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[OSSessionRecord]:
        return (
            db.query(OSSessionRecord)
            .filter(
                OSSessionRecord.user_id == user_id,
                OSSessionRecord.session_start >= from_iso,
                OSSessionRecord.session_start <= to_iso,
                OSSessionRecord.session_end.isnot(None),
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
