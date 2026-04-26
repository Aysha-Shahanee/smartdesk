# SmartDesk Data Collection Layer

This project collects a developer's activity from multiple sources and stores it locally in a SQLite database:

- OS signals (active window, idle time, lock status)
- Browser activity (tabs, URLs, basic focus/distracted classification)
- VS Code activity (via a dedicated extension)
- Google Calendar events
- A small dashboard UI to visualize what has been stored

---

## 1. Backend API & Collectors

### 1.1. Requirements

- Python 3.10+ (recommended)
- PowerShell (on Windows, default)

### 1.2. Setup and run backend

From the `backend` folder:

```powershell
cd "path/to/software project-2nd year/implementation/data collection layer/backend"

# Activate the shared project virtual environment
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& "path/to/software project-2nd year/implementation/data collection layer/.venv/Scripts/Activate.ps1"

# Install dependencies
python -m pip install -r requirements.txt

# Run the FastAPI app
python -m uvicorn app.main:app --reload
```

Once it starts you should see log lines like:

- `Initializing local SQLite database...`
- `Starting OS Collector background service...`
- `Starting Calendar Collector background service...`

The API will be listening at:

- http://127.0.0.1:8000/

### 1.3. Dashboard UI

A small dashboard UI is available to see an overview of stored data.

- Open: http://127.0.0.1:8000/dashboard/

It shows:

- Total records and last timestamp per source (OS, Browser, VS Code, Calendar)
- A simple 24-hour time series of event counts
- A static setup checklist (can be edited later)

### 1.4. Prepare VS Code tables

If you are using the new clean VS Code session flow, run these in order after cloning:

```powershell
cd "path/to/software project-2nd year/implementation/data collection layer/backend"
python scripts/migrate_vscode_tables.py
python scripts/verify_vscode_schema.py
python scripts/build_model1_dataset.py
```

This essential sequence does the following:

- `vscode_sessions`
- `vscode_session_snapshots`

and then rebuilds:

- `model1_features_10min`

If you only need to inspect the tables without rebuilding the aggregation, run the first two commands only.

---

## 2. Browser Extension (Chrome / Edge / Firefox)

The browser extension tracks active tabs and periodically sends summarized history to the backend.

Source folder:

- `browser extension/` (top-level folder in this repo)

Key behaviors:

- Classifies pages as Focused / Distracted / Neutral (simple heuristics)
- Logs tab changes, window focus changes, and idle time
- Every 5 minutes, sends a batch to:
  - `http://127.0.0.1:8000/api/v1/browser/`

### 2.1. Install in Chrome / Edge (development)

1. Build / run backend as above.
2. Open browser extensions page:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
3. Turn on **Developer mode**.
4. Click **Load unpacked**.
5. Select the `browser extension` folder from this repo.

The extension icon should appear and start logging when the backend is running.

### 2.2. Install in Firefox (temporary add-on)

1. Build / run backend as above.
2. Open `about:debugging` in Firefox.
3. Choose **This Firefox** → **Load Temporary Add-on…**.
4. Select the `manifest.json` inside the `browser extension` folder.

Note: This loads the add-on temporarily (it is removed when Firefox restarts). For permanent distribution, the extension should be packaged and submitted to the Firefox Add-ons store.

---

## 3. VS Code Extension (SmartDesk IDE Logger)

The VS Code extension sends IDE-related activity to the backend.

Source folder:

- `smartdesk-ide-logger/`

### 3.1. Install dependencies and run in development

From the `smartdesk-ide-logger` folder:

```powershell
cd "path/to/software project-2nd year/implementation/data collection layer/smartdesk-ide-logger"

npm install
```

Then, open this folder in VS Code and press **F5** to launch an **Extension Development Host**. That VS Code window will have the extension running and can send events to the backend.

If you want to install the packaged extension instead of running it from source, use the VSIX file inside this folder:

- `smartdesk-ide-logger/smartdesk-ide-logger-0.0.1.vsix`

Install it from VS Code by choosing **Extensions** -> **...** -> **Install from VSIX**.

Later, this extension can be packaged and published to the VS Code Marketplace for easier installation.

