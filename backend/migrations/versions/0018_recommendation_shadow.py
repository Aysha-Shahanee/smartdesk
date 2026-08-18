"""Mark recommendations produced in shadow mode.

A new rule cannot currently be tried without shipping it. Its first contact
with real data is also the user's first contact with it, so a rule that fires
forty times a day or renders a broken sentence is discovered by the person it
was meant to help.

Shadow mode is the standard answer: evaluate the rule on live features, record
what it would have produced, and compare that against the accepted rules before
promoting it. This column is what separates those rows from real ones.

A flag rather than a new ``status`` value, because status records the user's
verdict and a shadow card has none — nobody saw it. Folding the two together
would put unseen cards into every acceptance rate the telemetry computes.

Nullable, so existing rows keep meaning what they meant: NULL and false both
read as "this was a real card", which is what every row written before now was.

Revision ID: 0018_reco_shadow
Revises: 0017_reco_propensity
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_reco_shadow"
down_revision = "0017_reco_propensity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendations", sa.Column("shadow", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("recommendations", "shadow")
