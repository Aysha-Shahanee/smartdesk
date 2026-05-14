# SmartDesk — Option B: Full Session-Based Architecture Plan

> **Scope**: Complete professional redesign of data collection, storage, and dashboard API  
> **Replaces**: All three minute-window tables  
> **Target**: Long-term production desktop application for developer productivity tracking

---

## Part 1 — Architecture Overview

### Core Principle

The OS monitor is the **single source of truth for session boundaries and timestamps**. The VS Code and browser extensions are **detail providers only** — they enrich sessions with app-specific data but never own the session timeline.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Developer's Machine                       │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  OS Monitor  │   │  VS Code Ext │   │  Browser Ext     │    │
│  │  (Python)    │   │  (TypeScript)│   │  (JS / MV3)      │    │
│  │              │   │              │   │                  │    │
│  │ · Foreground │   │ · File switch│   │ · Tab switch     │    │
│  │   window     │   │ · Focus gain │   │ · Window focus   │    │
│  │ · App switch │   │ · Focus lost │   │ · Idle state     │    │
│  │ · Idle/Lock  │   │ · Counters   │   │ · Domain/category│    │
│  └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘    │
│         │                  │                     │              │
│         └──────────────────┼─────────────────────┘              │
│                            │  HTTP POST to localhost             │
│                            ▼                                     │
│              ┌─────────────────────────┐                        │
│              │   FastAPI Backend        │                        │
│              │                         │                        │
│              │  · Session coordinator  │                        │
│              │  · PID cross-matching   │                        │
│              │  · Safety timeout job   │                        │
│              │  · Dashboard service    │                        │
│              └───────────┬─────────────┘                        │
│                          │                                       │
│                          ▼                                       │
│              ┌─────────────────────────┐                        │
│              │   SQLite Database        │                        │
│              │   (smartdesk.db)         │                        │
│              │                         │                        │
│              │  · os_sessions          │                        │
│              │  · vscode_sessions      │                        │
│              │  · browser_sessions     │                        │
│              │  · calendar_events      │                        │
│              │  · work_periods         │                        │
│              └─────────────────────────┘                        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  Desktop Dashboard App                   │    │
│  │   GET /dashboard/os  ·  /dashboard/ide  ·  /dashboard/browser │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Session Authority Rules

| Event Type | Authority | Other Source Role |
|---|---|---|
| App A → App B switch | OS Monitor | Extension sends detail data |
| VS Code Window 1 → Window 2 | VS Code Extension | OS validates app is still "Code" |
| Browser Tab A → Tab B | Browser Extension | OS validates app is still "Chrome" |
| File switch inside VS Code | VS Code Extension | OS not involved |
| Screen lock / idle | OS Monitor | Sessions remain open during idle |
| OS suspend / shutdown | OS Monitor | Backend closes current sessions immediately |
| Abandoned / broken session | Backend job | Safety net only for crash/sleep/shutdown failures |

---

## Part 2 — Session Lifecycle

### What Is a Session?

A **session** is one continuous, uninterrupted period of activity on a specific context:
- OS session = one foreground app/window period
- VS Code session = one foreground VS Code window + one active file
- Browser session = one foreground browser window + one active tab

A new session starts when **any** of these change. The old session closes simultaneously. Idle alone does **not** close a session.

### Updated Session Lifecycle

```
Session opens → on app/file/tab focus event
Session stays open during idle
Session closes → next focus/switch event
Session closes → OS suspend signal
Timeout closes → only abandoned/broken sessions (shutdown/sleep/system crash)
```

### Session Open Flow

```
1. Trigger event occurs (app switch / file switch / tab switch)

2. Source sends POST /api/v1/ingest/{source}/event
   { event: "started", instance_id, process_id, timestamp, ...detail }

3. Backend:
   a. Close any currently open session for this instance_id
      → set end_time, calculate duration_sec, set closed_by reason
   b. Create new session row with end_time = NULL (open)
   c. Cross-check with OS: is this process_id the current foreground?
      → set is_foreground = 1 or 0
   d. Return { session_id, accepted: true }
```

### Session Close Flow

```
NORMAL CLOSE (triggered by next focus/switch event):
  Next app/file/tab focus or switch event arrives
  → backend closes previous session as part of step 3a

IDLE:
  No close event is emitted for idle alone
  → current session remains open until the next focus/switch event or suspend signal

EXPLICIT CLOSE (extension sends suspend/deactivate):
  POST /api/v1/ingest/{source}/event
  { event: "ended", instance_id, timestamp, counters: {...} }
  → Backend closes session, attaches counters to the closing row

TIMEOUT CLOSE (backend safety net only):
  Background job runs every 60 seconds
  → Finds sessions that are clearly abandoned/broken
     (shutdown/sleep/system crash prevented a normal close)
  → Closes them with closed_by = "timeout"
  → Uses the last known heartbeat/event timestamp when available
```

### Multi-Window Session Flow

```
STATE: Two VS Code windows open
  Window 1: PID 1234, workspace "projectA"  → instance_id = AAA
  Window 2: PID 5678, workspace "projectB"  → instance_id = BBB

USER IS IN Window 1:
  OS Monitor: foreground PID = 1234
  DB state:
    vscode_sessions row A: instance=AAA, pid=1234, is_foreground=1, end_time=NULL  ← OPEN
    vscode_sessions row B: instance=BBB, pid=5678, is_foreground=0, end_time=NULL  ← OPEN

USER SWITCHES TO Window 2 (alt+tab):
  OS Monitor fires:
    POST /ingest/os/event { event:"focused", app:"code", pid:5678, title:"projectB..." }
    POST /ingest/os/event { event:"blurred", app:"code", pid:1234 }

  Backend:
    → Finds open OS session for pid=1234, closes it
    → Opens new OS session for pid=5678
    → Updates vscode_sessions: set is_foreground=0 WHERE process_id=1234
    → Updates vscode_sessions: set is_foreground=1 WHERE process_id=5678

  VS Code Window 2 extension fires independently:
    POST /ingest/vscode/event { event:"started", instance_id:BBB, pid:5678, ... }
    → Backend sees instance BBB already has open session → refreshes is_foreground=1
    → No duplicate row created

  Result: Both windows tracked, is_foreground flag accurate ✅
```

### 3-Second Minimum Duration Rule

