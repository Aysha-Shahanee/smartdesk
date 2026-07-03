"""create activity_segments table

Revision ID: 0006_create_activity_segments_table
Revises: 0005_create_os_browser_summary_table
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_create_activity_segments_table"
down_revision: Union[str, Sequence[str], None] = "0005_create_os_browser_summary_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create activity_segments table
    op.create_table(
        "activity_segments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("start_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("timezone_name", sa.String(), nullable=False),
        sa.Column("local_date", sa.String(), nullable=False),
        sa.Column("primary_source", sa.String(), nullable=False),
        sa.Column("app_name", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("os_session_id", sa.String(), nullable=True),
        sa.Column("ide_session_id", sa.String(), nullable=True),
        sa.Column("browser_session_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("category_method", sa.String(), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=True),
        sa.Column("focus_score", sa.Float(), nullable=True),
        sa.Column("concurrent_json", sa.Text(), nullable=True),
        sa.Column("signals_json", sa.Text(), nullable=True),
        sa.Column("embedding_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("sync_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_time_utc > start_time_utc", name="ck_activity_segments_valid_time"),
        sa.CheckConstraint("duration_sec >= 0", name="ck_activity_segments_duration"),
        sa.CheckConstraint("focus_score IS NULL OR (focus_score >= 0 AND focus_score <= 1)", name="ck_activity_segments_focus"),
        sa.CheckConstraint("category_confidence IS NULL OR (category_confidence >= 0 AND category_confidence <= 1)", name="ck_activity_segments_category_confidence"),
        sa.CheckConstraint("primary_source IN ('os', 'ide', 'browser', 'synthetic')", name="ck_activity_segments_primary_source"),
        sa.CheckConstraint("state IN ('active', 'idle', 'locked', 'gap')", name="ck_activity_segments_state"),
        sa.CheckConstraint("category IS NULL OR category IN ('work', 'learn', 'communication', 'entertainment', 'social_media', 'system', 'meetings', 'other')", name="ck_activity_segments_category"),
        sa.CheckConstraint("category_method IS NULL OR category_method IN ('rule', 'embedding')", name="ck_activity_segments_category_method"),
        sa.CheckConstraint("embedding_status IN ('pending', 'processing', 'completed', 'failed', 'not_required')", name="ck_activity_segments_embedding_status"),
        sa.CheckConstraint("sync_status IN ('pending', 'syncing', 'synced', 'failed')", name="ck_activity_segments_sync_status"),
    )

    # Create indexes
    op.create_index(
        "ix_activity_segments_user_device_time",
        "activity_segments",
        ["user_id", "device_id", "start_time_utc", "end_time_utc"],
        unique=True,
    )
    op.create_index(
        "ix_activity_segments_user_time",
        "activity_segments",
        ["user_id", "start_time_utc"],
    )
    op.create_index(
        "ix_activity_segments_user_category_time",
        "activity_segments",
        ["user_id", "category", "start_time_utc"],
    )
    op.create_index(
        "ix_activity_segments_sync_status_time",
        "activity_segments",
        ["sync_status", "start_time_utc"],
    )
    op.create_index(
        "ix_activity_segments_embedding_status_time",
        "activity_segments",
        ["embedding_status", "start_time_utc"],
    )
    op.create_index(
        "ix_activity_segments_os_session",
        "activity_segments",
        ["os_session_id"],
    )
    op.create_index(
        "ix_activity_segments_ide_session",
        "activity_segments",
        ["ide_session_id"],
    )
    op.create_index(
        "ix_activity_segments_browser_session",
        "activity_segments",
        ["browser_session_id"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_activity_segments_browser_session", table_name="activity_segments")
    op.drop_index("ix_activity_segments_ide_session", table_name="activity_segments")
    op.drop_index("ix_activity_segments_os_session", table_name="activity_segments")
    op.drop_index("ix_activity_segments_embedding_status_time", table_name="activity_segments")
    op.drop_index("ix_activity_segments_sync_status_time", table_name="activity_segments")
    op.drop_index("ix_activity_segments_user_category_time", table_name="activity_segments")
    op.drop_index("ix_activity_segments_user_time", table_name="activity_segments")
    op.drop_index("ix_activity_segments_user_device_time", table_name="activity_segments")

    # Drop table
    op.drop_table("activity_segments")