"""Activity segment label model for storing user-corrected labels for supervised learning.

This table stores user-provided correct labels along with the embedding vector
used at prediction time to enable supervised learning retraining.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ActivitySegmentLabelRecord(Base):
    """User-corrected label for an activity segment, used for supervised learning."""

    __tablename__ = "activity_segment_labels"

    # Primary key
    id = Column(String, primary_key=True)  # Using String for UUID to match existing pattern

    # Foreign key to activity segment
    segment_id = Column(String, ForeignKey("activity_segments.id", ondelete="CASCADE"), nullable=False)

    # User and device context (for potential future filtering)
    user_id = Column(String, nullable=False)
    device_id = Column(String, nullable=False)

    # Embedding metadata (must match what was used for prediction)
    model_name = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    dimensions = Column(Integer, nullable=False)
    embedding = Column(String, nullable=False)  # Storing as base64 encoded string or similar

    # The correct label provided by the user
    correct_label = Column(String, nullable=False)

    # Where the label came from: 'user' for a correction someone typed,
    # 'backfill' for one derived by a repair script. Both are trained on, but
    # only 'user' rows are evidence of what the user actually meant.
    source = Column(String, nullable=False, server_default="user")

    # Audit trail
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    used_in_training = Column(Integer, nullable=False, server_default="0")  # Use 0 for false, 1 for true

    # Relationship
    segment = relationship("ActivitySegmentRecord", backref="labels")

    def __repr__(self) -> str:
        return f"<ActivitySegmentLabelRecord(id={self.id}, segment_id={self.segment_id}, label='{self.correct_label}')>"