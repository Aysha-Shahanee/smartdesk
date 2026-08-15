"""label provenance, and allow 'supervised' as a category method

Two changes, both prerequisites for training the supervised classifier on
anything other than hand-typed corrections.

``activity_segment_labels.source`` records where a label came from. The table
was built for user corrections, where every row is ground truth. Bulk-repairing
a misclassification writes thousands of rows that are *derived* — good enough to
learn from, but not evidence of what the user actually meant. Without a
provenance column the two are indistinguishable, and a later audit of "what did
the user tell us" would silently answer with the repair script's opinions.
Existing rows are stamped 'user', which is what they are.

``ck_activity_segments_category_method`` accepted only 'rule' and 'embedding',
while ``Categorizer._predict_uncapped`` has always been able to return
'supervised'. Nothing had hit it because no model had ever been trained — the
labels table held 26 rows against a 10-sample minimum spread over five
retrain-threshold batches. Backfilled labels take it past that bar, at which
point the first supervised prediction would fail the CHECK on INSERT; segments
are persisted one batch at a time, so that single row would discard every
segment built in the same window. The same class of latent failure as the
unstorable-category bug already guarded against in the categorizer.

Revision ID: 0011_label_provenance
Revises: 0010_repair_fabricated_spans
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011_label_provenance'
down_revision: Union[str, Sequence[str], None] = '0010_repair_fabricated_spans'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_METHOD_CHECK = "category_method IS NULL OR category_method IN ('rule', 'embedding')"
NEW_METHOD_CHECK = (
    "category_method IS NULL OR category_method IN ('rule', 'embedding', 'supervised')"
)


# Declared on the copied table so the rebuild recreates them. Anything left out
# here is silently dropped: the table is renamed, a new one is built from this
# definition, and the old one goes. Uniqueness of
# (user_id, device_id, start_time_utc, end_time_utc) is enforced by a unique
# *index* rather than a table constraint — that is how 0006 created it, and
# restating it as a UNIQUE constraint would rename the object.
_INDEXES = (
    ('ix_activity_segments_user_device_time',
     ('user_id', 'device_id', 'start_time_utc', 'end_time_utc'), True),
    ('ix_activity_segments_user_time', ('user_id', 'start_time_utc'), False),
    ('ix_activity_segments_user_category_time',
     ('user_id', 'category', 'start_time_utc'), False),
    ('ix_activity_segments_sync_status_time', ('sync_status', 'start_time_utc'), False),
    ('ix_activity_segments_embedding_status_time',
     ('embedding_status', 'start_time_utc'), False),
    ('ix_activity_segments_os_session', ('os_session_id',), False),
    ('ix_activity_segments_ide_session', ('ide_session_id',), False),
    ('ix_activity_segments_browser_session', ('browser_session_id',), False),
)


def _activity_segments(check: str) -> sa.Table:
    """The activity_segments table as it stands, for SQLite batch copying.

    SQLite cannot alter a CHECK constraint in place, so Alembic rebuilds the
    table; to do that it needs the current structure spelled out, because
    SQLite reflection does not return CHECK constraints.
    """
    table = sa.Table(
        'activity_segments',
        sa.MetaData(),
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('device_id', sa.String(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('start_time_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_sec', sa.Integer(), nullable=False),
        sa.Column('timezone_name', sa.String(), nullable=False),
        sa.Column('local_date', sa.String(), nullable=False),
        sa.Column('primary_source', sa.String(), nullable=False),
        sa.Column('app_name', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('detail', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('os_session_id', sa.String(), nullable=True),
        sa.Column('ide_session_id', sa.String(), nullable=True),
        sa.Column('browser_session_id', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('category_method', sa.String(), nullable=True),
        sa.Column('category_confidence', sa.Float(), nullable=True),
        sa.Column('focus_score', sa.Float(), nullable=True),
        sa.Column('concurrent_json', sa.Text(), nullable=True),
        sa.Column('signals_json', sa.Text(), nullable=True),
        sa.Column('embedding_status', sa.String(), server_default='pending', nullable=False),
        sa.Column('sync_status', sa.String(), server_default='pending', nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('content_version', sa.Integer(), server_default='1', nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'end_time_utc > start_time_utc', name='ck_activity_segments_valid_time'
        ),
        sa.CheckConstraint('duration_sec >= 0', name='ck_activity_segments_duration'),
        sa.CheckConstraint(
            'focus_score IS NULL OR (focus_score >= 0 AND focus_score <= 1)',
            name='ck_activity_segments_focus',
        ),
        sa.CheckConstraint(
            'category_confidence IS NULL OR '
            '(category_confidence >= 0 AND category_confidence <= 1)',
            name='ck_activity_segments_category_confidence',
        ),
        sa.CheckConstraint(
            "primary_source IN ('os', 'ide', 'browser', 'synthetic')",
            name='ck_activity_segments_primary_source',
        ),
        sa.CheckConstraint(
            "state IN ('active', 'idle', 'locked', 'gap')",
            name='ck_activity_segments_state',
        ),
        sa.CheckConstraint(
            "category IS NULL OR category IN ('work', 'learn', 'communication', "
            "'entertainment', 'social_media', 'system', 'meetings', 'other')",
            name='ck_activity_segments_category',
        ),
        sa.CheckConstraint(check, name='ck_activity_segments_category_method'),
        sa.CheckConstraint(
            "embedding_status IN ('pending', 'processing', 'completed', 'failed', "
            "'not_required')",
            name='ck_activity_segments_embedding_status',
        ),
        sa.CheckConstraint(
            "sync_status IN ('pending', 'syncing', 'synced', 'failed')",
            name='ck_activity_segments_sync_status',
        ),
    )
    for name, columns, unique in _INDEXES:
        sa.Index(name, *(table.c[column] for column in columns), unique=unique)
    return table


def upgrade() -> None:
    with op.batch_alter_table('activity_segment_labels') as batch_op:
        batch_op.add_column(
            sa.Column(
                'source', sa.String(), nullable=False, server_default='user',
            )
        )

    with op.batch_alter_table(
        'activity_segments',
        copy_from=_activity_segments(OLD_METHOD_CHECK),
        recreate='always',
    ) as batch_op:
        batch_op.drop_constraint(
            'ck_activity_segments_category_method', type_='check'
        )
        batch_op.create_check_constraint(
            'ck_activity_segments_category_method', NEW_METHOD_CHECK
        )


def downgrade() -> None:
    # Rows written by a supervised model would violate the restored CHECK, so
    # they are demoted to the method that produced their embedding rather than
    # blocking the downgrade.
    op.execute(
        "UPDATE activity_segments SET category_method = 'embedding' "
        "WHERE category_method = 'supervised'"
    )

    with op.batch_alter_table(
        'activity_segments',
        copy_from=_activity_segments(NEW_METHOD_CHECK),
        recreate='always',
    ) as batch_op:
        batch_op.drop_constraint(
            'ck_activity_segments_category_method', type_='check'
        )
        batch_op.create_check_constraint(
            'ck_activity_segments_category_method', OLD_METHOD_CHECK
        )

    with op.batch_alter_table('activity_segment_labels') as batch_op:
        batch_op.drop_column('source')
