# SmartDesk — Full System Analysis

> Updated: 2026-05-03 | Covers: IDE Extension, Browser Extension, OS Collector, Calendar Sync, Productivity Summary

---

## Architecture Overview

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  VS Code / IDE   │  │ Browser Extension│  │   OS Collector   │
│  Extension (.ts) │  │  (background.js) │  │  (background svc)│
└───────┬──────────┘  └───────┬──────────┘  └───────┬──────────┘
        │ POST                │ POST                │ internal
        ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (main.py)                  │
│  Routes → Services → Repositories → SQLAlchemy ORM          │
└───────────────────────────┬─────────────────────────────────┘
                            │                 ▲
                            ▼                 │ (background)
                    ┌───────────────┐  ┌──────────────────────┐
                    │  smartdesk.db │  │ Calendar Sync Service │
                    │   (SQLite)    │  │ Productivity Scheduler│
                    └───────────────┘  └──────────────────────┘
```

**Database**: SQLite file at `backend/smartdesk.db`
**All timestamps**: Asia/Colombo (UTC+5:30)

---

## 1. VS Code / IDE Extension

**Source**: `smartdesk-ide-logger/src/extension.ts`
**Activation**: `onStartupFinished`

### What It Collects

Every **60 seconds**, the extension flushes a "minute window" payload:

| Field | Type | Description |
|---|---|---|
| `user_id` | string | From env `USER_ID`, default `"demo_user"` |
| `window_start` | ISO string | Start of the 60-second window |
| `window_end` | ISO string | End of the 60-second window |
| `timezone` | string | Always `"Asia/Colombo"` |
| `workspace_name` | string | VS Code workspace folder name |
| `project_path` | string | Filesystem path to workspace root |
| `repo_id` | string? | Git remote origin URL (from `.git/config`) |
| `git_branch` | string? | Current git branch (from `.git/HEAD`) |
| `active_file_path` | string? | Relative path of the active file |
| `active_file_name` | string? | Basename of the active file |
| `active_language` | string? | Language ID of the active file |
| `vscode_foreground_sec` | int | Seconds VS Code was the foreground window |
| `active_editor_sec` | int | Seconds user was actively editing (not idle) |
| `idle_sec` | int | Seconds idle (>90s no input while focused, or unfocused) |
| `edit_count` | int | Number of text changes (keystrokes) |
| `save_count` | int | Number of file saves |
| `file_switch_count` | int | Number of file tab switches |
| `terminal_command_count` | int | Terminal shell executions |
| `debug_run_count` | int | Debug sessions started |
| `source` | string | Always `"vscode_extension"` |
| `schema_version` | string | `"1.0"` |

### How Events Are Detected

| Event | VS Code API Used |
|---|---|
| Edits | `workspace.onDidChangeTextDocument` — counts `contentChanges.length` |
| Saves | `workspace.onDidSaveTextDocument` |
| File switches | `window.onDidChangeActiveTextEditor` |
| Debug runs | `debug.onDidStartDebugSession` |
| Terminal commands | `window.onDidStartTerminalShellExecution` |
| Foreground/idle | 1-second tick timer + `window.state.focused` + 90s idle threshold |

### Endpoint

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/v1/vscode/minute-window` | Minute window data (every 60s) |

### Table Written

| Table | Written By |
|---|---|
| `vscode_minute_windows` | `VSCodeMinuteWindowRepository.upsert()` |

---

## 2. Browser Extension

**Source**: `browser extension/background.js`
**Type**: Chrome/Edge Manifest V3 extension

### What It Collects

Every **60 seconds** (via `chrome.alarms`), it builds a minute window from local browsing history:

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Hardcoded `"demo_user"` |
| `window_start` / `window_end` | ISO string | 60-second window boundaries |
| `timezone` | string | `"Asia/Colombo"` |
| `browser_name` | string | Chrome / Edge / Firefox / Safari |
| `active_tab_domain` | string? | Domain of the currently active tab |
| `active_tab_url` | string? | Full URL of the active tab |
| `active_tab_title` | string? | Title of the active tab |
| `active_tab_category` | string? | `"Focused"` / `"Distracted"` / `"Neutral"` |
| `browser_active_time_sec` | int | Seconds of active browsing in this window |
| `browser_idle_time_sec` | int | Window duration minus active time |
| `productive_time_sec` | int | Seconds on focused/educational sites |
| `neutral_time_sec` | int | Seconds on neutral sites |
| `distracting_time_sec` | int | Seconds on distraction sites |
| `communication_time_sec` | int | Always `0` (not yet implemented) |
| `tab_switch_count` | int | Tab switches within the window |
| `unique_domains_count` | int | Distinct domains visited |

