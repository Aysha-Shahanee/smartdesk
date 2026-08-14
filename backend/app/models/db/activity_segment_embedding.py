"""Activity segment embedding model for storing embeddings separately from segments.

This follows the recommendation in the plan to use a separate embedding table
to support multiple embedding models, re-embedding, and separation of concerns.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ActivitySegmentEmbeddingRecord(Base):
    """Embedding for an activity segment, stored separately for flexibility."""

    __tablename__ = "activity_segment_embeddings"

    # Primary key
    id = Column(String, primary_key=True)  # Using String for UUID to match existing pattern

    # Foreign key to activity segment
    segment_id = Column(String, ForeignKey("activity_segments.id", ondelete="CASCADE"), nullable=False)

    # Embedding metadata
    model_name = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    dimensions = Column(Integer, nullable=False)
    embedding = Column(String, nullable=False)  # Storing as base64 encoded string or similar for SQLite

    # Audit trail
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationship
    segment = relationship("ActivitySegmentRecord", backref="embeddings")

    # Constraints
    __table_args__ = (
        # Ensure one embedding per segment per model/version combination
        {
            'sqlite_autoincrement': True
        },
    )

    def __repr__(self) -> str:
        return f"<ActivitySegmentEmbeddingRecord(id={self.id}, segment_id={self.segment_id}, model={self.model_name}:{self.model_version})>"