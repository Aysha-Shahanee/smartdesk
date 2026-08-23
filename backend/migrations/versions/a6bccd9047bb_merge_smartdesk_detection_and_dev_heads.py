"""merge smartdesk detection and dev heads

Revision ID: a6bccd9047bb
Revises: 0019_smartdesk_detection, d0464978698a
Create Date: 2026-08-22 19:30:49.886753
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = 'a6bccd9047bb'
down_revision: Union[str, Sequence[str], None] = ('0019_smartdesk_detection', 'd0464978698a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
