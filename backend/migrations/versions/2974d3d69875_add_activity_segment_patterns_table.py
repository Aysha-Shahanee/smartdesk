"""Add activity_segment_patterns table

Revision ID: 2974d3d69875
Revises: 0010_repair_fabricated_spans
Create Date: 2026-08-07 11:49:56.140912

Originally committed as raw `--autogenerate` output ("please adjust!") and
never adjusted, so it had never run against a database. It has been trimmed
to the table its title names. Removed, deliberately:

  * re-creation of `os_browser_summary` and `activity_segment_embeddings`,
    both dropped on purpose by 0008_drop_unused_tables — autogenerate wanted
    them back only because app/models/db/ still declares the ORM classes.
  * drops of eight live indexes on `activity_segments` (user_time,
    user_category_time, user_device_time, sync_status_time, os_session,
    ide_session, browser_session, embedding_status_time).
  * a new unique constraint on activity_segments, which would rebuild the
    whole table on SQLite.
  * an unrelated index on work_periods.

It also passed bare strings to postgresql_where/sqlite_where, which
SQLAlchemy 2.x rejects with "'str' object has no attribute
'_compiler_dispatch'" — those partial indexes are gone with the table.
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = '2974d3d69875'
down_revision: Union[str, Sequence[str], None] = '0010_repair_fabricated_spans'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'activity_segment_patterns',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('segment_id', sa.String(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('anomaly_score', sa.Float(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['segment_id'], ['activity_segments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_patterns_segment_version', 'activity_segment_patterns', ['segment_id', 'model_version'], unique=False)
    op.create_index(op.f('ix_activity_segment_patterns_analyzed_at'), 'activity_segment_patterns', ['analyzed_at'], unique=False)
    op.create_index(op.f('ix_activity_segment_patterns_cluster_id'), 'activity_segment_patterns', ['cluster_id'], unique=False)
    op.create_index(op.f('ix_activity_segment_patterns_model_version'), 'activity_segment_patterns', ['model_version'], unique=False)
    op.create_index(op.f('ix_activity_segment_patterns_segment_id'), 'activity_segment_patterns', ['segment_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_segment_patterns_segment_id'), table_name='activity_segment_patterns')
    op.drop_index(op.f('ix_activity_segment_patterns_model_version'), table_name='activity_segment_patterns')
    op.drop_index(op.f('ix_activity_segment_patterns_cluster_id'), table_name='activity_segment_patterns')
    op.drop_index(op.f('ix_activity_segment_patterns_analyzed_at'), table_name='activity_segment_patterns')
    op.drop_index('idx_patterns_segment_version', table_name='activity_segment_patterns')
    op.drop_table('activity_segment_patterns')
