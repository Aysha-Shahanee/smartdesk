"""merge focus-score and dev lineages

Revision ID: 854bc354074b
Revises: 8a11c0d5f3d1, 0012_user_category_method
Create Date: 2026-08-14 19:26:45.909342
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = '854bc354074b'
down_revision: Union[str, Sequence[str], None] = ('8a11c0d5f3d1', '0012_user_category_method')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
