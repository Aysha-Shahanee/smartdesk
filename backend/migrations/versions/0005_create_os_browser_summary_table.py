"""create os_browser_summary table

Revision ID: 0005_create_os_browser_summary_table
Revises: 4ba685c05c0b
Create Date: 2026-06-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_create_os_browser_summary_table"
down_revision: Union[str, Sequence[str], None] = "4ba685c05c0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "os_browser_summary",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=True),
        sa.Column("parent_os_session_id", sa.String(), nullable=False),
        sa.Column("browser_session_id", sa.String(), nullable=True),
        sa.Column("segment_start", sa.String(), nullable=False),
        sa.Column("segment_end", sa.String(), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("os_app_name", sa.String(), nullable=False),
        sa.Column("os_app_category", sa.String(), nullable=True),
        sa.Column("os_window_title", sa.String(), nullable=True),
        sa.Column("os_process_id", sa.Integer(), nullable=True),
        sa.Column("os_state", sa.String(), nullable=False),
        sa.Column("os_idle_time", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("os_trigger", sa.String(), nullable=True),
        sa.Column("os_closed_by", sa.String(), nullable=True),
        sa.Column("browser_name", sa.String(), nullable=True),
        sa.Column("browser_window_id", sa.Integer(), nullable=True),
        sa.Column("browser_tab_id", sa.Integer(), nullable=True),
        sa.Column("browser_process_id", sa.Integer(), nullable=True),
        sa.Column("browser_domain", sa.String(), nullable=True),
        sa.Column("browser_url", sa.String(), nullable=True),
        sa.Column("browser_title", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("category_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("category_model", sa.String(), nullable=True),
        sa.Column("summary_created_at", sa.String(), nullable=False),
        sa.Column("summary_updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("duration_sec >= 0", name="ck_os_browser_summary_duration_nonneg"),
        sa.CheckConstraint("category_status IN ('pending', 'completed', 'failed')", name="ck_os_browser_summary_category_status"),
    )
    op.create_index(
        "ix_os_browser_summary_user_start",
        "os_browser_summary",
        ["user_id", "segment_start"],
    )
    op.create_index("ix_os_browser_summary_parent_os", "os_browser_summary", ["parent_os_session_id"])
    op.create_index("ix_os_browser_summary_browser_session", "os_browser_summary", ["browser_session_id"])
    op.create_index(
        "ux_os_browser_summary_os_only",
        "os_browser_summary",
        ["parent_os_session_id", "segment_start", "segment_end"],
        unique=True,
        postgresql_where=sa.text("browser_session_id IS NULL"),
        sqlite_where=sa.text("browser_session_id IS NULL"),
    )
    op.create_index(
        "ux_os_browser_summary_with_browser",
        "os_browser_summary",
        ["parent_os_session_id", "segment_start", "segment_end", "browser_session_id"],
        unique=True,
        postgresql_where=sa.text("browser_session_id IS NOT NULL"),
        sqlite_where=sa.text("browser_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_os_browser_summary_with_browser", table_name="os_browser_summary")
    op.drop_index("ux_os_browser_summary_os_only", table_name="os_browser_summary")
    op.drop_index("ix_os_browser_summary_browser_session", table_name="os_browser_summary")
    op.drop_index("ix_os_browser_summary_parent_os", table_name="os_browser_summary")
    op.drop_index("ix_os_browser_summary_user_start", table_name="os_browser_summary")
    op.drop_table("os_browser_summary")
