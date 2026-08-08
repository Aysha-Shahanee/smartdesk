"""merge heads

Revision ID: 2798bd862f43
Revises: d4ac3b699608, 0008_drop_unused_tables
Create Date: 2026-07-11 22:14:11.847094
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = '2798bd862f43'
down_revision: Union[str, Sequence[str], None] = ('d4ac3b699608', '0008_drop_unused_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