Browser tab sessions under 3 seconds are discarded from duration totals on close — user was scanning, not using. Keep the tab switch event/count so rapid switching still helps detect distraction patterns.

```python
MIN_BROWSER_SESSION_SEC = 3

def close_browser_session(session_id, end_time, counters, db):
    session = db.get(BrowserSessionRecord, session_id)
    duration = (end_time - parse(session.session_start)).total_seconds()

    if duration < MIN_BROWSER_SESSION_SEC:
        # Discard duration row, but keep/increment switch telemetry separately.
        self._record_browser_switch(session, counters, db)
        db.delete(session)
        db.commit()
        return

    session.session_end = end_time.isoformat()
    session.duration_sec = int(duration)
    session.closed_by = "next_session"
    db.commit()
```

---

## Part 3 — Complete Database Schema

### Table 1: `os_sessions`

One row = one continuous foreground period for one app/window on the OS.

```python
class OSSessionRecord(Base):
    __tablename__ = "os_sessions"

    # Identity
    id            = Column(String, primary_key=True)      # UUID
    user_id       = Column(String, index=True, nullable=False)

    # App info (from OS)
    app_name      = Column(String, nullable=False)         # "Code", "Chrome", "Slack"
    app_category  = Column(String, nullable=True)          # "IDE", "Browser", "Communication", "Other"
    window_title  = Column(String, nullable=True)          # "projectA — Visual Studio Code"
    process_id    = Column(Integer, nullable=True)         # OS PID

    # State
    state         = Column(String, nullable=False, default="active")  # "active" | "idle" | "locked"
    is_idle       = Column(Integer, nullable=False, default=0)        # 0 or 1
    is_locked     = Column(Integer, nullable=False, default=0)        # 0 or 1

    # Session timing
    session_start = Column(String, index=True, nullable=False)        # ISO8601 with timezone
    session_end   = Column(String, nullable=True)                     # NULL = still open
    duration_sec  = Column(Integer, nullable=True)                    # set on close

    # Session metadata
    trigger       = Column(String, nullable=True)          # "app_switch" | "idle" | "unlock" | "suspend" | "shutdown"
    closed_by     = Column(String, nullable=True)          # "next_event" | "timeout" | "suspend" | "shutdown"

    # Extensibility
    extra_data    = Column(String, nullable=True)           # JSON blob

    # Audit
    created_at    = Column(String, nullable=False)
    updated_at    = Column(String, nullable=False)
```

**No unique constraint** — OS can open multiple sessions for the same app in a day. Each gets its own UUID.

**Indexes**: `user_id`, `session_start`, `process_id`, `app_name`

---

### Table 2: `vscode_sessions`

One row = one continuous period in one VS Code window with one active file.

```python
class VSCodeSessionRecord(Base):
    __tablename__ = "vscode_sessions"

    # Identity
    id            = Column(String, primary_key=True)       # UUID (generated by backend)
    user_id       = Column(String, index=True, nullable=False)
    instance_id   = Column(String, index=True, nullable=False)  # UUID per VS Code window (from extension)
    process_id    = Column(Integer, index=True, nullable=True)  # OS PID (from extension)

    # VS Code context
    workspace_name     = Column(String, nullable=True)     # workspace/folder name
    project_path       = Column(String, nullable=True)     # full path (local only, not sent to cloud)
    repo_id            = Column(String, nullable=True)     # hashed git remote URL
    git_branch         = Column(String, nullable=True)
    active_file_path   = Column(String, nullable=True)
    active_file_name   = Column(String, nullable=True)
    active_language    = Column(String, nullable=True)     # "python", "typescript", etc.

    # Session timing
    session_start = Column(String, index=True, nullable=False)
    session_end   = Column(String, nullable=True)          # NULL = still open
    duration_sec  = Column(Integer, nullable=True)         # set on close
    idle_sec      = Column(Integer, nullable=True, default=0)  # idle time within this session

    # Foreground status (set by backend via OS cross-check)
    is_foreground    = Column(Integer, nullable=False, default=0)   # 0 or 1
    foreground_sec   = Column(Integer, nullable=True, default=0)    # actual foreground time
    confirmed_by_os  = Column(Integer, nullable=False, default=0)   # 0 or 1

    # Session metadata
    trigger    = Column(String, nullable=True)  # "file_switch" | "window_focus" | "app_focus" | "deactivate"
    closed_by  = Column(String, nullable=True)  # "next_session" | "timeout" | "deactivate" | "suspend"

    # Activity counters (accumulated during session, sent on close)
    edit_count             = Column(Integer, nullable=False, default=0)
    save_count             = Column(Integer, nullable=False, default=0)
    lines_added            = Column(Integer, nullable=False, default=0)
    lines_deleted          = Column(Integer, nullable=False, default=0)
    file_switch_count      = Column(Integer, nullable=False, default=0)
    terminal_command_count = Column(Integer, nullable=False, default=0)
    debug_run_count        = Column(Integer, nullable=False, default=0)

    # Extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

    # Audit
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
```

**Indexes**: `user_id`, `instance_id`, `process_id`, `session_start`, `is_foreground`

---

### Table 3: `browser_sessions`

One row = one continuous period on one browser tab in one browser window.

```python
class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"

    # Identity
    id                = Column(String, primary_key=True)   # UUID (generated by backend)
    user_id           = Column(String, index=True, nullable=False)
    browser_name      = Column(String, nullable=False)     # "Chrome" | "Edge" | "Firefox"
    browser_window_id = Column(Integer, index=True, nullable=True)  # chrome.windows ID
    tab_id            = Column(Integer, nullable=True)     # chrome.tabs ID
    process_id        = Column(Integer, nullable=True)     # OS PID of browser

    # Tab context
    domain    = Column(String, index=True, nullable=True)  # "github.com"
    url       = Column(String, nullable=True)
    title     = Column(String, nullable=True)
    category  = Column(String, nullable=True)  # "Focused" | "Distracted" | "Neutral" | "Communication"

    # Session timing
    session_start = Column(String, index=True, nullable=False)
    session_end   = Column(String, nullable=True)          # NULL = still open
    duration_sec  = Column(Integer, nullable=True)         # set on close

    # Foreground status
    is_foreground   = Column(Integer, nullable=False, default=0)
    confirmed_by_os = Column(Integer, nullable=False, default=0)

    # Session metadata
    trigger   = Column(String, nullable=True)   # "tab_switch" | "window_focus" | "app_focus"
    closed_by = Column(String, nullable=True)   # "next_session" | "timeout" | "suspend"

    # Extensibility
    extra_data = Column(String, nullable=True)  # JSON blob

    # Audit
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
```

