# SmartDesk — Developer Productivity Tracker

SmartDesk collects developer activity from four sources and stores everything locally in `backend/smartdesk.db`. A centralized dashboard and API layer lets you query your productivity data across OS, browser, IDE, and calendar.

**Sources:** OS activity · Browser tabs · IDE (VS Code, Antigravity, JetBrains, etc.) · Google Calendar

**Dashboard:** http://127.0.0.1:8000/dashboard/

---

## Quick Start

### 1. Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

> Run Uvicorn from the `backend/` folder — not the repo root.

When it starts you should see:

```
Initializing local SQLite database...
Starting OS Collector background service...
Starting Calendar Collector background service...
Starting Activity Session Scheduler...
```

### 2. Browser Extension

Folder: `browser extension/`

Tracks active tabs, classifies pages as **Focused / Distracted / Neutral**, and sends 1-minute window summaries to the backend. Detects when the browser is in the background and correctly excludes that time from active seconds.

**Chrome / Edge:**

1. Open `chrome://extensions` or `edge://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `browser extension/` folder

**Firefox:**

1. Open `about:debugging` → **This Firefox**
2. Click **Load Temporary Add-on...**
3. Select `browser extension/manifest.json`

**Configuration:**

After installing, right-click the extension icon → **Options** to set your **User ID** and **Backend URL**.

### 3. IDE Extension (VS Code)

Folder: `smartdesk-ide-logger/`

Tracks edits, saves, file switches, debug runs, terminal usage, and lines added/deleted (captures all changes including Copilot completions). Sends one payload per 1-minute window. The backend accepts data from any IDE — the `source` field identifies which IDE sent it.

```powershell
cd smartdesk-ide-logger
npm install
npx @vscode/vsce package
```

Then in VS Code: **Extensions → ⋯ → Install from VSIX...** → select the `.vsix` file.

**Configuration:**

Open VS Code settings and search for `smartdesk` to configure:

| Setting | Default | Description |
|---|---|---|
| `smartdesk.userId` | *(machine hostname)* | Your SmartDesk user ID |
| `smartdesk.backendUrl` | `http://localhost:8000` | Backend server URL |

### 4. Google Calendar (Optional)

The Calendar collector syncs your upcoming events automatically every 15 minutes.

#### Step 1: Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the **Google Calendar API**
4. Configure **OAuth consent screen**
5. Create an **OAuth 2.0 Client ID** (type: **Desktop App**)
6. Download the client JSON file

Guides:

