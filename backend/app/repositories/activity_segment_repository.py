"""Activity segment repository — Phase 10.

Provides data-access methods for the ``activity_segments`` table that are used
by the ActivitySegmentBuilder service and other analytics components.
"""

from sqlalchemy.orm import Session

from app.core.time import is_between_iso
from app.core.time import parse_iso
from app.models.db import ActivitySegmentRecord


class ActivitySegmentRepository:
    """Read-only query helpers for ``activity_segments``."""

    def get_segments_in_timerange(
        self,
        db: Session,
        user_id: str,
        device_id: str,
        from_iso: str,
        to_iso: str,
    ) -> list[ActivitySegmentRecord]:
        """Return activity segments for a user/device in the time range.

        Args:
            db: Database session
            user_id: User identifier
            device_id: Device identifier
            from_iso: Start time in ISO 8601 format
            to_iso: End time in ISO 8601 format

        Returns:
            List of activity segments sorted by start time
        """
        rows = (
            db.query(ActivitySegmentRecord)
            .filter(
                ActivitySegmentRecord.user_id == user_id,
                ActivitySegmentRecord.device_id == device_id,
            )
            .all()
        )
        return sorted(
            [row for row in rows if is_between_iso(row.start_time_utc.isoformat(), from_iso, to_iso)],
            key=lambda row: parse_iso(row.start_time_utc.isoformat()),
        )

    def get_pending_embeddings(
        self,
        db: Session,
        limit: int = 100,
    ) -> list[ActivitySegmentRecord]:
        """Get segments pending embedding generation.

        Args:
            db: Database session
            limit: Maximum number of segments to return

        Returns:
            List of segments with embedding_status = 'pending'
        """
        return (
            db.query(ActivitySegmentRecord)
            .filter(ActivitySegmentRecord.embedding_status == "pending")
            .limit(limit)
            .all()
        )

    def get_pending_sync(
        self,
        db: Session,
        limit: int = 100,
    ) -> list[ActivitySegmentRecord]:
        """Get segments pending synchronization.

        Args:
            db: Database session
            limit: Maximum number of segments to return

        Returns:
            List of segments with sync_status = 'pending'
        """
        return (
            db.query(ActivitySegmentRecord)
            .filter(ActivitySegmentRecord.sync_status == "pending")
            .limit(limit)
            .all()
        )