**Indexes**: `user_id`, `browser_window_id`, `session_start`, `domain`, `is_foreground`

---

### Table 4: `calendar_events` (unchanged, minor additions)

```python
class CalendarEventRecord(Base):
    __tablename__ = "calendar_events"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(String, index=True, nullable=False)
    event_id        = Column(String, index=True, nullable=False)   # Google Calendar event ID

    title           = Column(String, nullable=True)
    start_time      = Column(String, nullable=False)
    end_time        = Column(String, nullable=False)
    timezone        = Column(String, nullable=False)
    duration_sec    = Column(Integer, nullable=True)               # NEW: pre-calculated
    attendees_count = Column(Integer, nullable=True, default=0)
    is_recurring    = Column(Integer, nullable=False, default=0)
    status          = Column(String, nullable=True)                # NEW: "confirmed" | "tentative" | "cancelled"

    extra_data  = Column(String, nullable=True)
    source      = Column(String, nullable=False, default="google_calendar")
    created_at  = Column(String, nullable=False)
    updated_at  = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_calendar_events"),
    )
```

---

### Table 5: `work_periods` (replaces `activity_session_summary`)

A **work period** is a logical block of work — a continuous stretch of activity with no gap longer than 30 minutes. The dashboard timeline shows work periods; the summary panels aggregate within them.

```python
class WorkPeriodRecord(Base):
    __tablename__ = "work_periods"

    id           = Column(String, primary_key=True)        # UUID
    user_id      = Column(String, index=True, nullable=False)

    # Period boundary (set by backend scheduler)
    period_start = Column(String, index=True, nullable=False)
    period_end   = Column(String, nullable=True)           # NULL = current active period
    duration_sec = Column(Integer, nullable=True)

    # Which sources contributed data
    has_os_data       = Column(Integer, nullable=False, default=0)
    has_vscode_data   = Column(Integer, nullable=False, default=0)
    has_browser_data  = Column(Integer, nullable=False, default=0)
    has_calendar_data = Column(Integer, nullable=False, default=0)

    # Dominant source during this period
    primary_source = Column(String, nullable=True)  # "vscode" | "browser" | "os"

    # Audit
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "period_start", name="uq_work_periods"),
    )
```

**Work period logic**: The background scheduler runs every 60 seconds. It looks at all sessions in the last 30 minutes. If any session exists, the current work period stays open. If there has been no session activity for 30 minutes, the current work period is closed and the next one will start fresh when activity resumes.

---

### Schema Relationships

```
work_periods
    ↑ (time window query)
    │
    ├── os_sessions        (WHERE session_start >= period_start AND session_end <= period_end)
    ├── vscode_sessions    (same window, WHERE is_foreground = 1 for dashboard)
    ├── browser_sessions   (same window, WHERE is_foreground = 1 AND duration_sec >= 5)
    └── calendar_events    (WHERE start_time overlaps period window)
```

No foreign keys — the relationship is purely temporal (time window overlap). This keeps queries simple and allows partial data (e.g., only OS data with no extension data) without nulls on FK columns.

---

## Part 4 — Signal Flow & API Contract (Ingest Side)

### OS Monitor Events

```http
POST /api/v1/ingest/os/event
Content-Type: application/json

{
  "user_id": "local_user",
  "event":   "focused",           // "focused" | "blurred" | "idle_start" | "idle_end" | "locked" | "unlocked" | "suspend" | "shutdown"
  "app_name":    "Code",
  "app_category": "IDE",
  "window_title": "projectA — Visual Studio Code",
  "process_id":   1234,
  "timestamp":    "2026-05-07T10:23:45+05:30"
}
```

**Response:**
```json
{ "session_id": "uuid-of-opened-or-closed-session", "status": "opened" | "closed" }
```

### VS Code Extension Events

```http
POST /api/v1/ingest/vscode/event
Content-Type: application/json

// SESSION START (file switch, window/app focus gained)
{
  "user_id":       "local_user",
  "event":         "started",         // "started" | "ended"
  "instance_id":   "uuid-per-window",
  "process_id":    1234,
  "trigger":       "file_switch",     // "file_switch" | "window_focus" | "app_focus"
  "workspace_name": "projectA",
  "project_path":   "/home/dev/projectA",
  "repo_id":        "a3f9c821",       // hashed git remote URL
  "git_branch":     "main",
  "active_file_path": "/home/dev/projectA/app/main.py",
  "active_file_name": "main.py",
  "active_language":  "python",
  "timestamp":      "2026-05-07T10:23:45+05:30"
}

// SESSION END (deactivation, suspend/shutdown, or backend close on next focus/switch)
{
  "user_id":     "local_user",
  "event":       "ended",
  "instance_id": "uuid-per-window",
  "process_id":  1234,
  "trigger":     "deactivate",
  "timestamp":   "2026-05-07T10:25:12+05:30",
  "counters": {
    "edit_count":             14,
    "save_count":              2,
    "lines_added":            38,
    "lines_deleted":           5,
    "file_switch_count":       3,
    "terminal_command_count":  0,
    "debug_run_count":         0,
    "idle_sec":               12
  }
}
```

**Response:**
```json
{ "session_id": "uuid", "status": "opened" | "closed", "is_foreground": true }
```

### Browser Extension Events

```http
POST /api/v1/ingest/browser/event
Content-Type: application/json

// TAB/WINDOW SESSION START
{
  "user_id":           "local_user",
  "event":             "started",        // "started" | "ended"
  "browser_name":      "Chrome",
  "browser_window_id": 1,
  "tab_id":            42,
  "process_id":        5678,
  "trigger":           "tab_switch",     // "tab_switch" | "window_focus" | "app_focus"
  "domain":            "github.com",
  "url":               "https://github.com/user/repo/pulls",
  "title":             "Pull Requests · user/repo",
  "category":          "Focused",
  "timestamp":         "2026-05-07T10:26:00+05:30"
}

// SESSION END
{
  "user_id":           "local_user",
  "event":             "ended",
  "browser_name":      "Chrome",
  "browser_window_id": 1,
  "tab_id":            42,
  "process_id":        5678,
  "timestamp":         "2026-05-07T10:28:30+05:30"
}
```

