"""change is_idle and is_locked to store seconds instead of flags

Revision ID: 0002_change_is_idle_is_locked_to_seconds
Revises: 0001_create_session_architecture_tables
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_change_is_idle_is_locked_to_seconds"
down_revision: Union[str, Sequence[str], None] = "0001_create_session_architecture_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No structural change needed - columns remain INTEGER
    # Semantic change: now store seconds instead of boolean flags
    # Use batch operations for SQLite compatibility
    with op.batch_alter_table('os_sessions') as batch_op:
        batch_op.alter_column('is_idle',
                              existing_type=sa.Integer())
        batch_op.alter_column('is_locked',
                              existing_type=sa.Integer())


def downgrade() -> None:
    # Revert to boolean flag semantics (though data will be time values)
    # Use batch operations for SQLite compatibility
    with op.batch_alter_table('os_sessions') as batch_op:
        batch_op.alter_column('is_idle',
                              existing_type=sa.Integer())
        batch_op.alter_column('is_locked',
                              existing_type=sa.Integer())