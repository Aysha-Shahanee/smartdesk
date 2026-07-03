"""Activity segment model for the activity_segments table.

This table combines normalized data from os_sessions, ide_sessions, and
browser_sessions into one unified analytics timeline following the corrected design.
"""

from sqlalchemy import Column, CheckConstraint, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class ActivitySegmentRecord(Base):
    """Activity segment model representing canonical non-overlapping activity segments."""

    __tablename__ = "activity_segments"

    # Primary key
    id = Column(String, primary_key=True)  # Using String for UUID to match existing pattern

    # Identifiers
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=False)
    schema_version = Column(Integer, nullable=False)

    # Timestamps (UTC)
    start_time_utc = Column(DateTime(timezone=True), nullable=False)
    end_time_utc = Column(DateTime(timezone=True), nullable=False)
    duration_sec = Column(Integer, nullable=False)

    # Timezone info for local display
    timezone_name = Column(String, nullable=False)
    local_date = Column(String, nullable=False)  # Stored as YYYY-MM-DD

    # Source traceability
    primary_source = Column(String, nullable=False)
    app_name = Column(String, nullable=True)
    title = Column(String, nullable=True)
    detail = Column(String, nullable=True)
    state = Column(String, nullable=False)

    # Foreign keys to source sessions (nullable)
    os_session_id = Column(String, nullable=True)
    ide_session_id = Column(String, nullable=True)
    browser_session_id = Column(String, nullable=True)

    # Categorization
    category = Column(String, nullable=True)
    category_method = Column(String, nullable=True)
    category_confidence = Column(Float, nullable=True)
    focus_score = Column(Float, nullable=True)

    # Additional context (JSON stored as Text for SQLite compatibility)
    concurrent_json = Column(Text, nullable=True)
    signals_json = Column(Text, nullable=True)

    # Status tracking
    embedding_status = Column(String, nullable=False, default='pending')
    sync_status = Column(String, nullable=False, default='pending')
    synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_attempts = Column(Integer, nullable=False, default=0)
    last_sync_error = Column(Text, nullable=True)
    content_version = Column(Integer, nullable=False, default=1)

    # Audit trails
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Constraints
    __table_args__ = (
        # Exact duplicate prevention
        UniqueConstraint(
            'user_id',
            'device_id',
            'start_time_utc',
            'end_time_utc',
            name='uq_activity_segments_user_device_time'
        ),
        # Time validity
        CheckConstraint('end_time_utc > start_time_utc', name='ck_activity_segments_valid_time'),
        CheckConstraint('duration_sec >= 0', name='ck_activity_segments_duration'),
        # Focus score bounds
        CheckConstraint(
            'focus_score IS NULL OR (focus_score >= 0 AND focus_score <= 1)',
            name='ck_activity_segments_focus'
        ),
        # Category confidence bounds
        CheckConstraint(
            'category_confidence IS NULL OR (category_confidence >= 0 AND category_confidence <= 1)',
            name='ck_activity_segments_category_confidence'
        ),
        # Primary source validation
        CheckConstraint(
            "primary_source IN ('os', 'ide', 'browser', 'synthetic')",
            name='ck_activity_segments_primary_source'
        ),
        # State validation
        CheckConstraint(
            "state IN ('active', 'idle', 'locked', 'gap')",
            name='ck_activity_segments_state'
        ),
        # Category validation
        CheckConstraint(
            "category IS NULL OR category IN ('work', 'learn', 'communication', 'entertainment', 'social_media', 'system', 'meetings', 'other')",
            name='ck_activity_segments_category'
        ),
        # Category method validation
        CheckConstraint(
            "category_method IS NULL OR category_method IN ('rule', 'embedding')",
            name='ck_activity_segments_category_method'
        ),
        # Embedding status validation
        CheckConstraint(
            "embedding_status IN ('pending', 'processing', 'completed', 'failed', 'not_required')",
            name='ck_activity_segments_embedding_status'
        ),
        # Sync status validation
        CheckConstraint(
            "sync_status IN ('pending', 'syncing', 'synced', 'failed')",
            name='ck_activity_segments_sync_status'
        ),
    )

    def __repr__(self) -> str:
        return f"<ActivitySegmentRecord(id={self.id}, user_id={self.user_id}, start={self.start_time_utc}, end={self.end_time_utc})>"