---

## Part 5 — Backend Structure

### File Layout

```
backend/
├── alembic/
│   └── versions/
│       ├── 001_create_os_sessions.py
│       ├── 002_create_vscode_sessions.py
│       ├── 003_create_browser_sessions.py
│       ├── 004_create_calendar_events.py
│       └── 005_create_work_periods.py
├── app/
│   ├── core/
│   │   ├── config.py           # All settings via pydantic-settings
│   │   ├── database.py         # Engine, SessionLocal, get_db
│   │   └── logging.py          # Logging setup
│   ├── models/
│   │   ├── db/                 # SQLAlchemy ORM
│   │   │   ├── os_session.py
│   │   │   ├── vscode_session.py
│   │   │   ├── browser_session.py
│   │   │   ├── calendar_event.py
│   │   │   └── work_period.py
│   │   └── schemas/            # Pydantic request/response
│   │       ├── ingest.py       # All ingest payloads
│   │       └── dashboard.py    # All dashboard responses
│   ├── repositories/
│   │   ├── os_session_repository.py
│   │   ├── vscode_session_repository.py
│   │   ├── browser_session_repository.py
│   │   ├── calendar_repository.py
│   │   └── work_period_repository.py
│   ├── services/
│   │   ├── session_coordinator.py    # Core: opens/closes sessions, PID matching
│   │   ├── foreground_resolver.py    # Cross-checks extension PIDs against OS state
│   │   ├── dashboard_service.py      # Aggregation for all 3 dashboard panels
│   │   ├── work_period_scheduler.py  # Background: opens/closes work periods
│   │   ├── session_timeout_job.py    # Background: closes abandoned/broken sessions
│   │   ├── os_collector.py           # OS foreground monitor (moved from core)
│   │   └── calendar_sync.py          # Google Calendar sync
│   ├── routes/
│   │   ├── ingest/
│   │   │   ├── os.py
│   │   │   ├── vscode.py
│   │   │   └── browser.py
│   │   ├── dashboard.py
│   │   ├── sessions.py
│   │   └── health.py
│   └── main.py
└── tests/
    ├── test_session_coordinator.py
    ├── test_foreground_resolver.py
    ├── test_dashboard_service.py
    └── test_timeout_job.py
```

### Session Coordinator (Core Service)

```python
# app/services/session_coordinator.py

class SessionCoordinator:

    def handle_os_event(self, payload: OSEventPayload, db: Session) -> dict:
        if payload.event == "focused":
            self._close_current_os_session(payload, db)
            session_id = self._open_os_session(payload, db)
            self._update_foreground_flags(payload.process_id, db)
            return {"session_id": session_id, "status": "opened"}

        elif payload.event == "blurred":
            # Blur alone does not close. The next focused/switch event closes
            # the previous session and opens the replacement.
            return {"status": "ignored"}

        elif payload.event in ("idle_start", "idle_end", "locked", "unlocked"):
            # Idle/lock state enriches the current session but does not split it.
            self._mark_os_state(payload, db)
            return {"status": "state_updated"}

        elif payload.event in ("suspend", "shutdown"):
            self._close_current_os_session(payload, db)
            self._close_all_open_extension_sessions(payload.timestamp, db)
            return {"status": "closed_by_os_signal"}

    def handle_vscode_event(self, payload: VSCodeEventPayload, db: Session) -> dict:
        if payload.event == "started":
            # Close previous session for this instance
            self._close_vscode_session(payload.instance_id, payload.timestamp, None, db)
            # Open new session
            session_id = self._open_vscode_session(payload, db)
            # Check if this PID is currently OS foreground
            is_fg = self._is_foreground(payload.process_id, db)
            self._set_foreground(session_id, is_fg, db)
            return {"session_id": session_id, "status": "opened", "is_foreground": is_fg}

        elif payload.event == "ended":
            self._close_vscode_session(
                payload.instance_id, payload.timestamp, payload.counters, db
            )
            return {"status": "closed"}

    def handle_browser_event(self, payload: BrowserEventPayload, db: Session) -> dict:
        if payload.event == "started":
            self._close_browser_session(
                payload.browser_window_id, payload.tab_id, payload.timestamp, None, db
            )
            session_id = self._open_browser_session(payload, db)
            is_fg = self._is_foreground(payload.process_id, db)
            self._set_foreground(session_id, is_fg, db)
            return {"session_id": session_id, "status": "opened", "is_foreground": is_fg}

        elif payload.event == "ended":
            self._close_browser_session(
                payload.browser_window_id, payload.tab_id, payload.timestamp, None, db
            )
            return {"status": "closed"}

    def _is_foreground(self, process_id: int, db: Session) -> bool:
        """Check latest OS session to see if this PID is the current foreground."""
        latest_os = db.query(OSSessionRecord)\
            .filter(
                OSSessionRecord.process_id == process_id,
                OSSessionRecord.session_end == None,
                OSSessionRecord.state == "active"
            ).first()
        return latest_os is not None

    def _update_foreground_flags(self, foreground_pid: int, db: Session):
        """When OS focus changes, update is_foreground on all open extension sessions."""
        # Set all open vscode sessions is_foreground=0
        db.query(VSCodeSessionRecord)\
          .filter(VSCodeSessionRecord.session_end == None)\
          .update({"is_foreground": 0, "confirmed_by_os": 1})
        # Set the one matching PID to is_foreground=1
        db.query(VSCodeSessionRecord)\
          .filter(
              VSCodeSessionRecord.session_end == None,
              VSCodeSessionRecord.process_id == foreground_pid
          ).update({"is_foreground": 1})

        # Same for browser sessions
        db.query(BrowserSessionRecord)\
          .filter(BrowserSessionRecord.session_end == None)\
          .update({"is_foreground": 0, "confirmed_by_os": 1})
        db.query(BrowserSessionRecord)\
          .filter(
              BrowserSessionRecord.session_end == None,
              BrowserSessionRecord.process_id == foreground_pid
          ).update({"is_foreground": 1})

        db.commit()
```

### Session Timeout Job