### Tab Classification Logic

```
1. Check title/URL for educational keywords → "Focused"
   (tutorial, course, programming, documentation, etc.)
2. Check URL for distraction domains → "Distracted"
   (facebook, instagram, tiktok, netflix, twitter, reddit, etc.)
3. Check URL for developer domains → "Focused"
   (github, stackoverflow, MDN, coursera, etc.)
4. Default → "Neutral"
```

**Special**: YouTube is NOT in the distracted list — it's classified by title keywords (educational YouTube = Focused).

### Idle Detection

- Uses `chrome.idle` API with 180-second threshold
- When idle/locked: closes current session, stops counting time
- When active again: resumes tracking from current tab

### Endpoint

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/v1/browser/minute-window` | Minute window data (every 60s) |

### Table Written

| Table | Written By |
|---|---|
| `browser_minute_windows` | `BrowserMinuteWindowRepository.upsert()` |

---

## 3. OS Collector

**Source**: `backend/app/services/os_monitoring_service.py`
**Type**: Background thread started on FastAPI startup (Windows only)

### What It Collects

Polls every **1 second**, flushes every **60 seconds**:

| Field | Type | Description |
|---|---|---|
| `user_id` | string | From env `USER_ID`, default `"demo_user"` |
| `window_start` / `window_end` | ISO string | 60-second window |
| `timezone` | string | `"Asia/Colombo"` |
| `active_time_sec` | int | Seconds of active computer use |
| `idle_time_sec` | int | Seconds idle (>60s no keyboard/mouse) |
| `locked_time_sec` | int | Seconds screen was locked |
| `context_switch_count` | int | App switches during the window |
| `top_app` | string? | Most-used app process name |
| `top_app_sec` | int? | Seconds spent in top app |
| `dominant_app_category` | string? | Most-used app category |
| `dominant_app_category_sec` | int? | Seconds in dominant category |
| `active_app_durations_json` | JSON string | `{"chrome.exe": 25.3, "Code.exe": 34.7}` |
| `category_durations_json` | JSON string | `{"browser": 25.3, "ide": 34.7}` |

### App Classification Logic

```
Process name heuristics:
  chrome/msedge/firefox/brave/opera → "browser"
  code/pycharm/idea/vscode          → "ide"
  whatsapp/slack/discord/outlook    → "communication"
  zoom/teams/skype/meet             → "meeting"
  winword/excel/powerpnt/pdf        → "docs"
  terminal/powershell/cmd/bash      → "terminal"
  explorer/taskmgr/systemsettings   → "system"
  
