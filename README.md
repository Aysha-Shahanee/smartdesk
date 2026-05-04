# SmartDesk Data Collection Layer

SmartDesk collects developer activity from four sources and stores everything locally in `backend/smartdesk.db`.

**Sources:** OS activity · Browser tabs · VS Code IDE · Google Calendar

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

- `Initializing local SQLite database...`
- `Starting OS Collector background service...`
- `Starting Calendar Collector background service...`

### 2. Browser Extension

Folder: `browser extension/`

Tracks active tabs, classifies pages as **Focused / Distracted / Neutral**, and sends 1-minute window summaries to the backend.

**Chrome / Edge:**

1. Open `chrome://extensions` or `edge://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `browser extension/` folder

**Firefox:**

1. Open `about:debugging` → **This Firefox**
2. Click **Load Temporary Add-on...**
3. Select `browser extension/manifest.json`

### 3. VS Code Extension

Folder: `smartdesk-ide-logger/`

Tracks edits, saves, file switches, debug runs, and terminal usage. Sends one payload per 1-minute window.

```powershell
cd smartdesk-ide-logger
npm install
npx @vscode/vsce package
```

Then in VS Code: **Extensions → ⋯ → Install from VSIX...** → select the `.vsix` file.

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

## Architecture

```
IDE Extension ──POST──→ /vscode/minute-window ──→ vscode_minute_windows
Browser Ext   ──POST──→ /browser/minute-window ──→ browser_minute_windows
OS Collector  ──────────── (background thread) ──→ os_minute_windows
Calendar Sync ──────────── (background thread) ──→ calendar_events
                                                       │
                     ┌─────────────────────────────────┘
                     ▼
Activity Sessions   derive from OS windows
Builder        ──→ aggregates into sessions ──→ activity_session_summary
                                                       │
Dashboard   reads all 5 tables ◄───────────────────────┘
```

---

## Database Tables

| Table | Purpose | Writer |
|---|---|---|
| `os_minute_windows` | 1-min OS activity windows | OS Collector (background thread) |
| `browser_minute_windows` | 1-min browser activity windows | Browser Extension (POST) |
| `vscode_minute_windows` | 1-min VS Code activity windows | IDE Extension (POST) |
| `calendar_events` | Google Calendar events | Calendar Sync (background thread) |
| `activity_session_summary` | Session-based dashboard summary | Activity Session Scheduler (background thread) |

All 5 tables use **upsert** logic — duplicate windows are updated, not duplicated.

---

## Data Collection Frequency

| Source | Interval |
|---|---|
| OS collector | Every 60 seconds |
| Browser extension | Every 1 minute |
| VS Code extension | Every 1 minute |
| Calendar sync | Every 15 minutes |
| Activity session summary | Builds latest 30-minute window every 60 seconds |

---

## Activity Session Summary Table

`activity_session_summary` is a session-based dashboard summary table. It stores the main timeline rows for the UI.

OS activity defines sessions. Browser, VS Code, and calendar data are attached by time overlap.

For detailed drill-downs, the backend or dashboard should query the source tables for the same `user_id` and time range:

- `os_minute_windows`
- `browser_minute_windows`
- `vscode_minute_windows`
- `calendar_events`


---

## Timezone

All timestamps use **Asia/Colombo** (UTC+5:30) ISO format:

```
2026-05-02T22:10:00+05:30
```

- `window_start` and `window_end` include the `+05:30` offset
- `timezone` field is always `"Asia/Colombo"`

---

## API Endpoints

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/v1/vscode/minute-window` | VS Code minute window data |
| POST | `/api/v1/browser/minute-window` | Browser minute window data |
| GET | `/api/v1/calendar/status` | Calendar connection status |
| GET | `/api/v1/calendar/events` | List calendar events |
| POST | `/api/v1/calendar/sync` | Manual calendar sync trigger |
| POST | `/api/v1/activity-sessions/build` | Manual session summary build |
| GET | `/api/v1/activity-sessions` | List activity sessions |
| GET | `/dashboard/` | Dashboard HTML page |

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'app'`

You started Uvicorn from the wrong folder. Run from `backend/`:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

### Dashboard says `Needs credentials`

Calendar OAuth config is missing. Either:
- Create `backend/.env` from `backend/.env.example`
- Or place `google_calendar_client.json` in `backend/app/config/`

### Dashboard says `Reconnect needed`

Delete `%APPDATA%\smartdesk-calendar\token.json` and click **Connect** again.

### No browser / VS Code data appears

Check that the backend is running and the extension is loaded/installed.

---

## Notes

- Calendar access is read-only
- All data stays local in SQLite
- Database file: `backend/smartdesk.db`
- Use [DB Browser for SQLite](https://sqlitebrowser.org/) for manual inspection