"""Recommendation storage.

Nothing here is ever deleted. A dismissed recommendation is as much training
data as an applied one, and the ranker in Phase 6 learns from exactly that
contrast — the same reasoning that keeps ``activity_segment_labels`` around
after the categoriser has trained on them.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class RecommendationRecord(Base):
    __tablename__ = "recommendations"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    device_id = Column(String, nullable=True)

    rule_id = Column(String, nullable=False, index=True)
    rule_version = Column(Integer, nullable=False, default=1)
    scope = Column(String, nullable=False, index=True)
    section = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False)

    # The rendered copy. Stored rather than re-rendered on read so that a card
    # the user saw yesterday still says what it said yesterday, even after a
    # template is reworded.
    title = Column(String, nullable=False)
    why = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    action_label = Column(String, nullable=True)
    based_on = Column(String, nullable=True)

    # The facts behind the copy, and the evidence behind the facts. Keeping
    # both makes a claim auditable months later without re-deriving it.
    facts_json = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)

    score = Column(Float, nullable=False, default=0.0)
    dedup_key = Column(String, nullable=False, index=True)

    local_date = Column(String, nullable=False, index=True)
    generated_at = Column(String, nullable=False)
    valid_until = Column(String, nullable=True)

    status = Column(String, nullable=False, default="active", index=True)
    status_at = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'applied', 'dismissed', 'snoozed', 'expired')",
            name="ck_recommendations_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_recommendations_severity",
        ),
        CheckConstraint(
            "scope IN ('live', 'daily', 'weekly', 'monthly')",
            name="ck_recommendations_scope",
        ),
        # The dedup guard, enforced by the database rather than only by the
        # engine's in-memory check: two processes generating at once (the live
        # job and an on-demand API call) would otherwise both pass the check
        # and both insert.
        Index(
            "uq_recommendations_dedup_day",
            "user_id", "dedup_key", "local_date",
            unique=True,
        ),
        Index("idx_recommendations_user_status", "user_id", "status", "local_date"),
        # Answers the engine's cooldown question — "when did this rule last fire
        # for this user?" — from the index alone, with generated_at already
        # ordered for the MAX.
        Index(
            "idx_recommendations_user_rule_time",
            "user_id", "rule_id", "generated_at",
        ),
    )


class RecommendationEventRecord(Base):
    """One user interaction with a recommendation — the ranker's training set."""

    __tablename__ = "recommendation_events"

    id = Column(String, primary_key=True)
    recommendation_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    rule_id = Column(String, nullable=False, index=True)

    action = Column(String, nullable=False)
    # Context at the moment of the press, so the ranker can learn that a break
    # prompt lands at 15:00 and is dismissed at 09:00 without re-deriving it.
    hour_of_day = Column(Integer, nullable=True)
    weekday = Column(Integer, nullable=True)
    seconds_to_action = Column(Integer, nullable=True)

    created_at = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "action IN ('applied', 'dismissed', 'snoozed', 'shown', 'expired')",
            name="ck_recommendation_events_action",
        ),
    )