If no match: check Windows file metadata (Company/Product/Description)
If still no match: → "other"
```

### Lock Detection

- Uses `SessionWatcher` (Windows WTS session notifications)
- Also detects `LockApp.exe` as foreground process = locked

### Table Written

| Table | Written By |
|---|---|
| `os_minute_windows` | `OSMinuteWindowRepository.upsert()` |

---

## 4. Google Calendar Sync

**Source**: `backend/app/services/calendar_sync_service.py` + `calendar_service.py`
**Type**: Background thread, polls every 15 minutes

### What It Collects

Fetches upcoming 24h of events from Google Calendar API:

| Field | Type | Description |
|---|---|---|
| `user_id` | string | From env, default `"demo_user"` |
| `event_id` | string | Google Calendar event ID |
| `title` | string? | Event title/summary |
| `start_time` | ISO string | Event start |
| `end_time` | ISO string | Event end |
| `timezone` | string | Event timezone |
| `attendees_count` | int? | Number of attendees |
| `is_recurring` | bool? | Whether the event recurs |

### Table Written

| Table | Written By |
|---|---|
| `calendar_events` | `CalendarEventRepository.upsert()` |

---

## 5. Productivity Summary — 10-Minute Aggregation Window

**Source**: `backend/app/services/productivity_summary_service.py`
**Scheduler**: `backend/app/services/productivity_summary_scheduler.py`
**Repository**: `backend/app/repositories/productivity_summary_repository.py`
**Table**: `productivity_summary_10min`

### 5.1 How the Scheduler Works

The `ProductivitySummaryScheduler` runs as a **background daemon thread** started on FastAPI startup:

- **Tick interval**: Every **60 seconds** it checks whether a new 10-minute window has completed
- **Window alignment**: Windows are aligned to clock boundaries (e.g. 22:00, 22:10, 22:20...)
- **Deduplication**: Tracks `_last_built_end` — if the latest completed window was already built, it skips
- **User ID**: Hardcoded to `"demo_user"` (`SUMMARY_BUILDER_USER_ID`)
- **Upsert**: If a summary already exists for a window, it updates it; otherwise inserts

```
Timeline:
  22:00 ──── 22:10 ──── 22:20 ──── 22:30
   │          │          │          │
   └──window──┘          └──window──┘
     Built at ~22:11       Built at ~22:31
