# SmartDesk

SmartDesk is a personal productivity tracker built on a **session-based architecture** described in [`plan.md`](plan.md). It monitors OS foreground activity, IDE usage, browser activity, and calendar events — grouping them into logical work periods for dashboard reporting.

## Architecture Overview

```
OS Collector (background thread)
    │  POST /api/v1/ingest/os/event
    ▼
SessionCoordinator  ──►  os_sessions table
                    ──►  vscode_sessions table  (via IDE extension)
                    ──►  browser_sessions table (via browser extension)
                    ──►  foreground matching (is_foreground flag)

SessionTimeoutJob   ──►  closes stale open sessions (every 60s)
WorkPeriodScheduler ──►  groups sessions into work_periods (every 60s)

Dashboard API       ──►  aggregates all tables for the 5 dashboard panels
```

## Current State

### ✅ Fully Working

| Component | File | Status |
|---|---|---|
| FastAPI backend | `backend/app/main.py` | Running |
| OS foreground collector | `backend/app/services/os_collector.py` | Auto-starts with backend |
| Session coordinator | `backend/app/services/session_coordinator.py` | Active |
| Session timeout job | `backend/app/services/session_timeout_job.py` | Auto-starts (60s interval) |
| Work period scheduler | `backend/app/services/work_period_scheduler.py` | Auto-starts (60s interval) |
| Dashboard API — OS panel | `GET /dashboard/os` | Live |
| Dashboard API — IDE panel | `GET /dashboard/ide` | Live |
| Dashboard API — Browser panel | `GET /dashboard/browser` | Live |
| Dashboard API — Timeline panel | `GET /dashboard/timeline` | Live |
| Dashboard API — Sessions panel | `GET /dashboard/sessions` | Live |
| Ingest — OS events | `POST /api/v1/ingest/os/event` | Live |
| Ingest — IDE events | `POST /api/v1/ingest/vscode/event` | Live |
| Ingest — Browser events | `POST /api/v1/ingest/browser/event` | Live |
| Legacy shim (old extension compat) | `backend/app/routes/legacy.py` | Returns 410 Gone |

### ⏳ Still Needed

- VS Code extension rewrite (session-based events)
- Browser extension rewrite (session-based events)
- Test suite (`pytest`)

## Quick Start

```powershell
cd backend
python -m pip install -r requirements.txt
python -m alembic upgrade head   # first run only — creates smartdesk.db
python -m uvicorn app.main:app --reload
```

That single command starts **everything**:
- FastAPI HTTP server on `http://127.0.0.1:8000`
- OS foreground monitor (background thread, polls every 1s)
- Session timeout job (background thread, runs every 60s)
- Work period scheduler (background thread, runs every 60s)

## Create VS Code Extension VSIX

Build a local `.vsix` installer from the VS Code extension folder:

```powershell
cd vscode-extension
npm install -g @vscode/vsce   # one time only
vsce package --no-dependencies
```

The command creates a file like `smartdesk-vscode-2.0.0.vsix` in `vscode-extension/`.

Install it into VS Code:

```powershell
code --install-extension .\smartdesk-vscode-2.0.0.vsix
```

After editing the extension, rerun `vsce package --no-dependencies` and reinstall the new `.vsix`.

## Verify It's Working

```text
http://127.0.0.1:8000/               → service status + active background jobs
http://127.0.0.1:8000/health/        → {"status": "ok"}
http://127.0.0.1:8000/docs           → Swagger UI — all endpoints
http://127.0.0.1:8000/api/v1/ingest/status
http://127.0.0.1:8000/dashboard/status
http://127.0.0.1:8000/dashboard/os
http://127.0.0.1:8000/dashboard/timeline
http://127.0.0.1:8000/dashboard/sessions
http://127.0.0.1:8000/api/v1/calendar/auth/status
http://127.0.0.1:8000/api/v1/calendar/auth/start
```

Expected root response:

```json
{
  "service": "SmartDesk Session Backend",
  "status": "running",
  "architecture": "session-based",
  "background_jobs": ["session_timeout_job", "work_period_scheduler", "os_collector"]
}

## Google Calendar Authorization and Reconnection

- Access tokens refresh automatically when the saved refresh token is valid.
- If the refresh token is expired or revoked, you must reconnect Google Calendar.
- Check status with `GET /api/v1/calendar/auth/status`.
- Use `GET /api/v1/calendar/auth/start` to reconnect and complete OAuth.
- Use `POST /api/v1/calendar/sync` to manually sync events when connected.
- If your OAuth app is in Google Testing mode, refresh tokens may expire and require reconnection.
  For long-term usage, publish the OAuth consent app to Production and keep credentials unchanged.
```

## Database

Single file: `backend/smartdesk.db`

| Table | Purpose |
|---|---|
| `os_sessions` | One row per foreground window focus period |
| `vscode_sessions` | One row per IDE file/workspace session |
| `browser_sessions` | One row per browser tab session (≥3s) |
| `calendar_events` | Google Calendar events |
| `work_periods` | 30-minute activity blocks (auto-grouped) |

### VS Code Session Details

In `vscode_sessions`, we track both foreground context and session aggregates:
- **Foreground Context**: `active_file_path`, `active_file_name`, and `active_language` represent the **foreground active file** context only (updated as the active window/editor tab switches).
- **Edit Aggregates**: Per-file edit details are captured in `edited_files_json` (a JSON array of actual edited files along with their edit counts, save counts, and line metrics).
- **Session Metrics**: Overall session metrics are aggregated in `total_edit_count`, `total_save_count`, `total_lines_added`, `total_lines_deleted`, and `dominant_language` (computed dynamically from the files that were actually edited).

Recreate the database from scratch:

```powershell
# Stop the backend first, then:
Remove-Item backend/smartdesk.db -Force
cd backend
python -m alembic upgrade head
```

## Dashboard API

All endpoints accept optional query params:

| Param | Default | Example |
|---|---|---|
| `user_id` | `local_user` | `?user_id=local_user` |
| `from` | Start of today (UTC) | `?from=2026-05-12T00:00:00Z` |
| `to` | Now (UTC) | `?to=2026-05-12T23:59:59Z` |

## Environment Variables

Set in `backend/.env` or as environment variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartdesk.db` | SQLAlchemy DB URL |
| `LOG_LEVEL` | `INFO` | Logging level |
| `SMARTDESK_BACKEND_URL` | `http://127.0.0.1:8000` | URL the OS collector POSTs to |
| `SMARTDESK_USER_ID` | `local_user` | User ID stamped on all events |
| `SMARTDESK_POLL_INTERVAL` | `1.0` | OS collector poll interval (seconds) |
| `SMARTDESK_IDLE_THRESHOLD` | `120` | Seconds of no input before idle_start |

## Project Structure

```
backend/
├── app/
│   ├── core/           config, database, logging
│   ├── models/
│   │   ├── db/         SQLAlchemy ORM models (5 tables)
│   │   └── schemas/    Pydantic request/response schemas
│   ├── repositories/   per-source DB query helpers
│   ├── routes/         HTTP endpoints (ingest, dashboard, health, legacy)
│   └── services/       business logic (coordinator, scheduler, collector)
├── migrations/         Alembic migration scripts
└── requirements.txt

plan.md                 Full architecture specification
DEVELOPMENT_TODO.md     Phase-by-phase implementation checklist
```