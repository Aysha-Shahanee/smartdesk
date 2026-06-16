# SmartDesk

SmartDesk is a personal productivity tracker built on a **session-based architecture**. It monitors four data layers — OS foreground activity, IDE usage, browser activity, and Google Calendar — and groups them into logical work periods for dashboard reporting.

All timestamps across the system are stored and returned in **Sri Lankan time (Asia/Colombo)**, configurable via the `TIMEZONE` setting.

## Architecture

```
OS Collector (background thread)
    │  POST /api/v1/ingest/os/event
    ▼
SessionCoordinator  ──►  os_sessions table
                    ──►  ide_sessions table      (via IDE extension)
                    ──►  browser_sessions table  (via browser extension)
                    ──►  foreground matching (PID + parent PID + app category)

CalendarSyncJob     ──►  calendar_events table   (Google Calendar, every 15 min)
SessionTimeoutJob   ──►  closes stale open sessions (every 60s)
WorkPeriodScheduler ──►  groups sessions into work_periods (every 60s)

Dashboard API       ──►  aggregates all tables (5 panels + monitoring overview)
Dashboard UI        ──►  /dashboard/ui — live health check of all 4 layers
```

Sessions split at every focus boundary, so one row never mixes foreground and background time. If the backend restarts, extension heartbeats automatically re-open their sessions — no data is lost.

## Setup

### 1. Backend

```powershell
cd backend
python -m venv venv                     # first time only
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m alembic upgrade head   # first time only — creates smartdesk.db
.\venv\Scripts\python.exe -m uvicorn app.main:app
```

That single command starts everything: the HTTP server on `http://127.0.0.1:8000`, the OS foreground monitor (1s polling), the session timeout job, the work period scheduler, and the calendar auto-sync job.

Then open the **monitoring dashboard**: <http://127.0.0.1:8000/dashboard/ui> — it shows live health, totals, and recent rows for all four layers, with the calendar **Connect** / **Sync now** buttons. Auto-refreshes every 30s.

### 2. IDE extension (VS Code, Antigravity, Cursor, …)

Build and install (see [vscode-extension/README.md](vscode-extension/README.md) for details):

```powershell
cd vscode-extension
npx --yes @vscode/vsce package --allow-missing-repository
code --install-extension .\smartdesk-ide-3.1.0.vsix     # VS Code
```

For **Antigravity** and other VS Code-based IDEs: Extensions panel (`Ctrl+Shift+X`) → `···` → **Install from VSIX…** → pick the file → restart the IDE.

Collection rules: focused IDE → collected normally; blurred IDE with AI still editing → collected with `is_foreground=0` (`background_ai`); blurred and idle 60s → session ends, nothing collected.

### 3. Browser extension (Chromium: Chrome, Comet, Brave, Edge, Arc)

1. Open `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select the [browser-extension/](browser-extension/) folder
3. Click the SmartDesk toolbar icon → confirm backend URL `http://127.0.0.1:8000` and Enabled ✔

Only the focused window's active tab is tracked; sessions under 3 seconds are dropped.

### 4. Google Calendar

**Connect (one click):** on the dashboard, click **Connect Google Calendar** → approve in the Google tab → first sync runs automatically. After that it auto-syncs every 15 minutes; **Sync now** forces one.

**Credentials (developers):** OAuth client of type *Desktop App*, supplied either way — env vars win:

