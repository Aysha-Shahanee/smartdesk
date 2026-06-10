"""Convert all timestamp String columns to DateTime(timezone=True)

Revision ID: 0004_convert_timestamps_to_datetime
Revises: 0003_add_vscode_session_tracking_fields
Create Date: 2026-06-06
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_convert_timestamps_to_datetime"
down_revision: Union[str, Sequence[str], None] = "0003_add_vscode_session_tracking_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _to_utc_str(value: str | None) -> str | None:
    """Parse an ISO 8601 string (any offset) and return UTC in SQLite DateTime format.

    SQLite's DateTime type expects 'YYYY-MM-DD HH:MM:SS.ffffff' (space separator,
    no offset). We normalise to UTC so the stored value is unambiguous.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        utc = dt.astimezone(timezone.utc)
        return utc.strftime("%Y-%m-%d %H:%M:%S.%f")
    except (ValueError, AttributeError):
        return value  # leave malformed values unchanged rather than crashing


def _convert_table(conn, table: str, pk: str, cols: list[str]) -> None:
    """Read every row and rewrite the named timestamp columns in UTC format."""
    select_cols = ", ".join([pk] + cols)
    rows = conn.execute(sa.text(f"SELECT {select_cols} FROM {table}")).fetchall()
    for row in rows:
        pk_val = row[0]
        updates = {col: _to_utc_str(row[i + 1]) for i, col in enumerate(cols)}
        set_clause = ", ".join(f"{col} = :{col}" for col in cols)
        conn.execute(
            sa.text(f"UPDATE {table} SET {set_clause} WHERE {pk} = :pk"),
            {**updates, "pk": pk_val},
        )


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------ #
    # Phase 1 — convert existing string values to UTC format in-place      #
    # ------------------------------------------------------------------ #
    _convert_table(
        conn, "os_sessions", "id",
        ["session_start", "session_end", "created_at", "updated_at"],
    )
    _convert_table(
        conn, "vscode_sessions", "id",
        ["session_start", "session_end", "created_at", "updated_at"],
    )
    _convert_table(
        conn, "browser_sessions", "id",
        ["session_start", "session_end", "created_at", "updated_at"],
    )
    _convert_table(
        conn, "calendar_events", "id",
        ["start_time", "end_time", "created_at", "updated_at"],
    )
    _convert_table(
        conn, "work_periods", "id",
        ["period_start", "period_end", "created_at", "updated_at"],
    )

    # ------------------------------------------------------------------ #
    # Phase 2 — redeclare columns as DateTime(timezone=True)              #
    # SQLite requires batch mode (table rebuild) for ALTER COLUMN.        #
    # ------------------------------------------------------------------ #
    _DT = sa.DateTime(timezone=True)
    _STR = sa.String()

    with op.batch_alter_table("os_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_DT, existing_type=_STR, existing_nullable=False)

    with op.batch_alter_table("vscode_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_DT, existing_type=_STR, existing_nullable=False)

    with op.batch_alter_table("browser_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_DT, existing_type=_STR, existing_nullable=False)

    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.alter_column("start_time",  type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("end_time",    type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("created_at",  type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("updated_at",  type_=_DT, existing_type=_STR, existing_nullable=False)

    with op.batch_alter_table("work_periods") as batch_op:
        batch_op.alter_column("period_start", type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("period_end",   type_=_DT, existing_type=_STR, existing_nullable=True)
        batch_op.alter_column("created_at",   type_=_DT, existing_type=_STR, existing_nullable=False)
        batch_op.alter_column("updated_at",   type_=_DT, existing_type=_STR, existing_nullable=False)


def downgrade() -> None:
    """Revert DateTime columns back to String, formatting datetimes as ISO 8601."""
    conn = op.get_bind()
    _DT = sa.DateTime(timezone=True)
    _STR = sa.String()

    # Redeclare as String first (batch rebuilds the table)
    with op.batch_alter_table("os_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_STR, existing_type=_DT, existing_nullable=False)

    with op.batch_alter_table("vscode_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_STR, existing_type=_DT, existing_nullable=False)

    with op.batch_alter_table("browser_sessions") as batch_op:
        batch_op.alter_column("session_start", type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("session_end",   type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("created_at",    type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("updated_at",    type_=_STR, existing_type=_DT, existing_nullable=False)

    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.alter_column("start_time",  type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("end_time",    type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("created_at",  type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("updated_at",  type_=_STR, existing_type=_DT, existing_nullable=False)

    with op.batch_alter_table("work_periods") as batch_op:
        batch_op.alter_column("period_start", type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("period_end",   type_=_STR, existing_type=_DT, existing_nullable=True)
        batch_op.alter_column("created_at",   type_=_STR, existing_type=_DT, existing_nullable=False)
        batch_op.alter_column("updated_at",   type_=_STR, existing_type=_DT, existing_nullable=False)
