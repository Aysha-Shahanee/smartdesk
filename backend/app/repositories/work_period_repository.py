"""Work period repository — Phases 8 & 9."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import parse_iso_utc, to_utc
from app.models.db import WorkPeriodRecord


class WorkPeriodRepository:
    """Data-access helpers for the ``work_periods`` table."""

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    def get_periods_db(
        self,
        db: Session,
        user_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[WorkPeriodRecord]:
        """Return all work periods whose start falls within [from_iso, to_iso]."""
        from_dt = parse_iso_utc(from_iso)
        to_dt = parse_iso_utc(to_iso)
        return (
            db.query(WorkPeriodRecord)
            .filter(
                WorkPeriodRecord.user_id == user_id,
                WorkPeriodRecord.period_start >= from_dt,
                WorkPeriodRecord.period_start <= to_dt,
            )
            .order_by(WorkPeriodRecord.period_start)
            .all()
        )

    def get_open_period_db(
        self,
        db: Session,
        user_id: str,
    ) -> WorkPeriodRecord | None:
        """Return the currently open (active) work period, if any."""
        return (
            db.query(WorkPeriodRecord)
            .filter(
                WorkPeriodRecord.user_id == user_id,
                WorkPeriodRecord.period_end.is_(None),
            )
            .order_by(WorkPeriodRecord.period_start.desc())
            .first()
        )

    def get_latest_period_db(
        self,
        db: Session,
        user_id: str,
    ) -> WorkPeriodRecord | None:
        """Return the most recent work period (open or closed)."""
        return (
            db.query(WorkPeriodRecord)
            .filter(WorkPeriodRecord.user_id == user_id)
            .order_by(WorkPeriodRecord.period_start.desc())
            .first()
        )

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    def open_period_db(
        self,
        db: Session,
        user_id: str,
        period_start: datetime,
        now_dt: datetime,
    ) -> WorkPeriodRecord:
        """Create and flush a new open work period row."""
        from uuid import uuid4

        now = to_utc(now_dt)
        period = WorkPeriodRecord(
            id=str(uuid4()),
            user_id=user_id,
            period_start=to_utc(period_start),
            period_end=None,
            duration_sec=None,
            has_os_data=0,
            has_vscode_data=0,
            has_browser_data=0,
            has_calendar_data=0,
            primary_source=None,
            created_at=now,
            updated_at=now,
        )
        db.add(period)
        db.flush()
        return period

    def close_period_db(
        self,
        db: Session,
        period: WorkPeriodRecord,
        period_end: datetime,
        duration_sec: int,
        now_dt: datetime,
    ) -> WorkPeriodRecord:
        """Close an open work period."""
        period.period_end = to_utc(period_end)
        period.duration_sec = duration_sec
        period.updated_at = to_utc(now_dt)
        db.flush()
        return period

    def update_flags_db(
        self,
        db: Session,
        period: WorkPeriodRecord,
        has_os: bool,
        has_vscode: bool,
        has_browser: bool,
        has_calendar: bool,
        primary_source: str | None,
        now_dt: datetime,
    ) -> None:
        """Update source-availability flags on an open period."""
        period.has_os_data = 1 if has_os else 0
        period.has_vscode_data = 1 if has_vscode else 0
        period.has_browser_data = 1 if has_browser else 0
        period.has_calendar_data = 1 if has_calendar else 0
        period.primary_source = primary_source
        period.updated_at = to_utc(now_dt)
        db.flush()
