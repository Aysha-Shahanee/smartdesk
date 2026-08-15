"""Create GitHub App integration and initial prediction tables.

Revision ID: 0013_github_integration
Revises: 0012_user_category_method
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_github_integration"
down_revision: Union[str, Sequence[str], None] = "0012_user_category_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _validate_columns(inspector, table: str, required: set[str]) -> None:
    present = {column["name"] for column in inspector.get_columns(table)}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(
            f"Existing {table} table is incompatible; missing columns: "
            f"{', '.join(missing)}"
        )


def _ensure_index(inspector, name: str, table: str, columns: list[str]) -> None:
    if name not in {index["name"] for index in inspector.get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, "github_connections"):
        op.create_table(
            "github_connections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("github_login", sa.String(), nullable=True),
            sa.Column("installation_id", sa.Integer(), nullable=True),
            sa.Column("selected_owner", sa.String(), nullable=True),
            sa.Column("selected_project_number", sa.Integer(), nullable=True),
            sa.Column("selected_project_id", sa.String(), nullable=True),
            sa.Column("selected_project_title", sa.String(), nullable=True),
            sa.Column("connection_status", sa.String(), nullable=False, server_default="disconnected"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.UniqueConstraint("installation_id"),
            sa.UniqueConstraint("selected_project_id"),
            sa.UniqueConstraint("user_id"),
        )
    else:
        _validate_columns(inspector, "github_connections", {
            "id", "user_id", "github_login", "installation_id",
            "selected_owner", "selected_project_number", "selected_project_id",
            "selected_project_title", "connection_status", "created_at", "updated_at",
        })
    inspector = sa.inspect(op.get_bind())
    _ensure_index(inspector, "ix_github_connections_installation_id", "github_connections", ["installation_id"])
    _ensure_index(inspector, "ix_github_connections_selected_project_id", "github_connections", ["selected_project_id"])
    _ensure_index(inspector, "ix_github_connections_user_id", "github_connections", ["user_id"])

    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, "github_oauth_states"):
        op.create_table(
            "github_oauth_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("state_hash", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("expires_at", sa.String(), nullable=False),
            sa.Column("used_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.UniqueConstraint("state_hash"),
        )
    else:
        _validate_columns(inspector, "github_oauth_states", {
            "id", "state_hash", "user_id", "expires_at", "used_at", "created_at",
        })
    inspector = sa.inspect(op.get_bind())
    _ensure_index(inspector, "ix_github_oauth_states_state_hash", "github_oauth_states", ["state_hash"])
    _ensure_index(inspector, "ix_github_oauth_states_user_id", "github_oauth_states", ["user_id"])

    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, "github_initial_predictions"):
        op.create_table(
            "github_initial_predictions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("collector_lifecycle_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("project_item_id", sa.String(), nullable=False),
            sa.Column("issue_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("labels_json", sa.String(), nullable=True),
            sa.Column("repository", sa.String(), nullable=True),
            sa.Column("started_at", sa.String(), nullable=False),
            sa.Column("predicted_low_hours", sa.Float(), nullable=True),
            sa.Column("predicted_typical_hours", sa.Float(), nullable=True),
            sa.Column("predicted_high_hours", sa.Float(), nullable=True),
            sa.Column("model_version", sa.String(), nullable=True),
            sa.Column("predicted_at", sa.String(), nullable=False),
            sa.Column("prediction_status", sa.String(), nullable=False),
            sa.Column("prediction_error", sa.String(), nullable=True),
            sa.UniqueConstraint("collector_lifecycle_id"),
        )
    else:
        _validate_columns(inspector, "github_initial_predictions", {
            "id", "collector_lifecycle_id", "user_id", "project_id",
            "project_item_id", "issue_id", "title", "description", "labels_json",
            "repository", "started_at", "predicted_low_hours",
            "predicted_typical_hours", "predicted_high_hours", "model_version",
            "predicted_at", "prediction_status", "prediction_error",
        })
    inspector = sa.inspect(op.get_bind())
    _ensure_index(inspector, "ix_github_initial_predictions_collector_lifecycle_id", "github_initial_predictions", ["collector_lifecycle_id"])
    _ensure_index(inspector, "ix_github_initial_predictions_project_id", "github_initial_predictions", ["project_id"])
    _ensure_index(inspector, "ix_github_initial_predictions_project_item_id", "github_initial_predictions", ["project_item_id"])
    _ensure_index(inspector, "ix_github_initial_predictions_user_id", "github_initial_predictions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_github_initial_predictions_user_id", table_name="github_initial_predictions")
    op.drop_index("ix_github_initial_predictions_project_item_id", table_name="github_initial_predictions")
    op.drop_index("ix_github_initial_predictions_project_id", table_name="github_initial_predictions")
    op.drop_index("ix_github_initial_predictions_collector_lifecycle_id", table_name="github_initial_predictions")
    op.drop_table("github_initial_predictions")
    op.drop_index("ix_github_oauth_states_user_id", table_name="github_oauth_states")
    op.drop_index("ix_github_oauth_states_state_hash", table_name="github_oauth_states")
    op.drop_table("github_oauth_states")
    op.drop_index("ix_github_connections_user_id", table_name="github_connections")
    op.drop_index("ix_github_connections_selected_project_id", table_name="github_connections")
    op.drop_index("ix_github_connections_installation_id", table_name="github_connections")
    op.drop_table("github_connections")
