"""Remove unused calendar columns.

Revision ID: 0002_remove_calendar_event_columns
Revises: 0001_create_session_architecture_tables
Create Date: 2026-05-25
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_remove_calendar_event_columns"
down_revision: Union[str, Sequence[str], None] = "0001_create_session_architecture_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.drop_column("attendees_count")
        batch_op.drop_column("is_recurring")
        batch_op.drop_column("schema_version")


def downgrade() -> None:
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.add_column(sa.Column("attendees_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_recurring", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.String(), nullable=True))
