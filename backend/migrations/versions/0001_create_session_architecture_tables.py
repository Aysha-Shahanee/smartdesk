"""create session architecture tables

Revision ID: 0001_create_session_architecture_tables
Revises:
Create Date: 2026-06-11 (rebuilt: vscode->ide rename, calendar expansion)
"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_create_session_architecture_tables"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "os_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("app_name", sa.String(), nullable=False),
        sa.Column("app_category", sa.String(), nullable=True),
        sa.Column("window_title", sa.String(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("is_idle", sa.Integer(), nullable=False),
        sa.Column("is_locked", sa.Integer(), nullable=False),
        sa.Column("session_start", sa.String(), nullable=False),
        sa.Column("session_end", sa.String(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("extra_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_os_sessions_app_name", "os_sessions", ["app_name"])
    op.create_index("ix_os_sessions_process_id", "os_sessions", ["process_id"])
    op.create_index("ix_os_sessions_user_start", "os_sessions", ["user_id", "session_start"])

    op.create_table(
        "ide_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("ide_name", sa.String(), nullable=True),
        sa.Column("instance_id", sa.String(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("parent_process_id", sa.Integer(), nullable=True),
        sa.Column("workspace_name", sa.String(), nullable=True),
        sa.Column("project_path", sa.String(), nullable=True),
        sa.Column("repo_id", sa.String(), nullable=True),
        sa.Column("git_branch", sa.String(), nullable=True),
        sa.Column("active_file_path", sa.String(), nullable=True),
        sa.Column("active_file_name", sa.String(), nullable=True),
        sa.Column("active_language", sa.String(), nullable=True),
        sa.Column("session_start", sa.String(), nullable=False),
        sa.Column("session_end", sa.String(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("idle_sec", sa.Integer(), nullable=True),
        sa.Column("is_foreground", sa.Integer(), nullable=False),
        sa.Column("foreground_sec", sa.Integer(), nullable=True),
        sa.Column("confirmed_by_os", sa.Integer(), nullable=False),
        sa.Column("collection_reason", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("edit_count", sa.Integer(), nullable=False),
        sa.Column("save_count", sa.Integer(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False),
        sa.Column("lines_deleted", sa.Integer(), nullable=False),
        sa.Column("file_switch_count", sa.Integer(), nullable=False),
        sa.Column("terminal_command_count", sa.Integer(), nullable=False),
        sa.Column("debug_run_count", sa.Integer(), nullable=False),
        sa.Column("edited_file_count", sa.Integer(), nullable=True),
        sa.Column("changed_file_count", sa.Integer(), nullable=True),
        sa.Column("dominant_language", sa.String(), nullable=True),
        sa.Column("languages_json", sa.String(), nullable=True),
        sa.Column("edited_files_json", sa.String(), nullable=True),
        sa.Column("extra_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ide_sessions_instance_id", "ide_sessions", ["instance_id"])
    op.create_index("ix_ide_sessions_is_foreground", "ide_sessions", ["is_foreground"])
    op.create_index("ix_ide_sessions_process_id", "ide_sessions", ["process_id"])
    op.create_index("ix_ide_sessions_user_start", "ide_sessions", ["user_id", "session_start"])

    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("browser_name", sa.String(), nullable=False),
        sa.Column("browser_window_id", sa.Integer(), nullable=True),
        sa.Column("tab_id", sa.Integer(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("session_start", sa.String(), nullable=False),
        sa.Column("session_end", sa.String(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("is_foreground", sa.Integer(), nullable=False),
        sa.Column("confirmed_by_os", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("extra_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_sessions_window_id", "browser_sessions", ["browser_window_id"])
    op.create_index("ix_browser_sessions_domain", "browser_sessions", ["domain"])
    op.create_index("ix_browser_sessions_is_foreground", "browser_sessions", ["is_foreground"])
    op.create_index(
        "ix_browser_sessions_user_start", "browser_sessions", ["user_id", "session_start"]
    )

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("start_time", sa.String(), nullable=True),
        sa.Column("end_time", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("is_all_day", sa.Integer(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("organizer_email", sa.String(), nullable=True),
        sa.Column("attendees_count", sa.Integer(), nullable=True),
        sa.Column("attendees_json", sa.String(), nullable=True),
        sa.Column("is_recurring", sa.Integer(), nullable=True),
        sa.Column("recurring_event_id", sa.String(), nullable=True),
        sa.Column("html_link", sa.String(), nullable=True),
        sa.Column("google_updated_at", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.String(), nullable=True),
        sa.Column("extra_data", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_calendar_events_user_event"),
    )
    op.create_index("ix_calendar_events_event_id", "calendar_events", ["event_id"])
    op.create_index("ix_calendar_events_id", "calendar_events", ["id"])
    op.create_index("ix_calendar_events_user_id", "calendar_events", ["user_id"])
    op.create_index("ix_calendar_events_user_start", "calendar_events", ["user_id", "start_time"])

    op.create_table(
        "work_periods",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("period_start", sa.String(), nullable=False),
        sa.Column("period_end", sa.String(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("primary_source", sa.String(), nullable=True),
        sa.Column("primary_app", sa.String(), nullable=True),
        sa.Column("primary_project", sa.String(), nullable=True),
        sa.Column("primary_domain", sa.String(), nullable=True),
        sa.Column("has_os_data", sa.Integer(), nullable=False),
        sa.Column("has_ide_data", sa.Integer(), nullable=False),
        sa.Column("has_browser_data", sa.Integer(), nullable=False),
        sa.Column("has_calendar_data", sa.Integer(), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("extra_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_periods_primary_source", "work_periods", ["primary_source"])
    op.create_index("ix_work_periods_user_id", "work_periods", ["user_id"])
    op.create_index("ix_work_periods_user_start", "work_periods", ["user_id", "period_start"])


def downgrade() -> None:
    op.drop_table("work_periods")
    op.drop_table("calendar_events")
    op.drop_table("browser_sessions")
    op.drop_table("ide_sessions")
    op.drop_table("os_sessions")
