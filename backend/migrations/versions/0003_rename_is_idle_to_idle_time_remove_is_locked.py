"""rename is_idle to idle_time and remove is_locked column

Revision ID: 0003_rename_is_idle_to_idle_time_remove_is_locked
Revises: 0002_change_is_idle_is_locked_to_seconds
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_rename_is_idle_to_idle_time_remove_is_locked"
down_revision = "0002_change_is_idle_is_locked_to_seconds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename is_idle -> idle_time and remove is_locked column
    # Use batch operations for SQLite compatibility
    with op.batch_alter_table('os_sessions') as batch_op:
        batch_op.alter_column('is_idle',
                              new_column_name='idle_time',
                              existing_type=sa.Integer())
        batch_op.drop_column('is_locked')


def downgrade() -> None:
    # Add back is_locked column and rename idle_time back to is_idle
    # Use batch operations for SQLite compatibility
    with op.batch_alter_table('os_sessions') as batch_op:
        batch_op.add_column(sa.Column('is_locked',
                                      sa.Integer(),
                                      nullable=False,
                                      server_default=sa.text("0")))
        batch_op.alter_column('idle_time',
                              new_column_name='is_idle',
                              existing_type=sa.Integer())