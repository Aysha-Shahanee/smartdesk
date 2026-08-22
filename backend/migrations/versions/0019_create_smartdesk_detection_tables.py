"""create smartdesk v2 detection tables

Revision ID: 0019_smartdesk_detection
Revises: 0011_create_emotion_local_tables
Create Date: 2026-08-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_smartdesk_detection"
down_revision: Union[str, Sequence[str], None] = "0011_create_emotion_local_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "smartdesk_detection_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("program_start_time", sa.String(), nullable=False),
        sa.Column("warmup_end_time", sa.String(), nullable=True),
        sa.Column("real_start_time", sa.String(), nullable=True),
        sa.Column("actual_camera_end_time", sa.String(), nullable=True),
        sa.Column("usable_block_end_time", sa.String(), nullable=True),
        sa.Column("discarded_tail_seconds", sa.Float(), nullable=False),
        sa.Column("startup_wait_seconds_after_warmup", sa.Float(), nullable=False),
        sa.Column("official_seconds_requested", sa.Float(), nullable=False),
        sa.Column("sample_fps", sa.Float(), nullable=False),
        sa.Column("frames_read", sa.Integer(), nullable=False),
        sa.Column("samples_processed", sa.Integer(), nullable=False),
        sa.Column("face_detected_samples", sa.Integer(), nullable=False),
        sa.Column("completed_counts_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_smartdesk_detection_sessions_user_real_start",
        "smartdesk_detection_sessions",
        ["user_id", "real_start_time"],
    )
    op.create_index(
        "ix_smartdesk_detection_sessions_status",
        "smartdesk_detection_sessions",
        ["status"],
    )

    op.create_table(
        "smartdesk_signal_blocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("block_type", sa.String(), nullable=False),
        sa.Column("block_start_time", sa.String(), nullable=False),
        sa.Column("block_end_time", sa.String(), nullable=False),
        sa.Column("window_seconds", sa.Float(), nullable=False),
        sa.Column("total_time", sa.Float(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("valid_frame_count", sa.Integer(), nullable=False),
        sa.Column("happy_avg", sa.Float(), nullable=False),
        sa.Column("neutral_avg", sa.Float(), nullable=False),
        sa.Column("confusion_avg", sa.Float(), nullable=False),
        sa.Column("top_class", sa.String(), nullable=True),
        sa.Column("top_probability", sa.Float(), nullable=False),
        sa.Column("emotion_state", sa.String(), nullable=True),
        sa.Column("emotion_sublabel", sa.String(), nullable=True),
        sa.Column("face_visible_ratio", sa.Float(), nullable=False),
        sa.Column("screen_facing_ratio", sa.Float(), nullable=False),
        sa.Column("looking_away_ratio", sa.Float(), nullable=False),
        sa.Column("long_lookaway_count", sa.Integer(), nullable=False),
        sa.Column("engagement_label", sa.String(), nullable=True),
        sa.Column("perclos", sa.Float(), nullable=False),
        sa.Column("eye_closed_ratio", sa.Float(), nullable=False),
        sa.Column("head_down_ratio", sa.Float(), nullable=False),
        sa.Column("possible_yawn_ratio", sa.Float(), nullable=False),
        sa.Column("long_eye_closure_count", sa.Integer(), nullable=False),
        sa.Column("yawn_count", sa.Integer(), nullable=False),
        sa.Column("sleepiness_label", sa.String(), nullable=True),
        sa.Column("raw_summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smartdesk_signal_blocks_session_start", "smartdesk_signal_blocks", ["session_id", "block_start_time"])
    op.create_index("ix_smartdesk_signal_blocks_user_start", "smartdesk_signal_blocks", ["user_id", "block_start_time"])
    op.create_index("ix_smartdesk_signal_blocks_type_start", "smartdesk_signal_blocks", ["block_type", "block_start_time"])

    op.create_table(
        "smartdesk_final_state_blocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("block_start_time", sa.String(), nullable=False),
        sa.Column("block_end_time", sa.String(), nullable=False),
        sa.Column("window_seconds", sa.Float(), nullable=False),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("matched_rule", sa.String(), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("confusion_ratio", sa.Float(), nullable=False),
        sa.Column("stable_emotion_ratio", sa.Float(), nullable=False),
        sa.Column("engaged_ratio", sa.Float(), nullable=False),
        sa.Column("low_engagement_ratio", sa.Float(), nullable=False),
        sa.Column("drowsy_ratio", sa.Float(), nullable=False),
        sa.Column("emotion_confusion_count", sa.Integer(), nullable=False),
        sa.Column("emotion_stable_count", sa.Integer(), nullable=False),
        sa.Column("engagement_high_count", sa.Integer(), nullable=False),
        sa.Column("engagement_medium_count", sa.Integer(), nullable=False),
        sa.Column("engagement_low_count", sa.Integer(), nullable=False),
        sa.Column("sleepiness_alert_count", sa.Integer(), nullable=False),
        sa.Column("sleepiness_drowsy_count", sa.Integer(), nullable=False),
        sa.Column("dominant_emotion", sa.String(), nullable=True),
        sa.Column("dominant_engagement", sa.String(), nullable=True),
        sa.Column("dominant_sleepiness", sa.String(), nullable=True),
        sa.Column("raw_summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smartdesk_final_state_blocks_session_start", "smartdesk_final_state_blocks", ["session_id", "block_start_time"])
    op.create_index("ix_smartdesk_final_state_blocks_user_start", "smartdesk_final_state_blocks", ["user_id", "block_start_time"])
    op.create_index("ix_smartdesk_final_state_blocks_state_start", "smartdesk_final_state_blocks", ["state", "block_start_time"])

    op.create_table(
        "smartdesk_reporting_blocks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("block_start_time", sa.String(), nullable=False),
        sa.Column("block_end_time", sa.String(), nullable=False),
        sa.Column("window_seconds", sa.Float(), nullable=False),
        sa.Column("final_state_block_count", sa.Integer(), nullable=False),
        sa.Column("focused_ratio", sa.Float(), nullable=False),
        sa.Column("struggling_ratio", sa.Float(), nullable=False),
        sa.Column("disengaged_ratio", sa.Float(), nullable=False),
        sa.Column("fatigued_ratio", sa.Float(), nullable=False),
        sa.Column("overloaded_ratio", sa.Float(), nullable=False),
        sa.Column("dominant_state", sa.String(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("raw_summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smartdesk_reporting_blocks_session_start", "smartdesk_reporting_blocks", ["session_id", "block_start_time"])
    op.create_index("ix_smartdesk_reporting_blocks_user_start", "smartdesk_reporting_blocks", ["user_id", "block_start_time"])
    op.create_index("ix_smartdesk_reporting_blocks_state_start", "smartdesk_reporting_blocks", ["dominant_state", "block_start_time"])


def downgrade() -> None:
    op.drop_index("ix_smartdesk_reporting_blocks_state_start", table_name="smartdesk_reporting_blocks")
    op.drop_index("ix_smartdesk_reporting_blocks_user_start", table_name="smartdesk_reporting_blocks")
    op.drop_index("ix_smartdesk_reporting_blocks_session_start", table_name="smartdesk_reporting_blocks")
    op.drop_table("smartdesk_reporting_blocks")

    op.drop_index("ix_smartdesk_final_state_blocks_state_start", table_name="smartdesk_final_state_blocks")
    op.drop_index("ix_smartdesk_final_state_blocks_user_start", table_name="smartdesk_final_state_blocks")
    op.drop_index("ix_smartdesk_final_state_blocks_session_start", table_name="smartdesk_final_state_blocks")
    op.drop_table("smartdesk_final_state_blocks")

    op.drop_index("ix_smartdesk_signal_blocks_type_start", table_name="smartdesk_signal_blocks")
    op.drop_index("ix_smartdesk_signal_blocks_user_start", table_name="smartdesk_signal_blocks")
    op.drop_index("ix_smartdesk_signal_blocks_session_start", table_name="smartdesk_signal_blocks")
    op.drop_table("smartdesk_signal_blocks")

    op.drop_index("ix_smartdesk_detection_sessions_status", table_name="smartdesk_detection_sessions")
    op.drop_index("ix_smartdesk_detection_sessions_user_real_start", table_name="smartdesk_detection_sessions")
    op.drop_table("smartdesk_detection_sessions")

