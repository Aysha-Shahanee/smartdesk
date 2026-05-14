# Phase 5 Manual Test - Session Lifecycle

Phase 5 turns ingest validation into real local database writes.

## Setup

From `backend/`:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Use a fresh test database if you do not want to touch your local runtime DB:

```powershell
$env:DATABASE_URL = "sqlite:///./phase5_lifecycle_test.db"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

## OS Open And Close

Send first OS focus event:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/os/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "focused",
    "app_name": "Code",
    "app_category": "IDE",
    "window_title": "projectA",
    "process_id": 1234,
    "timestamp": "2026-05-07T10:00:00+05:30"
  }'
```

Send second OS focus event:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/os/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "focused",
    "app_name": "Chrome",
    "app_category": "Browser",
    "window_title": "GitHub",
    "process_id": 5678,
    "timestamp": "2026-05-07T10:05:00+05:30"
  }'
```

Expected database result:

- first `os_sessions` row is closed
- first row has `duration_sec = 300`
- second `os_sessions` row remains open

## VS Code Open And Close

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/vscode/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "started",
    "instance_id": "window-1",
    "process_id": 1234,
    "trigger": "window_focus",
    "workspace_name": "projectA",
    "active_file_name": "main.py",
    "active_language": "python",
    "timestamp": "2026-05-07T10:01:00+05:30"
  }'
```

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/vscode/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "ended",
    "instance_id": "window-1",
    "process_id": 1234,
    "trigger": "deactivate",
    "timestamp": "2026-05-07T10:04:00+05:30",
    "counters": {
      "edit_count": 5,
      "save_count": 1,
      "lines_added": 10,
      "lines_deleted": 2,
      "file_switch_count": 1,
      "terminal_command_count": 0,
      "debug_run_count": 0,
      "idle_sec": 12
    }
  }'
```

Expected database result:

- one `vscode_sessions` row
- row has `duration_sec = 180`
- counters are stored on the closed row

## Browser Tab Switch

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/browser/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "started",
    "browser_name": "Chrome",
    "browser_window_id": 1,
    "tab_id": 42,
    "process_id": 5678,
    "trigger": "tab_switch",
    "domain": "github.com",
    "category": "Focused",
    "timestamp": "2026-05-07T10:06:00+05:30"
  }'
```

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/browser/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "started",
    "browser_name": "Chrome",
    "browser_window_id": 1,
    "tab_id": 43,
    "process_id": 5678,
    "trigger": "tab_switch",
    "domain": "docs.python.org",
    "category": "Focused",
    "timestamp": "2026-05-07T10:08:00+05:30"
  }'
```

Expected database result:

- first browser row closes with `duration_sec = 120`
- second browser row remains open
