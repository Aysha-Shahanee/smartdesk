"""Fix used_in_training column type and default value

Change used_in_training from BOOLEAN (stored as string 'false'/'true') to INTEGER (0/1)
with default 0.

Revision ID: d4ac3b699608
Revises: 37d26e8238d9
Create Date: 2026-07-04 19:41:44.923898

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4ac3b699608'
down_revision = '37d26e8238d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new table with Integer column for used_in_training
    op.create_table(
        'activity_segment_labels_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('segment_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('device_id', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.String(), nullable=False),
        sa.Column('correct_label', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('used_in_training', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['segment_id'], ['activity_segments.id'], ondelete='CASCADE')
    )
    # Copy data from old table, converting used_in_training
    op.execute("""
        INSERT INTO activity_segment_labels_new (
            id, segment_id, user_id, device_id, model_name, model_version, dimensions, embedding, correct_label, created_at, used_in_training
        )
        SELECT
            id, segment_id, user_id, device_id, model_name, model_version, dimensions, embedding, correct_label, created_at,
            CASE used_in_training
                WHEN 'false' THEN 0
                WHEN 'true' THEN 1
                ELSE 0
            END
        FROM activity_segment_labels
    """)
    # Drop old table
    op.drop_table('activity_segment_labels')
    # Rename new table to original name
    op.rename_table('activity_segment_labels_new', 'activity_segment_labels')


def downgrade() -> None:
    # Revert to BOOLEAN column with string default
    op.create_table(
        'activity_segment_labels_old',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('segment_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('device_id', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('model_version', sa.String(), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.String(), nullable=False),
        sa.Column('correct_label', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('used_in_training', sa.BOOLEAN(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['segment_id'], ['activity_segments.id'], ondelete='CASCADE')
    )
    # Copy data from current table, converting used_in_training back to string
    op.execute("""
        INSERT INTO activity_segment_labels_old (
            id, segment_id, user_id, device_id, model_name, model_version, dimensions, embedding, correct_label, created_at, used_in_training
        )
        SELECT
            id, segment_id, user_id, device_id, model_name, model_version, dimensions, embedding, correct_label, created_at,
            CASE used_in_training
                WHEN 0 THEN 'false'
                WHEN 1 THEN 'true'
                ELSE 'false'
            END
        FROM activity_segment_labels
    """)
    op.drop_table('activity_segment_labels')
    op.rename_table('activity_segment_labels_old', 'activity_segment_labels')