- [Calendar quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
- [Create credentials](https://developers.google.com/workspace/guides/create-credentials)

#### Step 2: Add Credentials

**Option A: Environment file (recommended)**

1. Copy `backend/.env.example` to `backend/.env`
2. Fill in your `client_id`, `client_secret`, and `project_id` from the downloaded JSON

**Option B: JSON file**

1. Rename the downloaded file to `google_calendar_client.json`
2. Place it at `backend/app/config/google_calendar_client.json`

#### Step 3: Connect

1. Restart the backend
2. Open the dashboard → Calendar section → click **Connect**
3. Sign in to Google and approve Calendar read-only access

After success the token is saved to `%APPDATA%\smartdesk-calendar\token.json` and sync runs automatically.

---

## Configuration

All backend settings are managed via environment variables in `backend/.env`. See `backend/.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartdesk.db` | Database connection string |
| `DEFAULT_USER_ID` | `local_user` | Default user ID for background collectors |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CALENDAR_SYNC_INTERVAL_SEC` | `900` | Calendar sync interval (seconds) |
| `SESSION_SCHEDULER_INTERVAL_SEC` | `60` | Timeline index rebuild interval (seconds) |
| `SMARTDESK_GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `SMARTDESK_GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `SMARTDESK_GOOGLE_PROJECT_ID` | — | Google Cloud project ID |

---

## Architecture

```
IDE Extension ──POST──→ /ide/minute-window   ──→ ide_minute_windows
Browser Ext   ──POST──→ /browser/minute-window ──→ browser_minute_windows
OS Collector  ──────────── (background thread)  ──→ os_minute_windows
Calendar Sync ──────────── (background thread)  ──→ calendar_events
                                                        │
                     ┌──────────────────────────────────┘
                     ▼
Timeline Index   derives from OS windows, enriched
Builder      ──→ with browser/ide flags ──→ activity_timeline_index
                                                        │
Dashboard API   reads all 5 tables ◄────────────────────┘
```

### Backend Structure

```
backend/app/
├── core/
│   ├── config.py              # Centralized Pydantic Settings
│   ├── database.py            # SQLAlchemy engine + session factory
│   ├── logging.py             # Structured logging setup
│   ├── google_calendar_client.py
│   └── session_watcher.py     # Windows lock/unlock detection
├── models/
│   ├── db_models.py           # SQLAlchemy ORM models (all tables)
│   ├── os_minute_window.py    # Pydantic schemas (OS)
│   ├── browser_minute_window.py
│   ├── ide_minute_window.py
│   ├── calendar_event.py
│   ├── activity_session_summary.py
│   └── dashboard.py           # Dashboard response schemas
├── repositories/              # Data access layer
│   ├── os_minute_window_repository.py
│   ├── browser_minute_window_repository.py
│   ├── ide_minute_window_repository.py
│   ├── calendar_event_repository.py
│   └── activity_session_summary_repository.py
├── services/                  # Business logic layer
│   ├── os_monitoring_service.py
│   ├── os_minute_window_service.py
│   ├── browser_minute_window_service.py
│   ├── ide_minute_window_service.py
│   ├── calendar_service.py
│   ├── calendar_event_service.py
│   ├── calendar_sync_service.py
│   ├── activity_session_summary_service.py
│   ├── activity_session_summary_scheduler.py
│   └── dashboard_service.py   # Dashboard aggregation logic
├── routes/                    # Thin API controllers
│   ├── health.py
│   ├── os_minute_window.py
│   ├── browser.py
│   ├── ide.py
│   ├── calendar.py
│   ├── activity_session_summary.py
│   └── dashboard.py
└── main.py                    # FastAPI app entry point
```

---

## Database Tables

| Table | Purpose | Writer |
|---|---|---|
| `os_minute_windows` | 1-min OS activity windows | OS Collector (background thread) |
| `browser_minute_windows` | 1-min browser activity windows | Browser Extension (POST) |
| `ide_minute_windows` | 1-min IDE activity windows | IDE Extension (POST) |
| `calendar_events` | Google Calendar events | Calendar Sync (background thread) |
| `activity_timeline_index` | Lean session timeline — foreground activity index | Timeline Scheduler (background thread) |

All tables use **upsert** logic — duplicate windows are updated, not duplicated. The `source` field in `ide_minute_windows` identifies which IDE sent the data (e.g. `vscode_extension`, `antigravity_extension`).

Every raw table includes:
- `extra_data` — JSON blob for future extensibility
- `timeline_index_id` — links to the corresponding timeline entry (OS, browser, vscode)

---

## Data Collection Frequency

| Source | Interval |
|---|---|
| OS collector | Every 60 seconds |
| Browser extension | Every 1 minute |
| IDE extension | Every 1 minute |
| Calendar sync | Every 15 minutes |
| Activity timeline index | Builds latest 30-minute window every 60 seconds |

---

## Activity Timeline Index

`activity_timeline_index` is the canonical foreground activity timeline. It replaces the old `activity_session_summary` table with a lean index.

Each row represents one minute window and records:
- **What was in the foreground** (app name, source, category)
- **Which data sources have data** for that minute (`has_os_data`, `has_ide_data`, `has_browser_data`)
- **Context links** (which IDE workspace, which browser domain)

For detailed drill-downs, the dashboard API queries the source tables directly for the same `user_id` and time range:

- `os_minute_windows`
- `browser_minute_windows`
- `ide_minute_windows`
- `calendar_events`

---

## Timezone

All timestamps use the **system's local timezone** dynamically:

```
2026-05-02T22:10:00+05:30
```

- `window_start` and `window_end` include the UTC offset
- `timezone` field stores the IANA timezone name (e.g. `Asia/Colombo`, `America/New_York`)
- All three collectors (OS, browser, VS Code) detect timezone automatically

---

## API Endpoints

### Ingest Endpoints

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/v1/ide/minute-window` | IDE minute window data |
| POST | `/api/v1/browser/minute-window` | Browser minute window data |

### Calendar Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/v1/calendar/status` | Calendar connection status |
| GET | `/api/v1/calendar/events` | List calendar events |
| POST | `/api/v1/calendar/connect` | Connect Google Calendar (OAuth) |
| POST | `/api/v1/calendar/sync` | Manual calendar sync trigger |

### Dashboard API

| Method | URL | Purpose |
|---|---|---|
| GET | `/dashboard/` | Dashboard HTML page (debug UI) |
| GET | `/dashboard/stats` | Summary counts + 24h timeseries |
| GET | `/dashboard/os?user_id=...&from=...&to=...` | OS activity summary |
| GET | `/dashboard/ide?user_id=...&from=...&to=...` | IDE/coding summary |
| GET | `/dashboard/browser?user_id=...&from=...&to=...` | Browser activity summary |
| GET | `/dashboard/sessions?user_id=...&from=...&to=...` | Timeline session entries |

### Session Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/v1/activity-sessions` | List timeline index entries |
| POST | `/api/v1/activity-sessions/build` | Manual timeline index rebuild |

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'pydantic_settings'`

Install the missing dependency:

```powershell
python -m pip install pydantic-settings
```

### `ModuleNotFoundError: No module named 'app'`

You started Uvicorn from the wrong folder. Run from `backend/`:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

### `no such column: timeline_index_id` (or similar schema errors)

The database schema has changed. Delete the old database and restart:

```powershell
Remove-Item backend/smartdesk.db
python -m uvicorn app.main:app --reload
```

The new schema will be created automatically. Data from your extensions will start flowing in again.

### Dashboard says `Needs credentials`

Calendar OAuth config is missing. Either:
- Create `backend/.env` from `backend/.env.example`
- Or place `google_calendar_client.json` in `backend/app/config/`

### Dashboard says `Reconnect needed`

Delete `%APPDATA%\smartdesk-calendar\token.json` and click **Connect** again.

### No browser / VS Code data appears

1. Check that the backend is running on `http://127.0.0.1:8000`
2. Check that the extension is loaded/installed
3. For the browser extension: right-click → **Options** → verify the Backend URL is correct
4. For VS Code: open settings → search `smartdesk` → verify the Backend URL

---

## Supported IDEs

The backend accepts minute-window data from any IDE. The `source` field identifies the origin:

| IDE | Source Value |
|---|---|
| VS Code | `vscode_extension` |
| Antigravity | `antigravity_extension` |
| JetBrains (IntelliJ, PyCharm, etc.) | `jetbrains_extension` |
| Other | Any string identifying the IDE |

---

## Notes

- Calendar access is read-only
- All data stays local in SQLite
- Database file: `backend/smartdesk.db`
- All timestamps are server-side — extensions don't set `created_at` or `updated_at`
- Offline buffering: both extensions queue failed sends and retry on the next minute cycle
- Use [DB Browser for SQLite](https://sqlitebrowser.org/) for manual inspection

## GitHub Projects v2 integration

The backend integrates with the independent `github_data_collection` package.
Configure a GitHub App and its Projects v2 webhook using the variables in
`backend/.env.example`. SmartDesk stores only connection, installation, and
selected-project identifiers in `smartdesk.db`; short-lived installation tokens
are minted when needed and are not persisted.

API prefix: `/api/v1/integrations/github`

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Connection and selected-project status |
| GET | `/setup` | Open the minimal GitHub setup and active-task UI |
| GET | `/connect` | Create a CSRF-protected GitHub App installation URL |
| GET | `/callback` | Complete GitHub App installation association |
| GET | `/projects` | Discover accessible Projects v2 boards |
| PUT | `/project` | Select an accessible board |
| GET | `/status-options` | Discover the board's actual Status options |
| PUT | `/status-mapping` | Save logical mappings and establish the initial baseline |
| POST | `/initial-sync` | Manually reconcile the selected project |
| POST | `/webhook` | Receive HMAC-verified project events |
| GET | `/active-tasks` | List the current user's ACTIVE tasks with their initial prediction |
| DELETE | `/connection` | Disconnect the local SmartDesk user |

When a project item begins a new logical `ACTIVE` lifecycle, SmartDesk takes a
snapshot of its title, description, labels, repository, and start time and runs
the retained LightGBM quantile models in
`backend/model_artifacts/github_effort/`. The stored low, typical, and high
values are predicted elapsed hours from lifecycle start to completion. They are
an initial estimate: subsequent metadata changes do not overwrite it. A reopen
creates a new lifecycle and therefore a new estimate, while duplicate webhook
delivery and repeated initial synchronization remain idempotent.

The runtime preprocessing contract, feature order, fallback values, model
version, and retained-artifact checksums are recorded in
`backend/model_artifacts/github_effort/preprocessing_manifest.json`. Runtime
code does not import the offline `github_issue_dataset_builder`. A missing or
invalid artifact is recorded as a failed prediction without discarding the
ACTIVE lifecycle. Override the packaged artifact directory only when needed
with `SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR`.

SmartDesk currently has no login/authentication middleware, so the integration
uses `DEFAULT_USER_ID`, consistent with the other local collectors. Add a real
current-user dependency before exposing this API as a multi-user service.
