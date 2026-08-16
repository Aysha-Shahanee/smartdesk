"""drop unused tables

Revision ID: 0008_drop_unused_tables
Revises: 0007_create_activity_segment_embeddings_table
Create Date: 2026-07-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_drop_unused_tables'
down_revision: Union[str, Sequence[str], None] = '0007_create_activity_segment_embeddings_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop activity_segment_embeddings table
    op.drop_table('activity_segment_embeddings')

    # Drop os_browser_summary table
    op.drop_table('os_browser_summary')


def downgrade() -> None:
    # Note: For safety, we're not implementing downgrade as these tables
    # were determined to be unused and safe to remove permanently.
    # If needed, the tables can be recreated from previous migrations.
    pass