```python
# app/services/session_timeout_job.py
import threading
from datetime import datetime, timezone, timedelta

BROKEN_SESSION_TIMEOUT_SEC = 30 * 60
JOB_INTERVAL_SEC = 60

class SessionTimeoutJob:
    def __init__(self, db_factory):
        self.db_factory = db_factory
        self._timer = None

    def start(self):
        self._run()

    def _run(self):
        self._close_stale_sessions()
        self._timer = threading.Timer(JOB_INTERVAL_SEC, self._run)
        self._timer.daemon = True
        self._timer.start()

    def _close_stale_sessions(self):
        db = self.db_factory()
        try:
            threshold = (
                datetime.now(timezone.utc) -
                timedelta(seconds=BROKEN_SESSION_TIMEOUT_SEC)
            ).isoformat()
            now = datetime.now(timezone.utc).isoformat()

            for Model in [OSSessionRecord, VSCodeSessionRecord, BrowserSessionRecord]:
                stale = db.query(Model).filter(
                    Model.session_end == None,
                    Model.updated_at < threshold
                ).all()
                for s in stale:
                    s.session_end = now
                    s.duration_sec = seconds_between(s.session_start, now)
                    s.closed_by = "timeout"
                    s.updated_at = now

            db.commit()
        finally:
            db.close()
```

---

## Part 6 — VS Code Extension Changes

### Full List of Changes

```typescript
// extension.ts

import * as vscode from 'vscode';
import * as crypto from 'crypto';
import * as os from 'os';

// ── 1. INSTANCE IDENTITY ──────────────────────────────────────────
// Generated once per VS Code window activation. Unique per window.
const INSTANCE_ID: string = crypto.randomUUID();
const PROCESS_ID: number = process.pid;

// ── 2. DYNAMIC CONFIG (from VS Code settings) ─────────────────────
function getConfig() {
    const cfg = vscode.workspace.getConfiguration('smartdesk');
    return {
        userId:     cfg.get<string>('userId')?.trim() || os.hostname(),
        backendUrl: cfg.get<string>('backendUrl') || 'http://localhost:8000',
    };
}

// ── 3. DYNAMIC TIMEZONE ───────────────────────────────────────────
function getTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function nowISO(): string {
    const now = new Date();
    const offsetMs = -now.getTimezoneOffset() * 60 * 1000;
    const local = new Date(now.getTime() + offsetMs);
    const sign = offsetMs >= 0 ? '+' : '-';
    const abs = Math.abs(now.getTimezoneOffset());
    const hh = String(Math.floor(abs / 60)).padStart(2, '0');
    const mm = String(abs % 60).padStart(2, '0');
    return local.toISOString().replace('Z', `${sign}${hh}:${mm}`);
}

// ── 4. COUNTERS (accumulated during current session) ──────────────
type Counters = {
    edit_count: number;
    save_count: number;
    lines_added: number;
    lines_deleted: number;
    file_switch_count: number;
    terminal_command_count: number;
    debug_run_count: number;
    idle_sec: number;
};

function freshCounters(): Counters {
    return {
        edit_count: 0, save_count: 0,
        lines_added: 0, lines_deleted: 0,
        file_switch_count: 0,
        terminal_command_count: 0,
        debug_run_count: 0, idle_sec: 0,
    };
}

// ── 5. HASHED REPO ID ─────────────────────────────────────────────
function hashRepoId(remoteUrl: string): string {
    let hash = 0;
    for (let i = 0; i < remoteUrl.length; i++) {
        hash = ((hash << 5) - hash) + remoteUrl.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash).toString(16).padStart(8, '0');
}

async function getGitInfo(wf: vscode.WorkspaceFolder | undefined) {
    // ... read .git/HEAD and .git/config as before ...
    // hash the remote URL before returning:
    // repoId = hashRepoId(rawRemoteUrl)
}

// ── 6. SESSION EVENTS ─────────────────────────────────────────────
let counters: Counters = freshCounters();
let lastIdleCheckMs = Date.now();
const IDLE_THRESHOLD_MS = 60_000;

async function sendSessionStart(trigger: string) {
    const editor = vscode.window.activeTextEditor;
    const wf = vscode.workspace.workspaceFolders?.[0];
    const git = await getGitInfo(wf);

    const payload = {
        user_id:     getConfig().userId,
        event:       'started',
        instance_id: INSTANCE_ID,
        process_id:  PROCESS_ID,
        trigger,
        workspace_name:   wf?.name ?? null,
        project_path:     wf?.uri.fsPath ?? null,
        repo_id:          git?.repoId ?? null,
        git_branch:       git?.branch ?? null,
        active_file_path: editor?.document.uri.fsPath ?? null,
        active_file_name: editor?.document.fileName.split('/').pop() ?? null,
        active_language:  editor?.document.languageId ?? null,
        timestamp:        nowISO(),
    };

    await sendWithRetry(`${getConfig().backendUrl}/api/v1/ingest/vscode/event`, payload);
}

async function sendSessionEnd(trigger: string) {
    const payload = {
        user_id:     getConfig().userId,
        event:       'ended',
        instance_id: INSTANCE_ID,
        process_id:  PROCESS_ID,
        trigger,
        timestamp:   nowISO(),
        counters: { ...counters },
    };

    counters = freshCounters(); // reset immediately
    await sendWithRetry(`${getConfig().backendUrl}/api/v1/ingest/vscode/event`, payload);
}

// ── 7. OFFLINE BUFFER & RETRY ─────────────────────────────────────
const pendingQueue: object[] = [];

async function sendWithRetry(url: string, payload: object): Promise<void> {
    const toSend = [...pendingQueue, payload];
    pendingQueue.length = 0;

    for (const p of toSend) {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(p),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
            output.appendLine(`[SmartDesk] Queued for retry: ${err}`);
            pendingQueue.push(p);
        }
    }
}

// ── 8. EVENT LISTENERS ────────────────────────────────────────────
export function activate(context: vscode.ExtensionContext) {

    // File switch → new session
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(async () => {
            counters.file_switch_count++;
            await sendSessionStart('file_switch');
        })
    );

    // Window focus gained → close previous session and start current focused context
    context.subscriptions.push(
        vscode.window.onDidChangeWindowState(async (state) => {
            if (state.focused) {
                await sendSessionStart('window_focus');
            }
        })
    );

    // Edit counter (logical edits, not contentChanges.length)
    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument((e) => {
            if (e.contentChanges.length === 0) return;
            for (const change of e.contentChanges) {
                const newLines = change.text.split('\n').length - 1;
                const oldLines = change.range.end.line - change.range.start.line;
                counters.lines_added   += Math.max(0, newLines - oldLines);
                counters.lines_deleted += Math.max(0, oldLines - newLines);
            }
            counters.edit_count++;
        })
    );

    // Save counter
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(() => {
            counters.save_count++;
        })
    );

    // Terminal command counter
    context.subscriptions.push(
        vscode.window.onDidEndTerminalShellExecution(() => {
            counters.terminal_command_count++;
        })
    );

    // Debug run counter
    context.subscriptions.push(
        vscode.debug.onDidStartDebugSession(() => {
            counters.debug_run_count++;
        })
    );

    // Session opens only when the app/file focus event is observed.
}

export async function deactivate() {
    await sendSessionEnd('deactivate');
}
```

