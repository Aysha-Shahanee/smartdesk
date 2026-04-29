# SmartDesk Data Collection Layer

SmartDesk collects developer activity and stores it locally in `backend/smartdesk.db`.

Sources:

- OS signals
- Browser activity
- VS Code activity
- Google Calendar events

Dashboard:

- http://127.0.0.1:8000/dashboard/

---

## 1. What To Run After Cloning

1. Set up Python and start the backend
2. Open the dashboard
3. Load the browser extension
4. Package and install the VS Code extension as `.vsix`
5. If needed, set up Google Calendar and click `Connect`

---

## 2. Backend Setup

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Important:

- run Uvicorn from the `backend` folder
- if you run it from the repo root, `app.main:app` will fail

When it starts, you should see:

- `Initializing local SQLite database...`
- `Starting OS Collector background service...`
- `Starting Calendar Collector background service...`

Open:

- API root: http://127.0.0.1:8000/
- Dashboard: http://127.0.0.1:8000/dashboard/

---

## 3. Browser Extension Setup

Folder:

- `browser extension/`

What it does:

- tracks active tabs and tab switches
- classifies pages as `Focused`, `Distracted`, or `Neutral`
- sends browser minute-window summaries to the backend every 1 minute

### Chrome / Edge

1. Make sure the backend is running
2. Open:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
3. Turn on `Developer mode`
4. Click `Load unpacked`
5. Select the `browser extension` folder

### Firefox

1. Make sure the backend is running
2. Open `about:debugging`
3. Click `This Firefox`
4. Click `Load Temporary Add-on...`
5. Select `browser extension/manifest.json`

---

## 4. VS Code Extension Setup Using VSIX

Folder:

- `smartdesk-ide-logger/`

What it does:

- tracks edits, saves, file switches, debug runs, and terminal usage
- sends one payload per 1-minute window

### Step 1: Install dependencies

From the project root:

```powershell
cd smartdesk-ide-logger
npm install
```

### Step 2: Package the extension as `.vsix`

Use:

```powershell
npx @vscode/vsce package
```

This should create a file similar to:

- `smartdesk-ide-logger-0.0.1.vsix`

### Step 3: Install the `.vsix` in VS Code

1. Open VS Code
2. Open the Extensions panel
3. Click the `...` menu in the Extensions panel
4. Click `Install from VSIX...`
5. Select the generated `.vsix` file from `smartdesk-ide-logger/`
6. Reload VS Code if prompted

After that, use VS Code normally and the extension should start sending data to:

- `POST /api/v1/vscode/minute-window`

---

## VS Code Minute-Window Tracking

The VS Code extension now sends one payload per 1-minute window.

Key points:

- Endpoint: `POST /api/v1/vscode/minute-window`
- SQLite table: `vscode_minute_windows`
- One row per user per 1-minute window
- Upsert key: `user_id + window_start + window_end`
- If the same window is sent again, the row is updated (no duplicates)
- `window_start` and `window_end` include the Asia/Colombo offset (+05:30)
- `timezone` is stored as Asia/Colombo

Verify VS Code minute windows:

1. Start the backend:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

2. Install the latest VS Code extension VSIX:
   - Open VS Code
   - Go to Extensions
   - Click the three dots menu
   - Select Install from VSIX
   - Choose the newly built smartdesk-ide-logger `.vsix` file
   - Restart VS Code

3. Open a project folder in VS Code.
4. Edit any file for at least 1-2 minutes.
5. Check backend logs and confirm this endpoint appears:
   - `POST /api/v1/vscode/minute-window`
6. Open the SQLite database in DB Browser:
   - `backend/smartdesk.db`
7. Go to Browse Data and select:
   - `vscode_minute_windows`
8. Confirm rows appear with fields like:
   - `window_start`, `window_end`, `timezone`
   - `workspace_name`, `project_path`, `repo_id`, `git_branch`
   - `active_file_name`, `active_language`
   - `active_editor_sec`, `idle_sec`
   - `edit_count`, `save_count`, `file_switch_count`
   - `terminal_command_count`, `debug_run_count`
