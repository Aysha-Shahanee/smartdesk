"""Cached personal baselines.

Written nightly, read into memory once at startup. The table exists so that no
live rule ever computes a percentile: sorting a month of window rows on a
60-second timer would dominate the tick budget, and the answer changes once a
day at most.
"""

from sqlalchemy import Column, Float, Index, Integer, String, UniqueConstraint

from app.core.database import Base


class UserBaselineRecord(Base):
    __tablename__ = "user_baselines"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)

    #: e.g. "run_len", "focus", "daily_active_min", "hour_focus".
    metric = Column(String, nullable=False, index=True)
    #: "" for a global metric; "09" for hour-of-day; "1" for weekday.
    dim_key = Column(String, nullable=False, default="")

    n = Column(Integer, nullable=False, default=0)
    p10 = Column(Float, nullable=False, default=0.0)
    p25 = Column(Float, nullable=False, default=0.0)
    p50 = Column(Float, nullable=False, default=0.0)
    p75 = Column(Float, nullable=False, default=0.0)
    p90 = Column(Float, nullable=False, default=0.0)
    mad = Column(Float, nullable=False, default=0.0)

    computed_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "metric", "dim_key", name="uq_user_baselines_key"),
        Index("idx_user_baselines_user", "user_id", "metric"),
    )