---

## Part 7 — Browser Extension Changes

### Full List of Changes

```javascript
// background.js — Service Worker (MV3)

// ── 1. ALL STATE PERSISTED TO STORAGE IMMEDIATELY ─────────────────
// Service workers die after ~30s. Never trust in-memory variables.

async function getState() {
    return new Promise((resolve) => {
        chrome.storage.local.get({
            currentSession: null,   // { tabId, windowId, domain, url, title, category, startTime }
            pendingQueue:   [],     // failed POSTs to retry
        }, resolve);
    });
}

async function setState(updates) {
    return new Promise((resolve) => chrome.storage.local.set(updates, resolve));
}

// ── 2. DYNAMIC CONFIG VIA OPTIONS PAGE ────────────────────────────
async function getConfig() {
    return new Promise((resolve) => {
        chrome.storage.sync.get({
            userId:     '',
            backendUrl: 'http://127.0.0.1:8000',
        }, (cfg) => {
            resolve({
                userId:     cfg.userId || 'local_user',
                backendUrl: cfg.backendUrl,
            });
        });
    });
}

// ── 3. DYNAMIC TIMEZONE ───────────────────────────────────────────
function getTimezone() {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function nowISO() {
    const now = new Date();
    const offsetMs = -now.getTimezoneOffset() * 60000;
    const local = new Date(now.getTime() + offsetMs);
    const sign = offsetMs >= 0 ? '+' : '-';
    const abs = Math.abs(now.getTimezoneOffset());
    const hh = String(Math.floor(abs / 60)).padStart(2, '0');
    const mm = String(abs % 60).padStart(2, '0');
    return local.toISOString().replace('Z', `${sign}${hh}:${mm}`);
}

// ── 4. BROWSER NAME (reliable detection) ─────────────────────────
function getBrowserName() {
    if (typeof browser !== 'undefined') return 'Firefox';
    if (navigator.userAgent.includes('Edg/')) return 'Edge';
    return 'Chrome';
}

// ── 5. CATEGORY CLASSIFICATION (with dev allowlist) ───────────────
const FOCUSED_DOMAINS = [
    'github.com', 'gitlab.com', 'stackoverflow.com', 'docs.python.org',
    'developer.mozilla.org', 'devdocs.io', 'npmjs.com', 'pypi.org',
    'jira.atlassian.com', 'linear.app', 'figma.com', 'vercel.com',
    'cloudflare.com', 'aws.amazon.com', 'console.cloud.google.com',
];
const DISTRACTED_DOMAINS = [
    'youtube.com', 'twitter.com', 'x.com', 'instagram.com',
    'facebook.com', 'tiktok.com', 'netflix.com', 'twitch.tv',
];
const COMMUNICATION_DOMAINS = [
    'mail.google.com', 'outlook.live.com', 'slack.com',
    'discord.com', 'teams.microsoft.com', 'zoom.us',
];
const DEV_SUBREDDITS = [
    'programming', 'learnprogramming', 'webdev', 'javascript',
    'python', 'devops', 'MachineLearning', 'typescript',
];

function classifyTab(url, title) {
    if (!url) return 'Neutral';
    const text = (url + ' ' + (title || '')).toLowerCase();

    if (COMMUNICATION_DOMAINS.some(d => text.includes(d))) return 'Communication';

    if (text.includes('reddit.com')) {
        if (DEV_SUBREDDITS.some(s => text.includes(`/r/${s.toLowerCase()}`))) return 'Focused';
        return 'Distracted';
    }

    if (FOCUSED_DOMAINS.some(d => text.includes(d))) return 'Focused';
    if (DISTRACTED_DOMAINS.some(d => text.includes(d))) return 'Distracted';
    return 'Neutral';
}

// ── 6. SESSION EVENTS ─────────────────────────────────────────────
async function sendSessionStart(tab, trigger) {
    const cfg    = await getConfig();
    const win    = await chrome.windows.getCurrent().catch(() => null);
    const domain = tab.url ? new URL(tab.url).hostname : null;

    const payload = {
        user_id:           cfg.userId,
        event:             'started',
        browser_name:      getBrowserName(),
        browser_window_id: win?.id ?? null,
        tab_id:            tab.id ?? null,
        process_id:        null,           // Browser PID not accessible from extension
        trigger,
        domain,
        url:               tab.url   ?? null,
        title:             tab.title ?? null,
        category:          classifyTab(tab.url, tab.title),
        timestamp:         nowISO(),
    };

    // Save current session to storage BEFORE sending
    await setState({ currentSession: {
        tabId: tab.id, windowId: win?.id,
        domain, url: tab.url, title: tab.title,
        category: payload.category,
        startTime: payload.timestamp,
    }});

    await sendWithRetry(`${cfg.backendUrl}/api/v1/ingest/browser/event`, payload);
}

async function sendSessionEnd(trigger) {
    const cfg   = await getConfig();
    const state = await getState();
    if (!state.currentSession) return;

    const payload = {
        user_id:           cfg.userId,
        event:             'ended',
        browser_name:      getBrowserName(),
        browser_window_id: state.currentSession.windowId,
        tab_id:            state.currentSession.tabId,
        process_id:        null,
        trigger,
        timestamp:         nowISO(),
    };

    await setState({ currentSession: null });
    await sendWithRetry(`${cfg.backendUrl}/api/v1/ingest/browser/event`, payload);
}

async function sendIdleStateEvent(state) {
    const cfg = await getConfig();
    await sendWithRetry(`${cfg.backendUrl}/api/v1/ingest/browser/event`, {
        user_id:      cfg.userId,
        event:        'state',
        browser_name: getBrowserName(),
        trigger:      state,
        timestamp:    nowISO(),
    });
}

// ── 7. OFFLINE BUFFER & RETRY ─────────────────────────────────────
async function sendWithRetry(url, payload) {
    const state = await getState();
    const toSend = [...state.pendingQueue, payload];
    await setState({ pendingQueue: [] });

    const failed = [];
    for (const p of toSend) {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(p),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
            failed.push(p);
        }
    }

    if (failed.length > 0) {
        // Cap queue at 100 items to prevent storage bloat
        const capped = failed.slice(-100);
        await setState({ pendingQueue: capped });
    }
}

// ── 8. EVENT LISTENERS ────────────────────────────────────────────
chrome.tabs.onActivated.addListener(async (info) => {
    const tab = await chrome.tabs.get(info.tabId);
    await sendSessionStart(tab, 'tab_switch');
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    // Only fire when URL changes on the ACTIVE tab (navigation)
    if (changeInfo.url) {
        const active = await chrome.tabs.query({ active: true, currentWindow: true });
        if (active[0]?.id === tabId) {
            await sendSessionStart(tab, 'navigation');
        }
    }
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
    if (windowId === chrome.windows.WINDOW_ID_NONE) {
        // Idle/blur does not close the session. The next focus/switch event will.
        return;
    } else {
        const tabs = await chrome.tabs.query({ active: true, windowId });
        if (tabs[0]) {
            await sendSessionStart(tabs[0], 'window_focus');
        }
    }
});

chrome.idle.onStateChanged.addListener(async (state) => {
    // Idle state does not close or reopen sessions. It can be reported as
    // metadata, while the active session remains open.
    await sendIdleStateEvent(state);
});

chrome.idle.setDetectionInterval(60);
```

