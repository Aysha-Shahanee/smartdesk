"""remove foreground_sec, terminal_command_count, debug_run_count from ide_sessions

Revision ID: 0004_remove_ide_foreground_sec_terminal_debug_counts
Revises: 0003_rename_is_idle_to_idle_time_remove_is_locked
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_remove_ide_foreground_sec_terminal_debug_counts"
down_revision = "0003_rename_is_idle_to_idle_time_remove_is_locked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop unused IDE columns. Use batch operations for SQLite compatibility.
    with op.batch_alter_table("ide_sessions") as batch_op:
        batch_op.drop_column("foreground_sec")
        batch_op.drop_column("terminal_command_count")
        batch_op.drop_column("debug_run_count")


def downgrade() -> None:
    with op.batch_alter_table("ide_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("foreground_sec", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "terminal_command_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "debug_run_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
