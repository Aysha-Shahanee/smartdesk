"""Record the surfacing propensity on each recommendation.

The learned ranker cannot be evaluated as it stands, and no amount of later
analysis can fix that — the missing information is destroyed at the moment the
panel is built. Every off-policy estimator (IPS, SNIPS, doubly-robust) reweights
a logged reward by pi_eval / pi_logging and needs common support: pi_logging must
be greater than zero wherever pi_eval is. A deterministic policy gives
probability 1 to the cards it chose and 0 to everything it passed over, so the
ratio is undefined and the estimators cannot be computed at all.

Two nullable columns, because the fix is to log the probability at decision
time and there is nowhere else it can come from. ``propensity`` is the chance
the policy had of showing this particular card; ``explored`` marks the cards
surfaced by the epsilon-greedy arm rather than on merit.

Nullable rather than defaulted, on purpose: existing rows were written by a
policy whose propensities are genuinely unknown, and back-filling 1.0 would
assert common support that never existed. NULL means "not recorded", which is
the difference between no data and misleading data.

Revision ID: 0017_reco_propensity
Revises: 0016_reco_cooldown_idx
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_reco_propensity"
down_revision = "0016_reco_cooldown_idx"
branch_labels = None
depends_on = None

TABLE = "recommendations"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("propensity", sa.Float(), nullable=True))
    op.add_column(TABLE, sa.Column("explored", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, "explored")
    op.drop_column(TABLE, "propensity")