```

The scheduler can also be triggered manually via:
```
POST /api/v1/productivity-summary/10min/build
Body: { "user_id": "demo_user", "start_time": "...", "end_time": "..." }
```

### 5.2 Data Sources

For each 10-minute window, the service queries from the structured tables with SQL-level time range filtering:

| Source | Table |
|---|---|
| OS | `os_minute_windows` |
| Browser | `browser_minute_windows` |
| VS Code | `vscode_minute_windows` |
| Calendar | `calendar_events` |

Each source's 1-minute rows are **filtered to overlap** with the 10-minute window, then aggregated.

### 5.3 Full Column Breakdown — `productivity_summary_10min`

#### Window Identity (4 columns)

| Column | Type | Source | Description |
|---|---|---|---|
| `user_id` | STRING | Input parameter | User identifier |
| `window_start` | STRING | Computed | 10-min window start, e.g. `2026-05-02T22:10:00+05:30` |
| `window_end` | STRING | Computed | 10-min window end, e.g. `2026-05-02T22:20:00+05:30` |
| `timezone` | STRING | Hardcoded | Always `"Asia/Colombo"` |

#### OS Metrics (6 columns) — from `os_minute_windows`

| Column | Type | Aggregation | Description |
|---|---|---|---|
| `os_active_sec` | INT | SUM of `active_time_sec` across overlapping rows | Total seconds the computer was actively used |
| `os_idle_sec` | INT | SUM of `idle_time_sec` | Seconds idle (no keyboard/mouse >60s) |
| `os_locked_sec` | INT | SUM of `locked_time_sec` | Seconds screen was locked |
| `context_switch_count` | INT | SUM of `context_switch_count` | Total app switches |
| `top_app` | STRING | Most frequent `top_app` weighted by `top_app_sec` | e.g. `"Code.exe"` |
| `dominant_app_category` | STRING | Most frequent category weighted by duration | e.g. `"ide"`, `"browser"` |

#### Browser Metrics (9 columns) — from `browser_minute_windows`

| Column | Type | Aggregation | Description |
|---|---|---|---|
| `browser_active_sec` | INT | SUM of `browser_active_time_sec` | Total browser active time |
| `productive_browser_sec` | INT | SUM of `productive_time_sec` | Time on focused/educational sites |
| `neutral_browser_sec` | INT | SUM of `neutral_time_sec` | Time on neutral sites |
| `distracting_browser_sec` | INT | SUM of `distracting_time_sec` | Time on distraction sites |
| `communication_browser_sec` | INT | SUM of `communication_time_sec` | Time on communication sites |
| `tab_switch_count` | INT | SUM of `tab_switch_count` | Total tab switches |
| `unique_domains_count` | INT | SUM of `unique_domains_count` | Total unique domains |
| `top_domain` | STRING | Most frequently seen `active_tab_domain` | e.g. `"github.com"` |
| `active_tab_category` | STRING | Most frequently seen `active_tab_category` | `"Focused"` / `"Distracted"` / `"Neutral"` |

#### VS Code Metrics (12 columns) — from `vscode_minute_windows`

| Column | Type | Aggregation | Description |
|---|---|---|---|
| `vscode_foreground_sec` | INT | SUM of `vscode_foreground_sec` | Seconds VS Code was foreground |
| `vscode_active_sec` | INT | SUM of `active_editor_sec` | Seconds actively editing |
| `vscode_idle_sec` | INT | SUM of `idle_sec` | Seconds idle in VS Code |
| `edit_count` | INT | SUM of `edit_count` | Total text changes |
| `save_count` | INT | SUM of `save_count` | Total file saves |
| `file_switch_count` | INT | SUM of `file_switch_count` | Total file tab switches |
| `terminal_command_count` | INT | SUM of `terminal_command_count` | Terminal commands executed |
| `debug_run_count` | INT | SUM of `debug_run_count` | Debug sessions started |
| `active_project` | STRING | Most frequent `workspace_name` (or `project_path`) | e.g. `"smartdesk"` |
| `active_file_name` | STRING | From the latest minute-window row | e.g. `"extension.ts"` |
| `active_language` | STRING | Most frequent `active_language` | e.g. `"python"`, `"typescript"` |
| `git_branch` | STRING | From the latest minute-window row | e.g. `"dev"` |

#### Calendar Metrics (3 columns) — from `calendar_events` or `calendar_signals`

| Column | Type | Aggregation | Description |
|---|---|---|---|
| `calendar_meeting_sec` | INT | SUM of overlap seconds between event time range and 10-min window | Seconds in meetings |
| `in_meeting` | INT (0/1) | `1` if `calendar_meeting_sec > 0` | Binary meeting flag |
| `meeting_title` | STRING | Title of the first overlapping event | e.g. `"Sprint Planning"` |

#### Derived / ML Columns (3 columns) — computed by rule engine

| Column | Type | Description |
|---|---|---|
| `focus_score` | INT (0-100) | Composite productivity score (see formula below) |
| `activity_label` | STRING | Human-readable activity classification (see decision tree below) |
| `label_source` | STRING | Always `"rule_based"` (placeholder for future ML) |

#### Data Quality Columns (2 columns)

| Column | Type | Description |
|---|---|---|
| `data_quality_score` | INT (0-100) | `(sources_present / 4) × 100`. If all 4 sources have data → 100 |
| `missing_sources` | STRING (JSON) | e.g. `["browser", "calendar"]` — which sources had zero rows |

#### Metadata (4 columns)

| Column | Type | Description |
|---|---|---|
| `source` | STRING | Always `"productivity_summary_10min"` |
| `schema_version` | STRING | `"1.0"` |
| `created_at` | STRING | ISO timestamp of first insert |
| `updated_at` | STRING | ISO timestamp of last update |

**Total: 43 columns** in `productivity_summary_10min`.

### 5.4 Focus Score Formula

```python
score = 50                                          # Base score

# Positive signals
score += min(30, vscode_active / 600 * 30)          # Up to +30 for coding
score += min(20, productive_browser / 600 * 20)     # Up to +20 for learning
score += min(20, os_active / 600 * 20)              # Up to +20 for being active

# Negative signals
score -= min(30, distracting_browser / 600 * 30)    # Up to -30 for distractions
score -= min(20, os_idle / 600 * 20)                # Up to -20 for idling
score -= min(10, (context_switches + tab_switches) / 20 * 10)  # Up to -10 for switching

# Final range
score = clamp(score, 0, 100)
```

**600** = `WINDOW_SECONDS` (10 minutes × 60)

| Example Scenario | Score |
|---|---|
| 10 min solid coding, no distractions | ~100 |
| 10 min browsing stackoverflow | ~70 |
| 10 min on social media | ~20 |
| 10 min idle/locked | ~10 |
| Mixed coding + some YouTube | ~60 |

### 5.5 Activity Label Decision Tree

Labels are evaluated **top-to-bottom** — first match wins:

```
1. Meeting    → calendar_meeting_sec > 0
                 "User is in a calendar meeting"

