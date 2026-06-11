"""OS session repository — Phase 9.

Provides data-access methods for the ``os_sessions`` table that are used
by the Dashboard service.  All date parameters are ISO 8601 strings with
timezone information.
"""

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
