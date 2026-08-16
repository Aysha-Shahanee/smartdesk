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

GitHub collector    ──►  github_data.db + github_initial_predictions
                         (Projects v2 webhooks; LightGBM effort model)
Emotion service     ──►  emotion_sessions / emotion_blocks
                         (webcam thread, opt-in, 15-minute blocks)
```

Sessions split at every focus boundary, so one row never mixes foreground and background time. If the backend restarts, extension heartbeats automatically re-open their sessions — no data is lost.

### Where data is stored

Everything the app reads lives in `backend/smartdesk.db` under alembic, with one
exception: the GitHub collector keeps task lifecycles in its own
`github_data_collection/storage/github_data.db`, managed by `create_all` rather
than migrations. `GitHubPredictionService.active_tasks()` joins the two in
Python. Worth knowing before adding a query that spans them.

Nothing is uploaded anywhere. `emotion-recognition/RAF-DB-improvement/storage/`
contains a Supabase sync prototype retained from earlier work — every file in it
is marked at the top and imported by nothing. Do not wire it up without a
consent gate equivalent to the one on `/api/v1/emotion/start`.

### Privacy

Webcam emotion detection is **opt-in and off by default**. The toggle in
Settings → Privacy Controls writes to `user_preferences`, and
`POST /api/v1/emotion/start` returns `403` until it is on — the check is in the
backend because that is where the capture thread runs. Turning it off also stops
a session already in progress.

## Setup

### One-command local development

From the repository root, run:

```powershell
.\start-smartdesk-dev.ps1
```

If Windows blocks local PowerShell scripts under the current execution policy,
use the process-scoped form (it does not change the machine policy):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-smartdesk-dev.ps1
```

The development-only launcher runs `alembic upgrade head`, starts the FastAPI
backend, starts the existing Electron/Vite `npm run dev` workflow, creates a
Cloudflare Quick Tunnel to port 8000, and updates only the current GitHub App
webhook URL. It then verifies the local backend, public tunnel, frontend, and
the webhook's unsigned-request `401` response. Runtime PIDs and logs are kept
under the gitignored `.smartdesk-dev/` directory. Secrets and App JWTs are never
printed or written there.

The launcher reads `SMARTDESK_GITHUB_APP_ID`,
`SMARTDESK_GITHUB_APP_PRIVATE_KEY`, and `SMARTDESK_GITHUB_WEBHOOK_SECRET` from
the process environment or existing `backend/.env`. It stops before startup if
they are unavailable. The GitHub update uses the App-authenticated webhook
configuration endpoint and PATCHes only `url`; it does not modify the webhook
secret, permissions, subscribed events, callback URL, setup URL, or other App
configuration.

To stop only process trees recorded by this launcher:

```powershell
.\stop-smartdesk-dev.ps1
```

Stopping a Quick Tunnel makes its URL unreachable. The GitHub App retains that
last development webhook URL until the next successful launcher run replaces
it; webhook deliveries are therefore expected to fail while the local stack is
stopped.

For local diagnostics without changing GitHub, use
`.\start-smartdesk-dev.ps1 -SkipGitHubWebhookUpdate`.

### 1. Backend

```powershell
cd backend
python -m venv venv                     # first time only
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m alembic upgrade head   # after every pull — applies new migrations
.\venv\Scripts\python.exe -m uvicorn app.main:app

That single command starts everything: the HTTP server on `http://127.0.0.1:8000`, the OS foreground monitor (1s polling), the session timeout job, the work period scheduler, and the calendar auto-sync job.

