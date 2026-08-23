"""merge github identity and recommendation heads

Revision ID: d0464978698a
Revises: 0018_reco_shadow, 0016_github_identity
Create Date: 2026-08-21 05:56:57.818048
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = 'd0464978698a'
down_revision: Union[str, Sequence[str], None] = ('0018_reco_shadow', '0016_github_identity')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
