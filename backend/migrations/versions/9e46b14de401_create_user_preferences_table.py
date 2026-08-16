"""create user_preferences table

Revision ID: 9e46b14de401
Revises: a80bca229465
Create Date: 2026-08-16

Backs the Settings privacy toggles with storage the backend can read. Webcam
emotion capture is gated on a row in this table, so the consent answer has to
live somewhere the API process can see it rather than in renderer localStorage.
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "9e46b14de401"
down_revision: Union[str, Sequence[str], None] = "a80bca229465"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