Then open the **monitoring dashboard**: <http://127.0.0.1:8000/dashboard/ui> — it shows live health, totals, and recent rows for all four layers, with the calendar **Connect** / **Sync now** buttons. Auto-refreshes every 30s.
```

#### Installing only part of the backend

`requirements.txt` installs everything and is the right default. It is a thin
wrapper over three files, so you can skip the heavy optional pieces when you are
not working on them:

| File | Covers | Notable weight |
| --- | --- | --- |
| `requirements-core.txt` | Sessions, segments, focus, categorisation, recommendations, calendar | torch, via sentence-transformers |
| `requirements-prediction.txt` | GitHub task time prediction | lightgbm, pandas, the collector package |
| `requirements-emotion.txt` | Webcam emotion detection | torchvision, opencv, pillow |

```powershell
# app only, no ML integrations
.\venv\Scripts\python.exe -m pip install -r requirements-core.txt
```

The API starts with any subset installed. A feature whose dependencies are
missing reports that on its own endpoints rather than preventing startup.

`requirements-prediction.txt` contains a relative editable install
(`-e ../github_data_collection`), so run pip with `backend/` as the working
directory in every case.

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

## Development Phase: Sharing Corrections via Google Sheets (Optional)

During development, team members can share their activity-segment corrections (labels) via a shared Google Sheet to collaboratively improve the supervised learning model. This feature is **only for development** and can be completely removed after development by deleting a few lines of code and unsetting an environment variable.

### How It Works

1. When a user submits a correction via the `/activity-segments/{segment_id}/label` endpoint:
   - The correction is saved to the local SQLite database (triggers personal auto-training after 10 labels)
   - If `ENABLE_GSHEET_SYNC=true` is set, the same correction is appended to a shared Google Sheet
2. The Google Sheet collects corrections from all team members in real-time
3. Periodically, download the sheet as CSV and train a final supervised model (using your existing training logic)
4. Bake the final model into the application

### Setup Instructions

#### 👤 One-Time Setup (Done Once by Anyone)
Only needs to be done once for the entire team:

1. **Create and share the Google Sheet**:
   - Go to https://sheets.google.com → Blank spreadsheet
   - Name it (e.g., "SmartDesk Dev Corrections")
   - Share with all team members (give **Editor** access)
   - Create a worksheet tab named exactly `Labels` (case-sensitive)
   - In the first row, add these headers:
     ```
     timestamp,segment_id,user_id,label,embedding_json,device_id,app_name,title,detail
     ```
   - Copy the **Sheet ID** from the URL:
     ```
     https://docs.google.com/spreadsheets/d/1G_oudT83kv-JSugqzbVE-nbLyjmQ0c7YY5EGpbLUaG8/edit
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ THIS IS THE SHEET ID
     ```

2. **Configure the Sheet ID in code** (commit this change):
   - Edit `backend/app/services/categorizer.py`
   - Replace:
     ```python
     sh = gc.open_by_key("YOUR_SHEET_ID_HERE")
     ```
   - With your actual Sheet ID (keep the quotes):
     ```python
     sh = gc.open_by_key("1G_oudT83kv-JSugqzbVE-nbLyjmQ0c7YY5EGpbLUaG8")
     ```
   - Commit this change to the repository so all team members get it

#### 👥 Per-Team-Member Setup (Each Person Does This)

##### 1. One-Time Google Authentication (Per Machine)
```powershell
# Install/update dependencies
pip install -r backend/requirements.txt

# Run this ONCE to authenticate with Google (opens browser for login)
python -c "import gspread; gc = gspread.oauth()"
```
This saves OAuth tokens locally:
- Windows: `%APPDATA%\gspread\`
- macOS/Linux: `~/.config/gspread/`

**Important:** These token files are automatically ignored by Git (see `.gitignore`) - **no secrets are committed**.

##### 2. Enable Sync During Development (Per Session)
When running the backend, set the environment variable:
```powershell
# PowerShell
$env:ENABLE_GSHEET_SYNC = "true"
python -m uvicorn app.main:app

# bash/zsh
export ENABLE_GSHEET_SYNC=true
python -m uvicorn app.main:app
```

To disable later (for production or after development):
```powershell
# PowerShell
$env:ENABLE_GSHEET_SYNC = "false"
# or simply remove the variable: Remove-Item Env:ENABLE_GSHEET_SYNC

