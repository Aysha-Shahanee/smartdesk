"""Index the cooldown lookup on recommendations.

The engine asks "has this rule fired for this user since <timestamp>?" once per
scope run. Existing indexes cover ``user_id`` and ``rule_id`` separately, so
SQLite picked one and scanned the rest — on a user with a long history that is
every row the chosen index matched.

Ordered (user_id, rule_id, generated_at) so the grouped query in
``RecommendationEngine._last_fired`` is answered from the index alone: the
first two columns narrow, the third is already sorted for the MAX.

Revision ID: 0016_reco_cooldown_idx
Revises: 9e46b14de401
"""

from alembic import op

revision = "0016_reco_cooldown_idx"
down_revision = "9e46b14de401"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_recommendations_user_rule_time"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "recommendations",
        ["user_id", "rule_id", "generated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="recommendations")
