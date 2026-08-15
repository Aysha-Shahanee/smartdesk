"""Recommendation engine tables.

Revision ID: 0013_recommendation_engine
Revises: 854bc354074b
Create Date: 2026-08-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_recommendation_engine"
down_revision = "854bc354074b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("action_label", sa.String(), nullable=True),
        sa.Column("based_on", sa.String(), nullable=True),
        sa.Column("facts_json", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("local_date", sa.String(), nullable=False),
        sa.Column("generated_at", sa.String(), nullable=False),
        sa.Column("valid_until", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("status_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'applied', 'dismissed', 'snoozed', 'expired')",
            name="ck_recommendations_status",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_recommendations_severity",
        ),
        sa.CheckConstraint(
            "scope IN ('live', 'daily', 'weekly', 'monthly')",
            name="ck_recommendations_scope",
        ),
    )
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_index("ix_recommendations_rule_id", "recommendations", ["rule_id"])
    op.create_index("ix_recommendations_scope", "recommendations", ["scope"])
    op.create_index("ix_recommendations_section", "recommendations", ["section"])
    op.create_index("ix_recommendations_status", "recommendations", ["status"])
    op.create_index("ix_recommendations_local_date", "recommendations", ["local_date"])
    op.create_index("ix_recommendations_dedup_key", "recommendations", ["dedup_key"])
    # One card per concern per day. The engine also checks in memory, but two
    # producers can run at once (the 60 s job and an on-demand API call), and
    # only the database can arbitrate that race.
    op.create_index(
        "uq_recommendations_dedup_day",
        "recommendations",
        ["user_id", "dedup_key", "local_date"],
        unique=True,
    )
    op.create_index(
        "idx_recommendations_user_status",
        "recommendations",
        ["user_id", "status", "local_date"],
    )

    op.create_table(
        "recommendation_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("recommendation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("seconds_to_action", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "action IN ('applied', 'dismissed', 'snoozed', 'shown', 'expired')",
            name="ck_recommendation_events_action",
        ),
    )
    op.create_index(
        "ix_recommendation_events_rec", "recommendation_events", ["recommendation_id"]
    )
    op.create_index(
        "ix_recommendation_events_user", "recommendation_events", ["user_id"]
    )
    op.create_index(
        "ix_recommendation_events_rule", "recommendation_events", ["rule_id"]
    )

    op.create_table(
        "user_baselines",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("dim_key", sa.String(), nullable=False, server_default=""),
        sa.Column("n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p10", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p25", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p50", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p75", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p90", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mad", sa.Float(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", "metric", "dim_key", name="uq_user_baselines_key"),
    )
    op.create_index("ix_user_baselines_user_id", "user_baselines", ["user_id"])
    op.create_index("ix_user_baselines_metric", "user_baselines", ["metric"])
    op.create_index("idx_user_baselines_user", "user_baselines", ["user_id", "metric"])


def downgrade() -> None:
    op.drop_table("user_baselines")
    op.drop_table("recommendation_events")
    op.drop_table("recommendations")
