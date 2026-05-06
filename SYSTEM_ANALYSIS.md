# SmartDesk — Full System Analysis

> Updated: 2026-05-06 | Covers: IDE Extension, Browser Extension, OS Collector, Calendar Sync, Activity Timeline Index

---

## Architecture Overview

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  IDE Extension   │  │ Browser Extension│  │   OS Collector   │
│  (.ts / plugin)  │  │  (background.js) │  │  (background svc)│
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
                    │   (SQLite)    │  │ Timeline Index Builder│
                    └───────────────┘  └──────────────────────┘
```

**Database**: SQLite file at `backend/smartdesk.db`
**Timezones**: Dynamic (uses the local system timezone of the collector)

---

## 1. IDE Extension (VS Code, Antigravity, JetBrains)

**Source Example**: `smartdesk-ide-logger/src/extension.ts`
**Activation**: `onStartupFinished`

### What It Collects

Every **60 seconds**, the extension flushes an IDE-agnostic "minute window" payload. The `source` field identifies the IDE (e.g., `"vscode_extension"`, `"antigravity_extension"`).

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Configured user ID |
| `window_start` / `window_end` | ISO string | Start/end of the 60-second window |
| `timezone` | string | Detected local timezone |
| `workspace_name` | string | IDE workspace/project name |
| `project_path` | string | Filesystem path to workspace root |
| `repo_id` | string? | Hashed Git remote origin URL (for privacy) |
| `git_branch` | string? | Current git branch |
| `active_file_path` | string? | Relative path of the active file |
| `active_file_name` | string? | Basename of the active file |
| `active_language` | string? | Language ID of the active file |
| `ide_foreground_sec` | int | Seconds the IDE was the foreground window |
| `active_editor_sec` | int | Seconds user was actively editing |
| `idle_sec` | int | Seconds idle |
| `edit_count` | int | Number of document mutations |
| `save_count` | int | Number of file saves |
| `file_switch_count` | int | Number of file tab switches |
| `terminal_command_count` | int | Terminal shell executions |
| `debug_run_count` | int | Debug sessions started |
| `lines_added` / `lines_deleted` | int | Tracked line changes (supports AI generated code) |
| `source` | string | Identifies the IDE plugin |

### Endpoint

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/v1/ide/minute-window` | Minute window data (every 60s) |

### Table Written

| Table | Written By |
|---|---|
| `ide_minute_windows` | `IDEMinuteWindowRepository.upsert()` |

---

## 2. Browser Extension

**Source**: `browser extension/background.js`
**Type**: Chrome/Edge/Firefox Manifest V3 extension

### What It Collects

Every **60 seconds** (via `chrome.alarms`), it builds a payload from local history. Background activity is properly excluded from active time. Hardcap of 5000 history entries is maintained for AI training.

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Configured user ID |
| `browser_name` | string | Chrome / Edge / Firefox |
| `active_tab_domain` / `url` / `title` | string? | Details of the active tab |
| `active_tab_category` | string? | `"Focused"` / `"Distracted"` / `"Neutral"` |
| `browser_active_time_sec` | int | Seconds of foreground browsing |
| `browser_idle_time_sec` | int | Window duration minus active time |
| `productive_time_sec` | int | Seconds on focused/educational sites |
| `neutral_time_sec` | int | Seconds on neutral sites |
| `distracting_time_sec` | int | Seconds on distraction sites |
| `tab_switch_count` | int | Tab switches within the window |
| `unique_domains_count` | int | Distinct domains visited |

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
| `active_time_sec` / `idle_time_sec` / `locked_time_sec` | int | State durations |
| `context_switch_count` | int | App switches |
| `top_app` / `top_app_sec` | string / int | Most-used app |
| `dominant_app_category` | string | App category (e.g., `"ide"`, `"browser"`) |
| `active_app_durations_json` | string | JSON map of app times |

### Table Written

| Table | Written By |
|---|---|
| `os_minute_windows` | `OSMinuteWindowRepository.upsert()` |

---

## 4. Google Calendar Sync

**Source**: `backend/app/services/calendar_sync_service.py`
**Type**: Background thread, polls every 15 minutes, configured via `.env` OAuth credentials.

### Table Written

| Table | Written By |
|---|---|
| `calendar_events` | `CalendarEventRepository.upsert()` |

---

## 5. Activity Timeline Index

**Source**: `backend/app/services/activity_session_summary_service.py`
**Repository**: `backend/app/repositories/activity_session_summary_repository.py`
**Table**: `activity_timeline_index`

### 5.1 Architecture

The system uses a canonical foreground activity timeline. Instead of redundantly storing detailed metrics, `activity_timeline_index` serves as a lean index. 

