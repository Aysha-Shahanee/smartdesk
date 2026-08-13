"""create activity_window_patterns table

Revision ID: 8a11c0d5f3d1
Revises: 2974d3d69875
Create Date: 2026-08-11 10:30:00.000000
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a11c0d5f3d1"
down_revision: Union[str, Sequence[str], None] = "2974d3d69875"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_window_patterns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("window_id", sa.String(), nullable=False),
        sa.Column("window_start", sa.String(), nullable=False),
        sa.Column("window_end", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("run_date", sa.String(), nullable=False),
        sa.Column("range_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("focus_level", sa.String(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("avg_focus_score", sa.Float(), nullable=False),
        sa.Column("work_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("learn_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("communication_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("scope IN ('day', 'week', 'month')", name="ck_activity_window_patterns_scope"),
        sa.CheckConstraint(
            "focus_level IS NULL OR focus_level IN ('high_focus', 'low_focus', 'distracted')",
            name="ck_activity_window_patterns_focus_level",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("window_id", "scope", name="uq_activity_window_patterns_window_scope"),
    )
    op.create_index(op.f("ix_activity_window_patterns_window_id"), "activity_window_patterns", ["window_id"], unique=False)
    op.create_index(op.f("ix_activity_window_patterns_scope"), "activity_window_patterns", ["scope"], unique=False)
    op.create_index(op.f("ix_activity_window_patterns_run_date"), "activity_window_patterns", ["run_date"], unique=False)
    op.create_index(op.f("ix_activity_window_patterns_cluster_id"), "activity_window_patterns", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_activity_window_patterns_focus_level"), "activity_window_patterns", ["focus_level"], unique=False)
    op.create_index(op.f("ix_activity_window_patterns_model_version"), "activity_window_patterns", ["model_version"], unique=False)
    op.create_index("idx_activity_window_patterns_scope_date", "activity_window_patterns", ["scope", "window_start"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_activity_window_patterns_scope_date", table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_model_version"), table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_focus_level"), table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_cluster_id"), table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_run_date"), table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_scope"), table_name="activity_window_patterns")
    op.drop_index(op.f("ix_activity_window_patterns_window_id"), table_name="activity_window_patterns")
    op.drop_table("activity_window_patterns")
