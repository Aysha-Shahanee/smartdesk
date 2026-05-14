"""VS Code session repository — Phase 9."""

from sqlalchemy.orm import Session

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
        """Return completed foreground VS Code sessions in the time window.

        Only ``is_foreground = 1`` sessions are returned so the dashboard
        shows actual active coding time, not background window time.
        """
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_start >= from_iso,
                VSCodeSessionRecord.session_start <= to_iso,
                VSCodeSessionRecord.session_end.isnot(None),
                VSCodeSessionRecord.is_foreground == 1,
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
        return (
            db.query(VSCodeSessionRecord)
            .filter(
                VSCodeSessionRecord.user_id == user_id,
                VSCodeSessionRecord.session_start >= from_iso,
                VSCodeSessionRecord.session_start <= to_iso,
                VSCodeSessionRecord.session_end.isnot(None),
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