Each row represents one minute window and records:
- **Foreground authority**: Uses OS data to determine what the user was actually looking at (`"ide"`, `"browser"`, `"terminal"`, `"os"`).
- **Data availability flags**: `has_os_data`, `has_ide_data`, `has_browser_data`.
- **Context links**: `ide_workspace`, `browser_domain`.

When the dashboard needs detailed IDE metrics (like `lines_added`), it queries `ide_minute_windows` directly using the timeframe defined by the timeline index.

### 5.2 Background Builder

The `Activity Timeline Scheduler` runs every 60 seconds and rebuilds the timeline for the last 30 minutes, ensuring late-arriving data (due to offline extension buffering) is incorporated.

---

## 6. Dashboard & Aggregate Service

**Source**: `backend/app/services/dashboard_service.py` and `routes/dashboard.py`

The new `DashboardService` aggregates data from raw minute-window tables.

### Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/dashboard/` | Debug HTML UI |
| GET | `/dashboard/stats` | JSON summary + 24h timeline datasets |
| GET | `/dashboard/os?user_id=...` | OS activity metrics |
| GET | `/dashboard/ide?user_id=...` | IDE/coding metrics (`coding_time_sec`, `lines_added`) |
| GET | `/dashboard/browser?user_id=...` | Browser classification metrics |
| GET | `/dashboard/sessions?user_id=...` | Foreground activity timeline entries |

---

## 7. Data Source → Table Mapping

Each data source writes to exactly **one table**:

| Data Source | Route / Internal | Table Written |
|---|---|---|
| **IDE Extension** | POST `/api/v1/ide/minute-window` | `ide_minute_windows` |
| **Browser Extension**| POST `/api/v1/browser/minute-window` | `browser_minute_windows` |
| **OS Collector** | Internal | `os_minute_windows` |
| **Calendar Sync** | Internal | `calendar_events` |
| **Timeline Builder** | Internal | `activity_timeline_index` |

---

## 8. Complete Table Inventory (Current Schema)

All raw tables include `timeline_index_id` (for synchronization) and `extra_data` (JSON blob for AI extensibility).

| # | Table Name | Key New Fields |
|---|---|---|
| 1 | `os_minute_windows` | `timeline_index_id`, `extra_data` |
| 2 | `browser_minute_windows` | `timeline_index_id`, `extra_data` |
| 3 | `ide_minute_windows` | `lines_added`, `lines_deleted`, `ide_foreground_sec`, `timeline_index_id` |
| 4 | `calendar_events` | `extra_data` |
| 5 | `activity_timeline_index` | `foreground_source`, `has_ide_data`, `ide_workspace` |

---

## 9. Legacy Items Removed

The following legacy items were cleaned up in recent modernizations:
- **`activity_session_summary` table**: Replaced by the lean `activity_timeline_index`.
- **`productivity_summary_10min` table**: Removed in favor of dynamic dashboard aggregation.
- **Legacy `_signals` tables**: (`os_signals`, `vscode_signals`, etc.) fully replaced by `_minute_windows`.
- **Hardcoded Timezones**: Removed; system now respects dynamic local timezones and UTC server timestamps.
- **Hardcoded Credentials**: Removed from codebase; handled via `pydantic-settings` and `.env`.

---

## 10. Real Data Sample (IDE Agnostic)

```json
{
  "user_id": "speed",
  "window_start": "2026-05-06T13:42:00+05:30",
  "window_end": "2026-05-06T13:43:00+05:30",
  "timezone": "Asia/Colombo",
  "workspace_name": "smartdesk",
  "project_path": "C:\\Users\\speed\\Desktop\\Software project\\SmartDesk\\smartdesk",
  "repo_id": "4c3d2e1f",
  "git_branch": "main",
  "active_file_path": "backend/app/models/ide_minute_window.py",
  "active_file_name": "ide_minute_window.py",
  "active_language": "python",
  "ide_foreground_sec": 60,
  "active_editor_sec": 45,
  "idle_sec": 15,
  "edit_count": 24,
  "save_count": 1,
  "file_switch_count": 0,
  "terminal_command_count": 0,
  "debug_run_count": 0,
  "lines_added": 12,
  "lines_deleted": 4,
  "source": "antigravity_extension",
  "schema_version": "1.0"
}
```

---

## 11. Final Clean Data Flow

```
IDE Extension ──POST──→ /ide/minute-window     ──→ ide_minute_windows
Browser Ext   ──POST──→ /browser/minute-window ──→ browser_minute_windows
OS Collector  ──────────── (background thread) ──→ os_minute_windows
Calendar Sync ──────────── (background thread) ──→ calendar_events
                                                        │
                     ┌──────────────────────────────────┘
                     ▼
Timeline Index   derives from OS windows, enriched
Builder      ──→ with browser/ide flags ──→ activity_timeline_index
                                                        │
Dashboard API   reads all 5 tables ◄────────────────────┘
```
