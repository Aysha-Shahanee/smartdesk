"""add vscode session tracking fields

Revision ID: 0003_add_vscode_session_tracking_fields
Revises: 0002_remove_calendar_event_columns
Create Date: 2026-06-04
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_vscode_session_tracking_fields"
down_revision: Union[str, Sequence[str], None] = "0002_remove_calendar_event_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table("vscode_sessions") as batch_op:
        batch_op.add_column(sa.Column("edited_file_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("changed_file_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_edit_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_save_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_lines_added", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("total_lines_deleted", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("dominant_language", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("languages_json", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("edited_files_json", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("vscode_sessions") as batch_op:
        batch_op.drop_column("edited_files_json")
        batch_op.drop_column("languages_json")
        batch_op.drop_column("dominant_language")
        batch_op.drop_column("total_lines_deleted")
        batch_op.drop_column("total_lines_added")
        batch_op.drop_column("total_save_count")
        batch_op.drop_column("total_edit_count")
        batch_op.drop_column("changed_file_count")
        batch_op.drop_column("edited_file_count")