2. Idle       → os_idle_sec >= 300 OR (os_active + browser_active + vscode_active) < 120
                 "User is away or barely active"

3. Focused    → vscode_active_sec >= 300 AND distracting_browser_sec <= 60
                 "Deep work — coding with minimal distractions"

4. Learning   → productive_browser_sec >= 300 AND edit_count <= 2
                   AND active_tab_category == "Focused"
                 "Reading docs/tutorials without writing code"

5. Distracted → distracting_browser_sec >= 180
                 "3+ minutes on social media / entertainment"

6. Multitask  → (context_switches + tab_switches + file_switches) >= 15
                 "Rapidly switching between many apps/tabs/files"

7. Unknown    → none of the above matched
```

### 5.6 Sample `productivity_summary_10min` Row

```json
{
  "id": 42,
  "user_id": "demo_user",
  "window_start": "2026-05-02T22:10:00+05:30",
  "window_end": "2026-05-02T22:20:00+05:30",
  "timezone": "Asia/Colombo",

  "os_active_sec": 520,
  "os_idle_sec": 80,
  "os_locked_sec": 0,
  "context_switch_count": 6,
  "top_app": "Code.exe",
  "dominant_app_category": "ide",

  "browser_active_sec": 120,
  "productive_browser_sec": 100,
  "neutral_browser_sec": 20,
  "distracting_browser_sec": 0,
  "communication_browser_sec": 0,
  "tab_switch_count": 3,
  "unique_domains_count": 2,
  "top_domain": "github.com",
  "active_tab_category": "Focused",

  "vscode_foreground_sec": 400,
  "vscode_active_sec": 350,
  "vscode_idle_sec": 50,
  "edit_count": 87,
  "save_count": 5,
  "file_switch_count": 4,
  "terminal_command_count": 2,
  "debug_run_count": 0,
  "active_project": "smartdesk",
  "active_file_name": "extension.ts",
  "active_language": "typescript",
  "git_branch": "dev",

  "calendar_meeting_sec": 0,
  "in_meeting": 0,
  "meeting_title": null,

  "focus_score": 85,
  "activity_label": "Focused",
  "label_source": "rule_based",

  "data_quality_score": 75,
  "missing_sources": "[\"calendar\"]",

  "source": "productivity_summary_10min",
  "schema_version": "1.0",
  "created_at": "2026-05-02T22:21:01+05:30",
  "updated_at": "2026-05-02T22:21:01+05:30"
}
```

---

## 6. Dashboard

**Source**: `backend/app/routes/dashboard.py`
**URL**: `http://localhost:8000/dashboard/`

The dashboard reads from the **active structured tables** to show summary cards and a 24-hour timeline chart.

| Read From | Purpose |
|---|---|
| `os_minute_windows` | Count + last `window_start` |
| `browser_minute_windows` | Count + last `window_start` |
| `vscode_minute_windows` | Count + last `window_start` |
| `calendar_events` | Count + last `start_time` |

---

## 7. Data Source → Table Mapping

Each data source writes to exactly **one table** (no dual-writes):

| Data Source | Collector | Table Written | Write Method |
|---|---|---|---|
| **IDE Extension** (TypeScript) | POST `/api/v1/vscode/minute-window` | `vscode_minute_windows` | Upsert (user_id + window_start + window_end) |
| **Browser Extension** (JS) | POST `/api/v1/browser/minute-window` | `browser_minute_windows` | Upsert (user_id + window_start + window_end) |
| **OS Collector** (background thread) | Internal — `OSMinuteWindowService` | `os_minute_windows` | Upsert (user_id + window_start + window_end) |
| **Calendar Sync** (background thread) | Internal — `CalendarEventService` | `calendar_events` | Upsert (user_id + event_id) |
| **Productivity Scheduler** (background thread) | Internal — `ProductivitySummaryRepository` | `productivity_summary_10min` | Upsert (user_id + window_start + window_end) |



---

## 8. Complete Table Inventory (Current)

