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

# (Recommended) Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

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

Later, this extension can be packaged and published to the VS Code Marketplace for easier installation.

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
   - `vscode_signals` – VS Code events
   - `calendar_signals` – Google Calendar events

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

This README can be expanded over time as the product evolves (e.g., packaging, installers, or cloud sync).