# bash/zsh
export ENABLE_GSHEET_SYNC=false
# or: unset ENABLE_GSHEET_SYNC
```

### 🔄 Development Workflow
- Team members submit corrections via the API (as usual)
- Corrections appear in **both**:
  - Local SQLite database (triggers personal auto-training at 10 labels)
  - **Shared Google Sheet** (visible to entire team in real-time)
- Periodically (e.g., after 20-50 new corrections):
  1. Open the Google Sheet → File → Download → Comma-separated values (.csv)
  2. Train your final supervised model using that CSV (with your existing training logic)
  3. Bake the model into the application
- After development completes:
  1. Set `$env:ENABLE_GSHEET_SYNC = "false"` or remove the variable
  2. Delete the Google Sheets sync block from `categorizer.py` (≈10 lines)
  3. Commit: "Remove dev-only Google Sheet correction sync"
  4. System runs 100% locally with the final baked-in model

### ⚠️ Important Notes
- **Zero risk to core functionality**: If Google Sheets is unavailable, corrections still save locally with only a non-critical error printed.
- **No secrets committed**: OAuth tokens stay on each developer's machine (automatically ignored by Git).
- **Easy cleanup**: Controlled by a single environment variable + isolated code block (~10 lines).
- **Real-time collaboration**: During development, everyone sees each other's corrections in the Sheet as they happen.
- **Worksheet name must be exactly** `Labels` (case-sensitive) - not "label", "LABELS", or any other variation.

## API Reference

### Ingest

```text
POST /api/v1/ingest/os/event        OS collector events
POST /api/v1/ingest/ide.event       IDE extension events
POST /api/v1/ingest/browser.event   browser extension events
POST /api/v1/ingest/vscode.event    deprecated alias of /ide/event (old builds)
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
GET /dashboard/os          active/idle time, top apps, categories
GET /dashboard/ide         coding time, edits, lines, top languages/projects
GET /dashboard/browser     time by category, top domains
GET /dashboard/timeline    work periods with source flags
GET /dashboard/sessions    flat chronological session list
GET /dashboard/overview    per-layer health, totals, recent rows (feeds the UI)
GET /dashboard/ui          monitoring dashboard page
```

### Emotion detection

```text
GET    /api/v1/emotion/consent           is webcam capture allowed
PUT    /api/v1/emotion/consent           grant or revoke; revoking stops a running session
POST   /api/v1/emotion/start             403 until consent is granted
POST   /api/v1/emotion/stop              bounded wait; ok:false if the thread is stuck
GET    /api/v1/emotion/status            running, model/camera readiness, last error
GET    /api/v1/emotion/sessions/current  session, completed blocks, in-progress block
```

Block scores are per-emotion **mean** probabilities with `processed_frame_count`
alongside, so blocks of different lengths are directly comparable.

### GitHub task prediction

```text
GET    /api/v1/integrations/github/status          connection state
GET    /api/v1/integrations/github/connect         begin App installation
GET    /api/v1/integrations/github/projects        Projects v2 available to the install
PUT    /api/v1/integrations/github/project         choose the project to track
GET    /api/v1/integrations/github/status-options  the project's Status column values
PUT    /api/v1/integrations/github/status-mapping  map them to ACTIVE / DONE / OTHER
POST   /api/v1/integrations/github/initial-sync    import currently-active issues
GET    /api/v1/integrations/github/active-tasks    estimates, time spent, remaining
POST   /api/v1/integrations/github/webhook         GitHub delivery endpoint (HMAC verified)
DELETE /api/v1/integrations/github/connection      disconnect
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
| `activity_segments` | Canonical non-overlapping timeline built from the three session tables |
| `emotion_sessions`, `emotion_blocks` | Webcam emotion detection: one row per session, one per 15-minute block |
| `github_connections`, `github_initial_predictions` | GitHub App connection and per-task effort estimates |
| `user_preferences` | Settings toggles the backend must enforce, such as webcam consent |

Recreate from scratch:

```powershell
# Stop the backend AND close smartdesk.db in DB Browser first, then:
Remove-Item backend\smartdesk.db -Force
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head
```

### Writing a migration

Generate the revision rather than hand-numbering it:

```powershell
.\venv\Scripts\python.exe -m alembic revision -m "what it does"
```

The `NNNN_` prefixes on the older files are historical and no longer sequential —
two branches each added an `0011` and an `0013`, which is exactly the collision
alembic's generated hashes avoid. The revision id inside the file is what
matters; the filename is only a label. If a merge leaves two heads, join them
with `alembic merge -m "..." <head> <head>` instead of editing `down_revision`
by hand, and check with `alembic heads` before you commit.

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
| `ENABLE_GSHEET_SYNC` | `false` | Set to `true` to enable Google Sheets sync for corrections (dev only) |
| `SMARTDESK_POLL_INTERVAL` | `1.0` | OS collector poll interval (seconds) |
| `SMARTDESK_IDLE_THRESHOLD` | `120` | Seconds of no input before idle_start |

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
