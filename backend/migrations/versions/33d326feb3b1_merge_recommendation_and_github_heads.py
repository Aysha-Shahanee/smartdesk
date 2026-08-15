"""merge recommendation and github heads

Revision ID: 33d326feb3b1
Revises: 0013_recommendation_engine, 0015_issue_number
Create Date: 2026-08-16 04:23:16.527196
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = '33d326feb3b1'
down_revision: Union[str, Sequence[str], None] = ('0013_recommendation_engine', '0015_issue_number')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