| Option | How |
|---|---|
| A — env vars | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` in `backend/.env` |
| B — file | Save the downloaded JSON as `backend/calendar_store/credentials.json` |

Tokens and sync state live in `backend/calendar_store/` (gitignored — never commit it).

**Sync semantics:** events are upserted by `(user_id, event_id)` — re-syncs update existing rows only when Google's `updated` stamp changed and **never create duplicates**. Events deleted in Google are kept with `status="cancelled"`. Incremental syncs use Google's sync token. Access tokens auto-refresh.

**⚠ Token lifetime:** while your Google OAuth app is in *Testing* publishing status, Google expires the refresh token after **7 days**. For a permanent connection: Google Cloud Console → APIs & Services → **OAuth consent screen** → **Publish app**, then reconnect once. If a token ever dies, SmartDesk auto-disconnects and the dashboard shows it — just click Connect again.

## API Reference

### Ingest

```text
POST /api/v1/ingest/os/event        OS collector events
POST /api/v1/ingest/ide/event       IDE extension events
POST /api/v1/ingest/browser/event   browser extension events
POST /api/v1/ingest/vscode/event    deprecated alias of /ide/event (old builds)
```

### Calendar

```text
GET  /api/v1/calendar/status          connected? last sync? event count
GET  /api/v1/calendar/connect         redirects to Google consent (one-click)
GET  /api/v1/calendar/oauth/callback  OAuth landing (used by Google)
POST /api/v1/calendar/sync            manual sync
POST /api/v1/calendar/disconnect      remove the stored token
GET  /api/v1/calendar/events          events ordered by start time
```

### Dashboard

All endpoints accept optional `user_id`, `from`, `to` (ISO 8601, default = today in Asia/Colombo):

```text
GET /dashboard/os          active/idle/locked time, top apps, categories
GET /dashboard/ide         coding time, edits, lines, top languages/projects
GET /dashboard/browser     time by category, top domains
GET /dashboard/timeline    work periods with source flags
GET /dashboard/sessions    flat chronological session list
GET /dashboard/overview    per-layer health, totals, recent rows (feeds the UI)
GET /dashboard/ui          monitoring dashboard page
```

Also: `GET /` (service status), `GET /health/`, `GET /docs` (Swagger UI).

## Database

Single file: `backend/smartdesk.db` (SQLite).

Every row carries `device_id` (which machine collected it — auto-detected hostname) and `schema_version`, so data from multiple devices can be merged and used for training/aggregation without ambiguity.

| Table | Purpose |
|---|---|
| `os_sessions` | One row per foreground window focus period |
| `ide_sessions` | One row per IDE focus/background segment (per-file edits, languages, AI background edits) |
| `browser_sessions` | One row per browser tab session (≥3s, focused window only) |
| `calendar_events` | Google Calendar events (upserted, never duplicated) |
| `work_periods` | 30-minute activity blocks (auto-grouped) |

Recreate from scratch:

```powershell
# Stop the backend AND close smartdesk.db in DB Browser first, then:
Remove-Item backend\smartdesk.db -Force
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head
```

## Environment Variables

Set in `backend/.env` (see `backend/.env.example`):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartdesk.db` | SQLAlchemy DB URL |
| `TIMEZONE` | `Asia/Colombo` | Timezone for all stored timestamps |
| `DEVICE_ID` | _(hostname)_ | Identifies which device collected each row; auto-detected when empty |
| `LOG_LEVEL` | `INFO` | Logging level |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | _(empty)_ | Calendar OAuth client (option A) |
| `GOOGLE_CREDENTIALS_FILE` | `./calendar_store/credentials.json` | Calendar OAuth client (option B) |
| `CALENDAR_STORE_DIR` | `./calendar_store` | Where tokens & sync state live |
| `CALENDAR_SYNC_INTERVAL_MIN` | `15` | Auto-sync interval |
| `CALENDAR_SYNC_PAST_DAYS` / `CALENDAR_SYNC_FUTURE_DAYS` | `30` / `60` | First-sync window |
| `BACKEND_BASE_URL` | `http://127.0.0.1:8000` | Used to build the OAuth redirect URI |
| `SMARTDESK_POLL_INTERVAL` | `1.0` | OS collector poll interval (seconds) |
| `SMARTDESK_IDLE_THRESHOLD` | `120` | Seconds of no input before idle_start |

## Troubleshooting

- **Port 8000 already in use** (`WinError 10013/10048`): another backend instance is running — `netstat -ano | findstr :8000`, then stop that PID.
- **Can't delete smartdesk.db**: DB Browser for SQLite has it open — close the database there first. DB Browser also doesn't auto-refresh; press F5 to see new rows.
- **Calendar shows "Access blocked"**: your Gmail must be in the OAuth consent screen's Test users (or publish the app), and the Google Calendar API must be enabled.
- **Calendar stopped syncing after ~a week**: Testing-status refresh token expired — publish the app (see Setup §4) and reconnect.
- **IDE rows missing `ide_name`**: an IDE window is still running an old extension build — restart all IDE windows after installing the vsix.
- **Rejected payloads**: logged with full body at `WARNING` level in the backend console.

## Project Structure

```
backend/
├── app/
│   ├── core/           config, database, logging, time (Asia/Colombo)
│   ├── models/
│   │   ├── db/         SQLAlchemy ORM models (5 tables)
│   │   └── schemas/    Pydantic request/response schemas
│   ├── repositories/   per-source DB query helpers
│   ├── routes/         HTTP endpoints (ingest, calendar, dashboard, health)
│   ├── services/       coordinator, calendar sync, schedulers, OS collector
│   └── static/         dashboard.html (monitoring UI)
├── calendar_store/     Google OAuth credentials/tokens/sync state (gitignored)
├── migrations/         Alembic migration scripts
└── requirements.txt

vscode-extension/       IDE extension (VS Code, Antigravity, Cursor, ...)
browser-extension/      Chromium extension (Manifest V3)
```

i am testing how is the ide working.

hey, hello! world.