9. Confirm expected behavior:
   - One row per 1-minute window
   - The same `user_id + window_start + window_end` does not create duplicates
   - Re-sending the same window updates the existing row
   - Different minutes create different rows

Note:

`python -m scripts.verify_vscode_minute_windows` only verifies the backend/database insert and upsert logic. It does not prove that the installed VS Code extension is sending data. To confirm extension data flow, check backend logs for:

- `POST /api/v1/vscode/minute-window`

and confirm rows appear in `vscode_minute_windows`.

---

## Browser 1-Minute Window Tracking

Browser data is now collected every 1 minute to align with OS and VS Code windows.

Verify browser minute windows:

1. Start the backend.
2. Load/reload the browser extension.
3. Use the browser normally for 2-3 minutes.
4. Confirm backend logs show browser payloads every 1 minute:
   - `POST /api/v1/browser/minute-window`
5. Open the database table used for browser minute-window data:
   - `browser_minute_windows`
6. Confirm one row appears per minute.
7. Confirm browser windows align with VS Code and OS windows using `window_start` and `window_end`.

---

## 10-Minute Productivity Summary

1-minute source data from OS, browser, VS Code, and calendar is aggregated into `productivity_summary_10min`.

Key points:

- Each row represents one 10-minute Asia/Colombo window.
- This table is used for dashboard display and the initial ML dataset.
- It prevents dashboard queries from directly depending on multiple raw/source tables.
- Each summary row only uses data inside the same 10-minute window to reduce leakage risk.

For ML training, use feature columns only and exclude:

- `activity_label`
- `focus_score`
- `label_source`
- `created_at`
- `updated_at`

Manual build and scheduler:

- Manual: `POST /api/v1/productivity-summary/10min/build` (useful for testing/backfills)
- Automatic: a background scheduler builds completed 10-minute windows every minute during normal backend runtime

---

## Structured Source Tables

SmartDesk now uses structured source tables for easier dashboard and ML aggregation:

- `os_minute_windows`
- `browser_minute_windows`
- `vscode_minute_windows`
- `calendar_events`

Legacy/raw tables remain as backup and for backward compatibility:

- `os_signals`
- `browser_signals`
- `vscode_signals`
- `calendar_signals`

The structured tables are the main source for `productivity_summary_10min`. This reduces JSON parsing and makes dashboard/ML feature generation easier.

---

## Table Status

Active tables for current dashboard/ML:

- `os_minute_windows`
- `browser_minute_windows`
- `vscode_minute_windows`
- `calendar_events`
- `productivity_summary_10min`

Legacy/raw backup tables:

- `os_signals`
- `browser_signals`
- `vscode_signals`
- `calendar_signals`

Deprecated/ignore unless needed:

- `vscode_sessions`
- `vscode_session_snapshots`
- `activity_sessions`
- `model1_features_10min`

Note: `dashboard.py` still uses legacy tables for its current view. The next planned step is to switch dashboard reads to `productivity_summary_10min`.

## 5. Google Calendar Setup

The Calendar collector is built into the backend, but it needs Google OAuth client config before `Connect` from the dashboard will work.

### Step 1: Create Google OAuth credentials

In Google Cloud:

1. Create or choose a project
2. Enable Google Calendar API
3. Configure OAuth consent
4. Create an OAuth client of type `Desktop app`
5. Download the client JSON file

Useful official links:

- Calendar quickstart: https://developers.google.com/workspace/calendar/api/quickstart/python
- OAuth consent guide: https://developers.google.com/workspace/guides/configure-oauth-consent
- Create credentials guide: https://developers.google.com/workspace/guides/create-credentials

### Step 2: Add the credentials to this project

You can use either method below.

#### Option A: Use `backend/.env`

1. Open the downloaded Google JSON file
2. Copy the values of:
   - `client_id`
   - `client_secret`
   - `project_id`
3. Create a new file:
   - `backend/.env`
4. Paste this and replace the values:

```env
SMARTDESK_GOOGLE_CLIENT_ID=your-desktop-app-client-id.apps.googleusercontent.com
SMARTDESK_GOOGLE_CLIENT_SECRET=your-client-secret
SMARTDESK_GOOGLE_PROJECT_ID=your-google-cloud-project-id
```

You can also copy from:

- `backend/.env.example`

#### Option B: Put the downloaded JSON file in the project

1. Take the JSON file you downloaded from Google Cloud
2. Rename it to:
   - `google_calendar_client.json`
3. Place it here:
   - `backend/app/config/google_calendar_client.json`

This is the exact path the backend checks for bundled Calendar OAuth config.

### Step 3: Restart the backend

If the backend was already running, stop it and start it again:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

### Step 4: Connect Google Calendar

1. Open the dashboard:
   - http://127.0.0.1:8000/dashboard/
2. In the Calendar section, click `Connect`
3. Sign in to Google
4. Approve Calendar read-only access

After success:

- the token is saved to `%APPDATA%\smartdesk-calendar\token.json`
- background sync runs automatically every 15 minutes

### Step 5: Check if it worked

On the dashboard, the Calendar status should change like this:

- `Needs credentials` -> config missing
- `Not connected` -> config found, waiting for user connect
- `Connected` -> token saved and sync is active

You can also test these endpoints:

- `GET /api/v1/calendar/status`
- `GET /api/v1/calendar/events`
- `POST /api/v1/calendar/sync`

---

## 6. Local Database

Database file:

- `backend/smartdesk.db`

Tables:

- `os_signals`
- `browser_signals`
- `browser_minute_windows`
- `vscode_signals`
- `vscode_minute_windows`
- `calendar_signals`
- `os_minute_windows`
- `calendar_events`
- `productivity_summary_10min`

If you want to inspect it manually, use DB Browser for SQLite:

- https://sqlitebrowser.org/

---

## 7. Current Save Frequency

- OS collector: saves every 60 seconds
- Browser extension: sends every 1 minute
- VS Code extension: sends every 1 minute
- Calendar collector: syncs every 15 minutes
- Summary scheduler: builds the latest completed 10-minute window every 60 seconds

---

## Timezone Standard

SmartDesk stores collector timestamps in Asia/Colombo ISO format.

Example:

- `2026-04-27T10:37:00+05:30`

This means 10:37 AM Sri Lanka time.

Rules:

- `timezone` should be `Asia/Colombo`
- `window_start` and `window_end` include `+05:30`
- We are not maintaining separate UTC/local columns at this MVP stage

This makes local debugging, DB Browser inspection, dashboard display, and 10-minute aggregation easier.

---

## Time-Window Architecture Summary

Current time-window architecture:

- OS collector -> 1-minute OS windows
- VS Code extension -> `vscode_minute_windows`, 1-minute windows
- Browser extension -> 1-minute browser windows
- Calendar collector -> event intervals / meeting overlap data
- Feature layer -> aggregates 1-minute data into 10-minute summaries

The 1-minute tables are the main source for dashboard and ML feature generation. Raw/session/event tables can remain for debugging or detailed analysis, but ML should primarily use the aligned 1-minute window data.

---

## 8. Troubleshooting

### `ModuleNotFoundError: No module named 'app'`

You started Uvicorn from the wrong folder.

Use:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

### Dashboard says `Needs credentials`

Calendar OAuth config is missing.

Fix it by either:

- creating `backend/.env`
- or adding `backend/app/config/google_calendar_client.json`

Then restart the backend.

### Dashboard says `Reconnect needed`

The saved Google token is no longer valid.

Delete:

- `%APPDATA%\smartdesk-calendar\token.json`

Then use `Connect` again from the dashboard.

### No browser data appears

Check:

- backend is running
- the extension is loaded from `browser extension/`

### No VS Code data appears

Check:

- the `.vsix` extension was installed successfully
- backend is running

---

## 9. Notes

- Calendar access is read-only
- All data stays local in SQLite
- This project is currently set up for development use by teammates