| # | Table Name | Columns | Writer | Reader(s) |
|---|---|---|---|---|
| 1 | `os_minute_windows` | 16 cols — user_id, window_start/end, timezone, active/idle/locked_time_sec, context_switch_count, top_app/sec, dominant_category/sec, app_durations_json, category_durations_json, source, schema_version, created/updated_at | `OSMinuteWindowRepository` | Dashboard, ProductivitySummaryService |
| 2 | `browser_minute_windows` | 20 cols — user_id, window_start/end, timezone, browser_name, active_tab_domain/url/title/category, active/idle_time_sec, productive/neutral/distracting/communication_time_sec, tab_switch_count, unique_domains_count, source, schema_version, created/updated_at | `BrowserMinuteWindowRepository` | Dashboard, ProductivitySummaryService |
| 3 | `vscode_minute_windows` | 22 cols — user_id, window_start/end, timezone, workspace_name, project_path, repo_id, git_branch, active_file_path/name, active_language, vscode_foreground_sec, active_editor_sec, idle_sec, edit/save/file_switch/terminal_command/debug_run_count, source, schema_version, created/updated_at | `VSCodeMinuteWindowRepository` | Dashboard, ProductivitySummaryService |
| 4 | `calendar_events` | 12 cols — user_id, event_id, title, start/end_time, timezone, attendees_count, is_recurring, source, schema_version, created/updated_at | `CalendarEventRepository` | Dashboard, ProductivitySummaryService, CalendarService |
| 5 | `productivity_summary_10min` | 43 cols — see Section 5.3 for full breakdown | `ProductivitySummaryRepository` | API |

**Total: 5 active tables.**

---

## 9. Legacy Items Removed

The following legacy items were cleaned up in this audit:

### 9A. Deleted Database Models (4 classes removed from `db_models.py`)

| Model | Table | Reason |
|---|---|---|
| `OSSignalRecord` | `os_signals` | Replaced by `OSMinuteWindowRecord` |
| `BrowserRecord` | `browser_signals` | Replaced by `BrowserMinuteWindowRecord` |
| `VSCodeRecord` | `vscode_signals` | Replaced by `VSCodeMinuteWindowRecord` |
| `CalendarRecord` | `calendar_signals` | Replaced by `CalendarEventRecord` |

### 9B. Deleted Code Files (14 files)

| File | Was |
|---|---|
| `routes/os_signals.py` | Legacy POST endpoint for OS signals |
| `routes/calendar.py` | Legacy POST endpoint for calendar |
| `services/os_signals_service.py` | Service for legacy OS signals |
| `services/browser_service.py` | Service for legacy browser signals |
| `services/vscode_service.py` | Service for legacy VSCode sessions |
| `repositories/os_signals_repository.py` | Repository for `os_signals` table |
| `repositories/browser_repository.py` | Repository for `browser_signals` table |
| `repositories/vscode_repository.py` | Repository for `vscode_signals` table |
| `repositories/calendar_repository.py` | Repository for `calendar_signals` table |
| `models/os_signals.py` | Pydantic model for OS signal payloads |
| `models/browser.py` | Pydantic model for browser payloads |
| `models/vscode.py` | Pydantic model for VSCode session payloads |
| `models/calendar.py` | Pydantic model for calendar payloads |
| `Collector_v2.py` | Standalone MongoDB-based OS collector (dead code) |

### 9C. Removed Legacy Routes

| Route | Status |
|---|---|
| `POST /api/v1/os-signals/` | ❌ Removed |
| `POST /api/v1/calendar/` | ❌ Removed |
| `POST /api/v1/browser/` (legacy history sync) | ❌ Removed |
| `POST /api/v1/vscode/` (legacy session) | ❌ Removed |

### 9D. Deleted ML Module (May 2026 cleanup)

