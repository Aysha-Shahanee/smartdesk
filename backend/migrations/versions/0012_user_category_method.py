"""allow 'user' as a category method

A category someone assigned by hand had nowhere truthful to live. The method
column accepted only the classifiers' own names, so a hand-applied label had to
masquerade as 'rule' — indistinguishable from a keyword match, and therefore
indistinguishable to ``_upsert_segments``, which rewrites category,
category_method and category_confidence from the classifier on every rebuild.
Labelling 281 uncategorised segments would have survived exactly until the next
build pass.

With a method of its own, a user label is both attributable and defensible:
the builder now leaves those three columns alone when it finds one.

The table is respelled rather than altered because SQLite cannot change a CHECK
constraint in place, and the structure is restated in full here rather than
imported from 0011 — a migration has to keep replaying correctly no matter what
later code does to a shared helper.

Revision ID: 0012_user_category_method
Revises: 0011_label_provenance
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012_user_category_method'
down_revision: Union[str, Sequence[str], None] = '0011_label_provenance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_METHOD_CHECK = (
    "category_method IS NULL OR category_method IN ('rule', 'embedding', 'supervised')"
)
NEW_METHOD_CHECK = (
    "category_method IS NULL OR "
    "category_method IN ('rule', 'embedding', 'supervised', 'user')"
)

# Declared so the rebuild recreates them; anything omitted is silently dropped.
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
    """The activity_segments table as it stands, for SQLite batch copying."""
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


def _swap_check(from_check: str, to_check: str) -> None:
    with op.batch_alter_table(
        'activity_segments',
        copy_from=_activity_segments(from_check),
        recreate='always',
    ) as batch_op:
        batch_op.drop_constraint(
            'ck_activity_segments_category_method', type_='check'
        )
        batch_op.create_check_constraint(
            'ck_activity_segments_category_method', to_check
        )


def upgrade() -> None:
    _swap_check(OLD_METHOD_CHECK, NEW_METHOD_CHECK)


def downgrade() -> None:
    # Hand-assigned categories are kept; only the attribution is lost, since
    # the restored CHECK has no value that can carry it.
    op.execute(
        "UPDATE activity_segments SET category_method = NULL "
        "WHERE category_method = 'user'"
    )
    _swap_check(NEW_METHOD_CHECK, OLD_METHOD_CHECK)
