# Phase 4 Manual Test - Ingest Validation

Start the backend from `backend/`:

```powershell
python -m uvicorn app.main:app --reload
```

## OS Event

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
    "window_title": "projectA - Visual Studio Code",
    "process_id": 1234,
    "timestamp": "2026-05-07T10:23:45+05:30"
  }'
```

Expected status:

```json
{
  "status": "validated:focused",
  "session_id": null,
  "is_foreground": null,
  "accepted": true
}
```

## VS Code Event

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
    "timestamp": "2026-05-07T10:25:12+05:30",
    "counters": {
      "edit_count": 14,
      "save_count": 2,
      "lines_added": 38,
      "lines_deleted": 5,
      "file_switch_count": 3,
      "terminal_command_count": 0,
      "debug_run_count": 0,
      "idle_sec": 12
    }
  }'
```

Expected status:

```json
{
  "status": "validated:ended",
  "session_id": null,
  "is_foreground": false,
  "accepted": true
}
```

## Browser Event

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
    "trigger": "tab_switch",
    "domain": "github.com",
    "category": "Focused",
    "timestamp": "2026-05-07T10:26:00+05:30"
  }'
```

Expected status:

```json
{
  "status": "validated:started",
  "session_id": null,
  "is_foreground": false,
  "accepted": true
}
```

## Invalid Event Check

Send an invalid event name:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/ingest/os/event" `
  -ContentType "application/json" `
  -Body '{
    "user_id": "local_user",
    "event": "bad_event",
    "timestamp": "2026-05-07T10:23:45+05:30"
  }'
```

Expected result: FastAPI returns a `422` validation error.