| Item | Reason |
|---|---|
| `app/ml/__init__.py` | ML module referencing deleted legacy tables |
| `app/ml/model1_features.py` | Feature builder for deleted `os_signals`/`vscode_signals` tables |
| `app/ml/activity_sessions.py` | Session builder depending on deleted `model1_features_10min` |
| `scripts/build_model1_dataset.py` | Runner script for deleted ML module |
| `scripts/build_activity_sessions.py` | Runner script for deleted ML module |
| `scripts/debug_db.py` | Debug script importing deleted models |
| `scripts/migrate_vscode_tables.py` | Migration script importing deleted models |
| `scripts/migrate_activity_sessions_table.py` | Migration for deprecated table |
| `scripts/verify_*.py` (5 files) | One-time verification scripts |
| `scripts/test_vscode_workflow.py` | Manual test script |
| `calender/` directory | Legacy standalone calendar module (typo in name, fully replaced) |
| `db_dump.py`, `db_dump.json` | One-off database cleanup artifacts |
| Root `package.json`, `package-lock.json`, `node_modules/` | Phantom Node artifacts not used by any module |

---

## 10. Real Data Samples

### VS Code Minute Window (actual payload from extension)

```json
{
  "user_id": "demo_user",
  "window_start": "2026-05-02T22:29:00+05:30",
  "window_end": "2026-05-02T22:30:00+05:30",
  "timezone": "Asia/Colombo",
  "workspace_name": "smartdesk",
  "project_path": "C:\\Users\\speed\\Desktop\\Software project\\SmartDesk\\smartdesk",
  "repo_id": "https://github.com/Aysha-Shahanee/smartdesk.git",
  "git_branch": "dev",
  "active_file_path": "backend/app/models/vscode.py",
  "active_file_name": "vscode.py",
  "active_language": "python",
  "vscode_foreground_sec": 45,
  "active_editor_sec": 38,
  "idle_sec": 15,
  "edit_count": 12,
  "save_count": 2,
  "file_switch_count": 3,
  "terminal_command_count": 1,
  "debug_run_count": 0,
  "source": "vscode_extension",
  "schema_version": "1.0"
}
```

### Browser Minute Window (actual payload from extension)

```json
{
  "user_id": "demo_user",
  "window_start": "2026-05-02T22:29:00+05:30",
  "window_end": "2026-05-02T22:30:00+05:30",
  "timezone": "Asia/Colombo",
  "browser_name": "Chrome",
  "active_tab_domain": "github.com",
  "active_tab_url": "https://github.com/Aysha-Shahanee/smartdesk",
  "active_tab_title": "smartdesk repository",
  "active_tab_category": "Focused",
  "browser_active_time_sec": 55,
  "browser_idle_time_sec": 5,
  "productive_time_sec": 55,
  "neutral_time_sec": 0,
  "distracting_time_sec": 0,
  "communication_time_sec": 0,
  "tab_switch_count": 2,
  "unique_domains_count": 1,
  "source": "browser_extension",
  "schema_version": "1.0"
}
```

### OS Minute Window (actual payload from collector)

```json
{
  "user_id": "demo_user",
  "window_start": "2026-05-02T22:29:00+05:30",
  "window_end": "2026-05-02T22:30:00+05:30",
  "timezone": "Asia/Colombo",
  "active_time_sec": 52,
  "idle_time_sec": 8,
  "locked_time_sec": 0,
  "context_switch_count": 4,
  "top_app": "Code.exe",
  "top_app_sec": 34,
  "dominant_app_category": "ide",
  "dominant_app_category_sec": 34,
  "active_app_durations_json": "{\"Code.exe\": 34.2, \"chrome.exe\": 17.8}",
  "category_durations_json": "{\"ide\": 34.2, \"browser\": 17.8}",
  "source": "os_collector",
  "schema_version": "1.0"
}
```

---

## 11. Final Clean Data Flow

```
IDE Extension ──POST──→ /vscode/minute-window ──→ vscode_minute_windows
Browser Ext   ──POST──→ /browser/minute-window ──→ browser_minute_windows
OS Collector  ──────────── (background thread) ──→ os_minute_windows
Calendar Sync ──────────── (background thread) ──→ calendar_events
                                                       │
                     ┌─────────────────────────────────┘
                     ▼
Productivity    reads all 4 tables above every 60s
Scheduler  ──→ aggregates into 10-min windows ──→ productivity_summary_10min
                                                       │
Dashboard   reads all 5 tables ◄───────────────────────┘
```

