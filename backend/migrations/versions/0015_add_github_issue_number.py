"""Add nullable numeric GitHub issue number metadata.

Revision ID: 0015_issue_number
Revises: 0014_ide_repository
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_issue_number"
down_revision: Union[str, Sequence[str], None] = "0014_ide_repository"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "github_initial_predictions",
        sa.Column("issue_number", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_initial_predictions", "issue_number")
