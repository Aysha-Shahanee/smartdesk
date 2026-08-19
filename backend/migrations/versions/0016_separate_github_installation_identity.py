"""Separate GitHub installation ownership from human user identity.

Revision ID: 0016_github_identity
Revises: 33d326feb3b1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_github_identity"
down_revision: Union[str, Sequence[str], None] = "33d326feb3b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("github_connections", sa.Column("installation_account_login", sa.String(), nullable=True))
    op.add_column("github_connections", sa.Column("installation_account_type", sa.String(), nullable=True))
    # Legacy github_login values came from installation.account.login. Preserve
    # them as installation ownership, but never continue treating them as a
    # verified human identity. Reconnecting reuses this row and project choice.
    op.execute("UPDATE github_connections SET installation_account_login = github_login")
    op.execute(
        "UPDATE github_connections SET github_login = NULL, "
        "connection_status = 'reauthorization_required' "
        "WHERE connection_status = 'connected'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE github_connections SET github_login = installation_account_login "
        "WHERE github_login IS NULL"
    )
    op.drop_column("github_connections", "installation_account_type")
    op.drop_column("github_connections", "installation_account_login")