### 3.2. What the VS Code extension sends

The extension tracks one file-focused session at a time.

- Opening a file starts a new session
- Switching to another file closes the previous session and starts a new one
- The same session sends multiple snapshots with the same `event_id`

The backend stores these into:

- `vscode_sessions` for one clean row per session
- `vscode_session_snapshots` for the full timeline of periodic updates

---

## 4. Google Calendar Integration

The backend includes a background task that periodically reads events from your Google Calendar and stores them locally.

- On first run, when the calendar sync starts, it will open a browser window asking you to **allow access** to your Google Calendar.
- After you approve, a token is stored in a user-specific directory and future syncs run silently.

Behavior:

- Fetches upcoming events (by default: now to +24 hours)
- Runs on startup, then at a fixed interval (currently every 15 minutes)
- Stores normalized event data in the `calendar_signals` table inside `smartdesk.db`

---

## 5. Viewing the SQLite Database (DB Browser for SQLite)

All collected data is stored in a local SQLite database file:

- `backend/smartdesk.db`

You can inspect it using **DB Browser for SQLite** or any other SQLite client.

### 5.1. Using DB Browser for SQLite

1. Download and install **DB Browser for SQLite**:
   - https://sqlitebrowser.org/
2. Open the application.
3. Click **Open Database**.
4. Browse to this project and select:
   - `backend/smartdesk.db`
5. Go to the **Browse Data** tab.
6. Use the **Table** dropdown to inspect different data sources:
   - `os_signals` – OS-level summaries (window focus, idle/active/locked times)
   - `browser_signals` – Browser history sync batches
   - `vscode_sessions` – Clean one-row-per-session VS Code data
   - `vscode_session_snapshots` – Detailed VS Code timeline snapshots
   - `vscode_signals` – Legacy/raw VS Code events kept for fallback/backward compatibility
   - `calendar_signals` – Google Calendar events

   For the aggregated dataset used by Model 1, also inspect:
   - `model1_features_10min` – One row per 10-minute window

You can filter, sort, and export these tables as needed (CSV, JSON, etc.).

---

## 6. Typical Developer Workflow

For a collaborator who just cloned the repo:

1. **Backend**
   - Setup venv and install requirements.
   - Run `python -m uvicorn app.main:app --reload`.
   - Visit `http://127.0.0.1:8000/dashboard/`.

2. **Browser extension**
   - Load `browser extension/` as an unpacked extension in Chrome/Edge, or a temporary add-on in Firefox.

3. **VS Code extension**
   - In `smartdesk-ide-logger`, run `npm install` and start the extension host via VS Code (F5).

4. **Calendar**
   - On first run of the backend, accept the Google Calendar permission prompt.

5. **Inspect data**
   - Use the dashboard or DB Browser for SQLite to see what has been stored in `smartdesk.db`.

## 7. Model 1 Aggregation Workflow

The aggregation code lives in:

- `backend/app/ml/model1_features.py`

It builds the `model1_features_10min` table from:

- `os_signals`
- `browser_signals`
- `vscode_sessions`
- `calendar_signals`

### 7.1. Build the aggregated table

From the `backend` folder:

```powershell
cd "path/to/software project-2nd year/implementation/data collection layer/backend"
python scripts/build_model1_dataset.py
```

If you want to target a specific SQLite file:

```powershell
python scripts/build_model1_dataset.py "path/to/smartdesk.db"
```

### 7.2. See the aggregation output

The script writes rows into the `model1_features_10min` table inside `backend/smartdesk.db`.

You can inspect it with:

```powershell
python scripts/verify_vscode_schema.py
```

Or open `backend/smartdesk.db` in DB Browser for SQLite and browse the `model1_features_10min` table.

### 7.3. Quick validation checks

After rebuilding, useful checks are:

- `vscode_total_duration_sec <= 600` for each 10-minute row
- `vscode_active_seconds + vscode_idle_seconds <= vscode_total_duration_sec`
- `window_start` and `window_end` use UTC format ending in `+00:00`
- `manual_label` remains unchanged if it was already filled in

This README can be expanded over time as the product evolves (e.g., packaging, installers, or cloud sync).