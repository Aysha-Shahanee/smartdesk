"""create service_heartbeat table

Records when the backend was last observed alive, so a session close can be
bounded by how long the observer was actually running instead of stamping
whatever moment it happened to notice.

Revision ID: 0009_create_service_heartbeat
Revises: 2798bd862f43
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009_create_service_heartbeat'
down_revision: Union[str, Sequence[str], None] = '2798bd862f43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'service_heartbeat',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('beat_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('service_heartbeat')