---

## Part 8 — Dashboard API Contract

### Endpoints

```
GET /dashboard/os?user_id=local_user&from=2026-05-07T00:00:00+05:30&to=2026-05-07T23:59:59+05:30
GET /dashboard/ide?user_id=local_user&from=...&to=...
GET /dashboard/browser?user_id=local_user&from=...&to=...
GET /dashboard/timeline?user_id=local_user&from=...&to=...
GET /dashboard/sessions?user_id=local_user&from=...&to=...
```

### Response Schemas

```python
# OS Panel
{
  "active_time_sec":  18400,
  "idle_time_sec":    3200,
  "locked_time_sec":  1800,
  "top_apps": [
    { "name": "Code",   "seconds": 12400, "category": "IDE" },
    { "name": "Chrome", "seconds": 4200,  "category": "Browser" },
    { "name": "Slack",  "seconds": 1800,  "category": "Communication" }
  ],
  "category_breakdown": [
    { "category": "IDE",           "seconds": 12400 },
    { "category": "Browser",       "seconds": 4200  },
    { "category": "Communication", "seconds": 1800  }
  ]
}

# IDE Panel
{
  "coding_time_sec":   10800,
  "idle_sec":          1200,
  "edits":             342,
  "saves":             48,
  "lines_added":       1240,
  "lines_deleted":     380,
  "terminal_commands": 28,
  "debug_runs":        4,
  "top_languages": [
    { "name": "python",     "seconds": 7200 },
    { "name": "typescript", "seconds": 3600 }
  ],
  "top_projects": [
    { "name": "smartdesk-backend", "seconds": 7200 },
    { "name": "smartdesk-ui",      "seconds": 3600 }
  ]
}

# Browser Panel
{
  "browser_active_time_sec": 4200,
  "productive_time_sec":     3100,
  "distracting_time_sec":    600,
  "neutral_time_sec":        500,
  "communication_time_sec":  0,
  "top_domains": [
    { "name": "github.com",         "seconds": 1800 },
    { "name": "stackoverflow.com",  "seconds": 900  },
    { "name": "docs.python.org",    "seconds": 400  }
  ]
}

# Timeline (for work period timeline visualization)
{
  "work_periods": [
    {
      "id": "uuid",
      "period_start": "2026-05-07T09:00:00+05:30",
      "period_end":   "2026-05-07T12:30:00+05:30",
      "duration_sec": 12600,
      "primary_source": "vscode",
      "has_os_data": true,
      "has_vscode_data": true,
      "has_browser_data": true,
      "has_calendar_data": false
    }
  ]
}
```

### Dashboard Query Logic

```python
# app/services/dashboard_service.py

class DashboardService:

    def get_os_summary(self, user_id, from_dt, to_dt):
        rows = self.os_repo.get_completed_sessions(user_id, from_dt, to_dt)
        # Only include active state rows for active_time, exclude idle/locked
        active = [r for r in rows if r.state == "active"]
        idle   = [r for r in rows if r.state == "idle"]
        locked = [r for r in rows if r.state == "locked"]

        return OSDashboardResponse(
            active_time_sec  = sum(r.duration_sec or 0 for r in active),
            idle_time_sec    = sum(r.duration_sec or 0 for r in idle),
            locked_time_sec  = sum(r.duration_sec or 0 for r in locked),
            top_apps         = self._top_apps(active),
            category_breakdown = self._category_breakdown(active),
        )

    def get_ide_summary(self, user_id, from_dt, to_dt):
        # Only foreground sessions for dashboard display
        rows = self.vscode_repo.get_foreground_sessions(user_id, from_dt, to_dt)
        return IDEDashboardResponse(
            coding_time_sec   = sum((r.duration_sec or 0) - (r.idle_sec or 0) for r in rows),
            idle_sec          = sum(r.idle_sec or 0 for r in rows),
            edits             = sum(r.edit_count or 0 for r in rows),
            saves             = sum(r.save_count or 0 for r in rows),
            lines_added       = sum(r.lines_added or 0 for r in rows),
            lines_deleted     = sum(r.lines_deleted or 0 for r in rows),
            terminal_commands = sum(r.terminal_command_count or 0 for r in rows),
            debug_runs        = sum(r.debug_run_count or 0 for r in rows),
            top_languages     = self._top_by_field(rows, "active_language"),
            top_projects      = self._top_by_field(rows, "workspace_name"),
        )

    def get_browser_summary(self, user_id, from_dt, to_dt):
        # Only foreground sessions, minimum 3 seconds for duration totals.
        # Switch counts are aggregated separately, including sub-3-second tabs.
        rows = self.browser_repo.get_foreground_sessions(
            user_id, from_dt, to_dt, min_duration_sec=3
        )
        return BrowserDashboardResponse(
            browser_active_time_sec = sum(r.duration_sec or 0 for r in rows),
            productive_time_sec     = sum(r.duration_sec or 0 for r in rows if r.category == "Focused"),
            distracting_time_sec    = sum(r.duration_sec or 0 for r in rows if r.category == "Distracted"),
            neutral_time_sec        = sum(r.duration_sec or 0 for r in rows if r.category == "Neutral"),
            communication_time_sec  = sum(r.duration_sec or 0 for r in rows if r.category == "Communication"),
            top_domains             = self._top_by_field(rows, "domain"),
        )
```

