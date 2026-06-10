"""VS Code session repository — Phase 9."""

from sqlalchemy.orm import Session

from app.core.time import parse_iso_utc
from app.models.db import VSCodeSessionRecord


class VSCodeSessionRepository:
    """Read-only query helpers for ``vscode_sessions``."""

    def get_foreground_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[VSCodeSessionRecord]:
        """Return completed foreground VS Code sessions in the time window."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_end.isnot(None),
                VSCodeSessionRecord.is_foreground == 1,
                VSCodeSessionRecord.session_start >= from_dt,
                VSCodeSessionRecord.session_start <= to_dt,
            )
            .order_by(VSCodeSessionRecord.session_start)
            .all()
        )

    def get_all_sessions_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[VSCodeSessionRecord]:
        """Return all (foreground + background) completed sessions."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_end.isnot(None),
                VSCodeSessionRecord.session_start >= from_dt,
                VSCodeSessionRecord.session_start <= to_dt,
            )
            .order_by(VSCodeSessionRecord.session_start)
            .all()
        )

    def get_open_sessions_db(
        self,
        db: Session,
        user_id: str,
    ) -> list[VSCodeSessionRecord]:
        """Return all currently open VS Code sessions."""
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_end.is_(None),
            )
            .all()
        )
