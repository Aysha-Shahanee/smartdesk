"""Add canonical GitHub repository identity to IDE sessions.

Revision ID: 0014_ide_repository
Revises: 0013_github_integration
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_ide_repository"
down_revision: Union[str, Sequence[str], None] = "0013_github_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ide_sessions", sa.Column("repository", sa.String(), nullable=True))
    op.create_index(
        "ix_ide_sessions_user_repository_start",
        "ide_sessions",
        ["user_id", "repository", "session_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_ide_sessions_user_repository_start", table_name="ide_sessions")
    op.drop_column("ide_sessions", "repository")
