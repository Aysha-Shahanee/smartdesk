from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class ActivitySegmentPattern(Base):
    __tablename__ = "activity_segment_patterns"

    id = Column(String, primary_key=True)
    segment_id = Column(String, ForeignKey("activity_segments.id"), nullable=False, index=True)
    cluster_id = Column(Integer, nullable=True, index=True)   # NULL = noise/outlier
    anomaly_score = Column(Float, nullable=False)
    model_version = Column(String, nullable=False, index=True)
    analyzed_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Optional relationship back to the segment (helpful in queries)
    segment = relationship("ActivitySegmentRecord", lazy="joined")

    __table_args__ = (
        Index("idx_patterns_segment_version", "segment_id", "model_version"),
    )