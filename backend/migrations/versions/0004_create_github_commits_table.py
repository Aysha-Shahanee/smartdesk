"""create github commits table

Revision ID: 0004_create_github_commits_table
Revises: 0003_add_vscode_session_tracking_fields
Create Date: 2026-06-22
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_create_github_commits_table"
down_revision: Union[str, Sequence[str], None] = "0003_add_vscode_session_tracking_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_commits",
        sa.Column("sha", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("author_email", sa.String(), nullable=True),
        sa.Column("committed_at", sa.String(), nullable=False),
        sa.Column("collected_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("sha"),
    )
    op.create_index("ix_github_commits_sha", "github_commits", ["sha"])
    op.create_index("ix_github_commits_user_id", "github_commits", ["user_id"])
    op.create_index("ix_github_commits_repo", "github_commits", ["repo"])
    op.create_index(
        "ix_github_commits_user_repo", "github_commits", ["user_id", "repo"]
    )
    op.create_index("ix_github_commits_committed_at", "github_commits", ["committed_at"])


def downgrade() -> None:
    op.drop_index("ix_github_commits_committed_at", table_name="github_commits")
    op.drop_index("ix_github_commits_user_repo", table_name="github_commits")
    op.drop_index("ix_github_commits_repo", table_name="github_commits")
    op.drop_index("ix_github_commits_user_id", table_name="github_commits")
    op.drop_index("ix_github_commits_sha", table_name="github_commits")
    op.drop_table("github_commits")
