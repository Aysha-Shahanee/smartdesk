"""IDE session repository."""

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
        """Return all (foreground + background) completed sessions."""
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
