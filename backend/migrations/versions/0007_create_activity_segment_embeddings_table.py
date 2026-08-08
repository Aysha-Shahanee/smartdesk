"""create activity_segment_embeddings table

Revision ID: 0007_create_activity_segment_embeddings_table
Revises: 0006_create_activity_segments_table
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_create_activity_segment_embeddings_table"
down_revision: Union[str, Sequence[str], None] = "0006_create_activity_segments_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create activity_segment_embeddings table
    op.create_table(
        "activity_segment_embeddings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("segment_id", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),  # Store as base64 or similar
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["activity_segments.id"],
            ondelete="CASCADE"
        ),
    )

    # Create indexes
    op.create_index(
        "ix_activity_segment_embeddings_segment_id",
        "activity_segment_embeddings",
        ["segment_id"],
    )
    op.create_index(
        "ix_activity_segment_embeddings_model",
        "activity_segment_embeddings",
        ["model_name", "model_version"],
    )
    # Unique constraint for one embedding per segment per model/version
    op.create_index(
        "ux_activity_segment_embeddings_unique",
        "activity_segment_embeddings",
        ["segment_id", "model_name", "model_version"],
        unique=True,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ux_activity_segment_embeddings_unique", table_name="activity_segment_embeddings")
    op.drop_index("ix_activity_segment_embeddings_model", table_name="activity_segment_embeddings")
    op.drop_index("ix_activity_segment_embeddings_segment_id", table_name="activity_segment_embeddings")

    # Drop table
    op.drop_table("activity_segment_embeddings")