---

## Part 9 — Edge Cases & Solutions

| Edge Case | What Happens | Solution |
|---|---|---|
| VS Code extension crashes mid-session | Session stays open, no counters sent | Safety timeout closes it only after it is clearly abandoned/broken, `closed_by="timeout"`, counters remain 0 |
| Backend is down when extension fires | POST fails | Offline buffer queues payload, retries on next event |
| User locks screen | OS sends "locked" event | Current session stays open and is marked with lock/idle state metadata |
| Two VS Code windows, same workspace | Both send events | Different `instance_id` per window = separate rows, PID match determines `is_foreground` |
| Browser tab open for less than 3 seconds | Session created then closed | Backend excludes it from duration totals, but preserves/increments switch telemetry for distraction detection |
| Session crosses midnight | Single session spans two days | Dashboard queries use `session_start >= from_dt` so it appears in the day it started; a future improvement can split at midnight |
| Extension sends event before OS monitor | OS signal arrives 50–100ms later | Session is created, `is_foreground` starts as 0, OS event arrives and updates it via `_update_foreground_flags` |
| Calendar event overlaps with coding session | Both exist independently | Dashboard can show "in meeting while coding" indicator by querying both tables for the same time window |
| User closes browser without tab switch | No "ended" event fires | Safety timeout closes the open browser session only if no later focus/switch or shutdown/suspend signal arrives |
| Service worker killed (browser extension) | In-memory state lost | All state written to `chrome.storage.local` on every event — no in-memory reliance |

---

## Part 10 — Implementation Order

```
PHASE A — Foundation (1–2 days, nothing breaks)
  ✅ 1. Add Alembic, delete raw SQL migration runner from main.py
  ✅ 2. Add app/core/config.py with pydantic-settings
  ✅ 3. Add app/core/logging.py, replace all print() calls
  ✅ 4. Split models/ into models/db/ and models/schemas/

PHASE B — New DB Schema (1 day)
  ✅ 5. Create os_sessions table migration
  ✅ 6. Create vscode_sessions table migration
  ✅ 7. Create browser_sessions table migration
  ✅ 8. Create work_periods table migration (replaces activity_session_summary)
  ✅ 9. Keep calendar_events, add duration_sec and status columns

PHASE C — Backend Services (2–3 days)
  ✅ 10. Build SessionCoordinator service
  ✅ 11. Build SessionTimeoutJob (background thread)
  ✅ 12. Build WorkPeriodScheduler (background thread)
  ✅ 13. Build 3 ingest routes (/ingest/os/event, /ingest/vscode/event, /ingest/browser/event)
  ✅ 14. Build DashboardService with aggregation logic
  ✅ 15. Build 3 dashboard routes + timeline route

PHASE D — VS Code Extension (1–2 days)
  ✅ 16. Add INSTANCE_ID + PROCESS_ID
  ✅ 17. Dynamic timezone + dynamic config from VS Code settings
  ✅ 18. Replace minute-window interval with event-driven session start/end
  ✅ 19. Fix edit_count, add lines_added/lines_deleted
  ✅ 20. Add offline buffer + retry
  ✅ 21. Update package.json with contributes.configuration

PHASE E — Browser Extension (1–2 days)
  ✅ 22. Persist all state to chrome.storage.local
  ✅ 23. Add options page for userId and backendUrl
  ✅ 24. Dynamic timezone
  ✅ 25. Replace 1-minute alarm with event-driven session start/end
  ✅ 26. Fix getBrowserName(), improve category classification
  ✅ 27. Add offline buffer + retry with 100-item cap
  ✅ 28. Update manifest.json

PHASE F — OS Monitor Update (1 day)
  ✅ 29. POST to /ingest/os/event on every foreground change
  ✅ 30. POST idle_start, idle_end, locked, unlocked events
  ✅ 31. Remove the old minute-window POST logic

PHASE G — Tests (ongoing)
  ✅ 32. Unit test SessionCoordinator (open, close, PID matching)
  ✅ 33. Unit test SessionTimeoutJob
  ✅ 34. Unit test DashboardService aggregation
  ✅ 35. Integration test all ingest endpoints
```

---

## Part 11 — Phase 2 Readiness

| Feature | How Current Design Supports It |
|---|---|
| AI coding pattern insights | `vscode_sessions` has `lines_added/deleted`, `edit_count`, `language`, `workspace` per session — exact input AI needs |
| AI distraction detection | `browser_sessions` has `category` + `duration_sec` per session — feed sequences into AI to detect patterns |
| AI daily report generation | `work_periods` gives logical work blocks. AI can summarize each block from raw session data |
| Cloud migration | All local tables are PostgreSQL-compatible if `String` timestamp columns are migrated to `DateTime(timezone=True)`. No architectural change needed |
| Team comparison dashboard | `user_id` column on every table. Add proper UUID auth on top, query remains the same |
| GitHub / Jira correlation | `repo_id` (hashed) + `git_branch` in `vscode_sessions` = direct join key to GitHub API events |
| Notification / distraction alerts | `browser_sessions` with `category="Distracted"` + `duration_sec` in real-time — add WebSocket push from backend |
| Export to CSV/PDF | `DashboardService` already aggregates — add a serializer layer on top |

---

*End of Plan — 11 parts · 5 tables · 3 extensions updated · Complete session lifecycle · Phase 2 ready*
