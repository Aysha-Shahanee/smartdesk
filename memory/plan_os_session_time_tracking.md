# Plan: Change OS Session is_idle/is_locked from Flags to Time-in-Seconds

## Problem
The `is_idle` and `is_locked` columns in the `os_sessions` table currently store boolean flags (0 or 1) indicating whether the system was ever idle or locked during a session. The user wants these columns to store the actual time in seconds that the system was idle or locked during each session.

## Solution Overview
Change the semantics of `is_idle` and `is_locked` columns from boolean flags to cumulative time counters in seconds, while maintaining the same INTEGER column type.

## Detailed Changes

### 1. Database Schema
No structural changes needed - columns remain INTEGER type, but semantics change:
- `is_idle`: Stores total seconds the system was idle during the session
- `is_locked`: Stores total seconds the system was locked during the session

Files to update:
- `backend/app/models/db/sessions.py`: Update column comments/documentation
- `backend/migrations/versions/0001_create_session_architecture_tables.py`: Update column definitions in upgrade/downgrade functions

### 2. OS Collector (`backend/app/services/os_collector.py`)
No changes needed - the current approach of sending state change events (idle_start/idle_end, locked/unlocked) is ideal for calculating durations.

### 3. Session Coordinator (`backend/app/services/session_coordinator.py`)
**Key Changes:**
- Add instance variables to track state entry timestamps:
  - `_idle_start_timestamp`: When current idle period began (None if not idle)
  - `_locked_start_timestamp`: When current locked period began (None if not locked)

- Modify `_mark_current_os_state()` method:
  - For OSEventType.IDLE_START: 
    - Set `_idle_start_timestamp = payload.timestamp`
    - Set `session.state = "idle"`
  - For OSEventType.IDLE_END:
    - If `_idle_start_timestamp` is not None:
      - Calculate `idle_duration = (payload.timestamp - _idle_start_timestamp).total_seconds()`
      - Add to session: `session.is_idle += int(idle_duration)`
      - Reset `_idle_start_timestamp = None`
    - Set `session.state = "active"`
  - For OSEventType.LOCKED:
    - Set `_locked_start_timestamp = payload.timestamp`
    - Set `session.state = "locked"`
  - For OSEventType.UNLOCKED:
    - If `_locked_start_timestamp` is not None:
      - Calculate `locked_duration = (payload.timestamp - _locked_start_timestamp).total_seconds()`
      - Add to session: `session.is_locked += int(locked_duration)`
      - Reset `_locked_start_timestamp = None`
    - Set `session.state = "active"`

- Update `_open_os_session()` method:
  - Initialize `is_idle=0` and `is_locked=0` (already done)

### 4. Migration Script
Create new Alembic migration (e.g., `0002_change_is_idle_is_locked_to_seconds.py`):

```python
"""change is_idle and is_locked to store seconds instead of flags

Revision ID: 0002_change_is_idle_is_locked_to_seconds
Revises: 0001_create_session_architecture_tables
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_change_is_idle_is_locked_to_seconds"
down_revision = "0001_create_session_architecture_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No structural change needed - columns remain INTEGER
    # Semantic change: now store seconds instead of boolean flags
    # Comment the columns to reflect new meaning
    op.alter_column('os_sessions', 'is_idle',
                    existing_type=sa.Integer(),
                    comment='Total seconds system was idle during session')
    op.alter_column('os_sessions', 'is_locked',
                    existing_type=sa.Integer(),
                    comment='Total seconds system was locked during session')


def downgrade() -> None:
    # Revert to boolean flag semantics (though data will be time values)
    op.alter_column('os_sessions', 'is_idle',
                    existing_type=sa.Integer(),
                    comment=None)
    op.alter_column('os_sessions', 'is_locked',
                    existing_type=sa.Integer(),
                    comment=None)
```

## Implementation Notes

### State Tracking Approach
The session coordinator will track when idle/locked periods begin and calculate durations when they end, similar to how the OS collector works but in the backend where we have access to the session object.

### Handling Edge Cases
1. **Session ends while idle/locked**: The session closing logic in `_close_timed_session()` will need to account for any ongoing idle/locked period
2. **Multiple idle/locked periods**: The accumulator approach handles multiple periods naturally
3. **Clock changes**: Using timestamps from events ensures consistency

### Testing Considerations
- Unit tests for session coordinator state transitions
- Integration tests verifying time accumulation
- Edge case testing (session end during idle/locked state)

## Files to Modify
1. `backend/app/models/db/sessions.py` - Update documentation/comments
2. `backend/app/services/session_coordinator.py` - Add state tracking and time calculation logic
3. `backend/migrations/versions/0001_create_session_architecture_tables.py` - Update column comments in upgrade/downgrade
4. New migration file: `backend/migrations/versions/0002_change_is_idle_is_locked_to_seconds.py`

## Dependencies
- None - this change is self-contained within the session tracking logic