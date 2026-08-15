"""create local emotion storage tables

Revision ID: 0011_create_emotion_local_tables
Revises: 0010_repair_fabricated_spans
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_create_emotion_local_tables"
down_revision: Union[str, Sequence[str], None] = "0010_repair_fabricated_spans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "emotion_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("ended_at", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emotion_sessions_user_started", "emotion_sessions", ["user_id", "started_at"])
    op.create_index("ix_emotion_sessions_status", "emotion_sessions", ["status"])

    op.create_table(
        "emotion_blocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("session_start_time", sa.String(), nullable=False),
        sa.Column("block_start_time", sa.String(), nullable=False),
        sa.Column("block_end_time", sa.String(), nullable=False),
        sa.Column("block_type", sa.String(), nullable=False),
        sa.Column("duration_minutes", sa.Float(), nullable=False),
        sa.Column("dominant_emotion", sa.String(), nullable=False),
        sa.Column("happy_score", sa.Float(), nullable=False),
        sa.Column("neutral_score", sa.Float(), nullable=False),
        sa.Column("angry_score", sa.Float(), nullable=False),
        sa.Column("surprise_score", sa.Float(), nullable=False),
        sa.Column("emotion_scores", sa.Text(), nullable=False),
        sa.Column("processed_frame_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emotion_blocks_session_start", "emotion_blocks", ["session_id", "block_start_time"])
    op.create_index("ix_emotion_blocks_user_start", "emotion_blocks", ["user_id", "block_start_time"])


def downgrade() -> None:
    op.drop_index("ix_emotion_blocks_user_start", table_name="emotion_blocks")
    op.drop_index("ix_emotion_blocks_session_start", table_name="emotion_blocks")
    op.drop_table("emotion_blocks")
    op.drop_index("ix_emotion_sessions_status", table_name="emotion_sessions")
    op.drop_index("ix_emotion_sessions_user_started", table_name="emotion_sessions")
    op.drop_table("emotion_sessions")
