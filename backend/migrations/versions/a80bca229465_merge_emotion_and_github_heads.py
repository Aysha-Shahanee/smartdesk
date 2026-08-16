"""merge emotion and github heads

Revision ID: a80bca229465
Revises: 33d326feb3b1, 0011_create_emotion_local_tables
Create Date: 2026-08-16 20:39:56.247676

The emotion branch forked from 0010_repair_fabricated_spans, the same parent
0011_label_provenance already had, so both lineages ended up with an 0011.
The numbers are only filenames — the revision ids differ, and this merge is
what puts the two branches back on a single head.
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa



revision: str = 'a80bca229465'
down_revision: Union[str, Sequence[str], None] = ('33d326feb3b1', '0011_create_emotion_local_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
