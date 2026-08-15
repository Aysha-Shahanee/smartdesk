from sqlalchemy import CheckConstraint, Column, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class ActivityWindowPatternRecord(Base):
    __tablename__ = "activity_window_patterns"

    id = Column(String, primary_key=True)
    window_id = Column(String, nullable=False, index=True)
    window_start = Column(String, nullable=False, index=True)
    window_end = Column(String, nullable=False)
    scope = Column(String, nullable=False, index=True)
    run_date = Column(String, nullable=False, index=True)
    range_from = Column(DateTime(timezone=True), nullable=False)
    range_to = Column(DateTime(timezone=True), nullable=False)
    cluster_id = Column(Integer, nullable=True, index=True)
    focus_level = Column(String, nullable=True, index=True)
    anomaly_score = Column(Float, nullable=False)
    avg_focus_score = Column(Float, nullable=False)
    work_ratio = Column(Float, nullable=False, default=0.0)
    learn_ratio = Column(Float, nullable=False, default=0.0)
    communication_ratio = Column(Float, nullable=False, default=0.0)
    model_version = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("window_id", "scope", name="uq_activity_window_patterns_window_scope"),
        CheckConstraint("scope IN ('day', 'week', 'month')", name="ck_activity_window_patterns_scope"),
        CheckConstraint(
            "focus_level IS NULL OR focus_level IN ('high_focus', 'low_focus', 'distracted')",
            name="ck_activity_window_patterns_focus_level",
        ),
        Index("idx_activity_window_patterns_scope_date", "scope", "window_start"),
    )
