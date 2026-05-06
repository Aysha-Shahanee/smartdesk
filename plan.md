# SmartDesk — Full Refactoring & Implementation Plan

> **Project**: Developer productivity tracking desktop app  
> **Stack**: FastAPI + SQLite (backend) · VS Code extension (TypeScript) · Browser extension (MV3 JS) · Desktop app (TBD)  
> **Goal**: Clean MVP dashboard with OS, IDE, and browser panels. Phase 2 adds cloud AI insights.

---

## Part 1 — Issues Found (Current State)

### 1.1 VS Code Extension (`smartdesk-ide-logger`)

| # | Issue | Impact |
|---|-------|--------|
| 1 | Timezone hardcoded to `Asia/Colombo` | Breaks for every developer not in Sri Lanka |
| 2 | `repo_id` is raw git remote URL (e.g. `git@github.com:user/repo.git`) | Exposes sensitive paths, inconsistent format, should be a hash |
| 3 | `USER_ID` read from `process.env.USER_ID` with `"demo_user"` fallback | Fragile — env vars are not reliable in VS Code extensions; should use VS Code settings |
| 4 | API URL hardcoded to `http://localhost:8000` | No way for user to configure port |
| 5 | No offline buffering — if backend is down the minute window is silently lost | Data gaps in dashboard |
| 6 | `edit_count` counts `contentChanges.length`, not logical edits — auto-format inflates this massively | Misleading metric |
| 7 | `created_at` / `updated_at` sent from the extension | Should be set by the backend, not the client |
| 8 | `schema_version` hardcoded as `"1.0"` string in extension | Backend should own versioning |
| 9 | No `lines_added` / `lines_deleted` tracking | Needed for phase 2 coding velocity metrics |
| 10 | No retry on failed POST — error is logged but minute is lost | Silent data loss |
| 11 | some time used here in different format and timezone | All time related stuff used here want to be in UTC+530 |

---

### 1.2 Browser Extension (`background.js`)

| # | Issue | Impact |
|---|-------|--------|
| 1 | Timezone hardcoded to `Asia/Colombo` | Same as IDE extension — breaks globally |
| 2 | `USER_ID = "demo_user"` hardcoded in the file — not even an env var | Every user shares the same ID |
| 3 | `getBrowserName()` uses `navigator.userAgent` — service workers in Chrome always return Chrome UA even inside Edge | Edge always reported as Chrome |
| 4 | `communication_time_sec` always set to `0` — not implemented | Field is always empty |
| 5 | Category classification uses naive URL+title keyword match — `reddit.com/r/programming` classified as Distracted | Wrong categorization for dev-adjacent content |
| 6 | Tab switch count logic counts entries whose `startTime` is in the window — first tab of session is always counted | Count is inflated by 1 every minute |
| 7 | History stored in `chrome.storage.local` — can grow unbounded if syncs fail | Storage fills up, eventual crash |
| 8 | No retry on failed POST | Silent data loss |
| 9 | API URL hardcoded to `http://127.0.0.1:8000` | Not user-configurable |
| 10 | Manifest name is `"Activity Tracker"` — generic, not branded | Confusing when users see it in chrome://extensions |
| 11 | `host_permissions: ["<all_urls>"]` — overly broad | App stores flag this; only need current tab URL |
| 12 | `created_at` / `updated_at` sent from the extension | Should be set by the backend |

---

### 1.3 Backend (`FastAPI + SQLite`)

| # | Issue | Impact |
|---|-------|--------|
| 1 | Raw SQL migration files executed on every startup | Fragile, doesn't scale, hides migration state |
| 2 | `models/` folder mixes SQLAlchemy ORM models and Pydantic schemas | Confusing imports, violates separation of concerns |
| 3 | `dashboard.py` route is 10KB — contains aggregation queries and business logic | Routes should only handle HTTP; logic belongs in services |
| 4 | No config layer — values hardcoded in source files | No way to configure without editing source |
| 5 | All `print()` calls — no logging infrastructure | No log levels, no file output, can't debug production |
| 6 | `allow_origins=["*"]` CORS — never tightened | Security gap even for local apps |
| 7 | `activity_session_summary` has 23+ columns including pre-aggregated data | Violates its own purpose as a session index |
| 8 | `Column(String)` for all timestamps instead of `Column(DateTime)` | SQLite tolerates this; PostgreSQL will break on migration |
| 9 | `user_id` is an unformatted string with no auth behind it | Not ready for multi-user phase 2 |
| 10 | `vscode_repository.py` exists alongside `vscode_minute_window_repository.py` | Naming confusion, unclear split of responsibility |
| 11 | No `tests/` directory | Nothing is tested |
| 12 | `session_watcher.py` sits in `core/` with unclear purpose | Should be in `collectors/` or `services/` |

---

## Part 2 — Target Architecture

```
smartdesk-backend/
├── alembic/                        # DB migrations (replaces raw SQL files)
│   └── versions/
├── app/
│   ├── core/
│   │   ├── config.py               # Pydantic Settings — all env vars here
│   │   ├── database.py             # Engine, SessionLocal, get_db dependency
│   │   └── logging.py              # Logging setup
│   ├── models/
│   │   ├── db/                     # SQLAlchemy ORM models ONLY
│   │   │   ├── os.py
│   │   │   ├── browser.py
│   │   │   ├── vscode.py
│   │   │   ├── calendar.py
│   │   │   └── session.py
│   │   └── schemas/                # Pydantic request/response schemas ONLY
│   │       ├── os.py
│   │       ├── browser.py
│   │       ├── vscode.py
│   │       ├── calendar.py
│   │       ├── session.py
│   │       └── dashboard.py        # Dashboard response shapes
│   ├── repositories/               # DB query logic only — no business logic
│   │   ├── os_repository.py
│   │   ├── browser_repository.py
│   │   ├── vscode_repository.py
│   │   ├── calendar_repository.py
│   │   └── session_repository.py
│   ├── services/                   # Business logic only — no HTTP, no DB queries
│   │   ├── dashboard_service.py    # Aggregation logic for all 3 panels
│   │   ├── session_scheduler.py    # Background session index builder
│   │   ├── os_collector.py         # OS monitoring (moved from core/)
│   │   └── calendar_sync.py        # Google Calendar sync (moved from core/)
│   ├── routes/                     # HTTP layer only — parse request, call service, return response
│   │   ├── ingest/
│   │   │   ├── os.py
│   │   │   ├── browser.py
│   │   │   ├── vscode.py
│   │   │   └── calendar.py
│   │   ├── dashboard.py
│   │   ├── sessions.py
│   │   └── health.py
│   └── main.py
├── tests/
│   ├── test_dashboard_service.py
│   ├── test_session_scheduler.py
│   └── test_repositories.py
├── .env
├── .env.example
└── requirements.txt
```

---

## Part 3 — Database Changes

### 3.1 Redesign `activity_session_summary` (most important change)

**Remove all 15+ aggregated columns. The table becomes a pure session index.**

```python
# app/models/db/session.py

from sqlalchemy import Column, Integer, String, UniqueConstraint
from app.core.database import Base

class ActivityTimelineIndex(Base):
    __tablename__ = "activity_timeline_index"

    id = Column(Integer, primary_key=True)

    user_id = Column(String, index=True, nullable=False)

    window_start = Column(DateTime(timezone=True), index=True, nullable=False)
    window_end = Column(DateTime(timezone=True), index=True, nullable=False)

    timezone = Column(String, nullable=False)

    # Foreground authority from OS collector
    foreground_source = Column(String, nullable=False)
    # os | vscode | browser | terminal

    foreground_app = Column(String, nullable=True)

    foreground_window_title = Column(String, nullable=True)

    foreground_category = Column(String, nullable=True)
    # coding | learning | distraction | communication | browsing

    # synchronized raw data availability
    has_os_data = Column(Boolean, default=False)
    has_vscode_data = Column(Boolean, default=False)
    has_browser_data = Column(Boolean, default=False)

    # links/mapping metadata
    vscode_workspace = Column(String, nullable=True)
    browser_domain = Column(String, nullable=True)

    activity_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)

**Why**: The table becomes the canonical foreground activity timeline index used to synchronize OS, browser, and VSCode telemetry windows.

---


### 3.2 Add `lines_added` / `lines_deleted` to `vscode_minute_windows`

```python
# Add to VSCodeMinuteWindowRecord:
lines_added   = Column(Integer, nullable=True, default=0)
lines_deleted = Column(Integer, nullable=True, default=0)
```

## Shared Window Synchronization Standard

All collectors must align telemetry using the same canonical windowing rules.

Rules:
- All timestamps stored in UTC+5:30
- All windows aligned to exact minute boundaries
- All collectors use identical alignment logic
- Local timezone stored separately for UI reconstruction
- OS collector acts as synchronization authority
##
add this to all os, ide, and browser
'''
timeline_index_id = Column(Integer, nullable=True)
'''
These are zero cost to collect now, and are the most important coding velocity metrics for phase 2 AI insights.

---

### 3.3 Add `extra_data` JSON column to all raw tables

```python
# Add to every raw table (os, browser, vscode, calendar):
extra_data = Column(String, nullable=True)  # JSON blob for future extensibility
```

This lets you add new extension fields without a migration until you're ready to promote them to first-class columns.

---

### 3.4 Plan for `DateTime` types (PostgreSQL readiness)

All timestamp columns currently use `Column(String)`. This works in SQLite but breaks when migrating to PostgreSQL for phase 2.

```python
# Current (works in SQLite, breaks in PostgreSQL):
window_start = Column(String, index=True, nullable=False)

# Target (works in both):
from sqlalchemy import DateTime
from datetime import datetime
window_start = Column(DateTime(timezone=True), index=True, nullable=False)
```

Do this as a single Alembic migration before data volume gets large.

## 3.5 Timeline Authority Rules

The OS collector acts as the canonical foreground authority.

Rules:
- If VSCode/browser run in background, their telemetry is stored but excluded from primary productivity calculations.
- The timeline index determines which telemetry source represents the user's true active context.
- Browser and VSCode data are mapped into the timeline index using overlapping time windows.
- Foreground app/window title from the OS collector determines dominant context.
- Dashboard timeline views use the timeline index first, then enrich using raw telemetry.

---

## Part 4 — Backend Code Changes

### 4.1 Replace SQL migration runner with Alembic

```bash
# Install
pip install alembic

# Initialize
alembic init alembic

# Edit alembic/env.py to point to your models:
from app.models.db import *  # imports all ORM models
from app.core.database import Base
target_metadata = Base.metadata

# Create first migration from current models:
alembic revision --autogenerate -m "initial_schema"

# Apply:
alembic upgrade head
```

**Remove from `main.py`:**
```python
# DELETE this entire block:
migration_files = [
    Path(__file__).parent.parent / "scripts" / "migrations" / "006_...",
    ...
]
for migration_sql in migration_files: ...
```

---

### 4.2 Config layer

```python
# app/core/config.py
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./smartdesk.db"
    DEFAULT_USER_ID: str = "local_user"
    CALENDAR_SYNC_INTERVAL_SEC: int = 300
    SESSION_SCHEDULER_INTERVAL_SEC: int = 60
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:1420"]
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
```

---

### 4.3 Logging setup

```python
# app/core/logging.py
import logging
import sys

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

# Usage in any file:
import logging
logger = logging.getLogger("smartdesk.dashboard")
logger.info("Dashboard OS query took %.2fms", elapsed)
```

**Replace every `print()` call in the codebase with the logger.**

---

### 4.4 Dashboard service layer (move logic out of routes)

```python
# app/services/dashboard_service.py
from datetime import datetime
from sqlalchemy.orm import Session
from app.repositories.os_repository import OSRepository
from app.repositories.vscode_repository import VSCodeRepository
from app.repositories.browser_repository import BrowserRepository
from app.models.schemas.dashboard import OSDashboardResponse, IDEDashboardResponse, BrowserDashboardResponse

class DashboardService:
    def __init__(self, db: Session):
        self.os_repo     = OSRepository(db)
        self.vscode_repo = VSCodeRepository(db)
        self.browser_repo = BrowserRepository(db)

    def get_os_summary(self, user_id: str, from_dt: datetime, to_dt: datetime) -> OSDashboardResponse:
        rows = self.os_repo.get_windows_in_range(user_id, from_dt, to_dt)
        return OSDashboardResponse(
            active_time_sec  = sum(r.active_time_sec or 0 for r in rows),
            idle_time_sec    = sum(r.idle_time_sec or 0 for r in rows),
            locked_time_sec  = sum(r.locked_time_sec or 0 for r in rows),
            top_apps         = self._aggregate_app_durations(rows),
            category_breakdown = self._aggregate_category_durations(rows),
        )

    def get_ide_summary(self, user_id: str, from_dt: datetime, to_dt: datetime) -> IDEDashboardResponse:
        rows = self.vscode_repo.get_windows_in_range(user_id, from_dt, to_dt)
        return IDEDashboardResponse(
            coding_time_sec    = sum(r.active_editor_sec or 0 for r in rows),
            idle_sec           = sum(r.idle_sec or 0 for r in rows),
            edits              = sum(r.edit_count or 0 for r in rows),
            saves              = sum(r.save_count or 0 for r in rows),
            terminal_commands  = sum(r.terminal_command_count or 0 for r in rows),
            debug_runs         = sum(r.debug_run_count or 0 for r in rows),
            top_languages      = self._aggregate_by_language(rows),
            top_projects       = self._aggregate_by_workspace(rows),
        )

    def get_browser_summary(self, user_id: str, from_dt: datetime, to_dt: datetime) -> BrowserDashboardResponse:
        rows = self.browser_repo.get_windows_in_range(user_id, from_dt, to_dt)
        return BrowserDashboardResponse(
            browser_active_time_sec  = sum(r.browser_active_time_sec or 0 for r in rows),
            productive_time_sec      = sum(r.productive_time_sec or 0 for r in rows),
            distracting_time_sec     = sum(r.distracting_time_sec or 0 for r in rows),
            neutral_time_sec         = sum(r.neutral_time_sec or 0 for r in rows),
            top_domains              = self._aggregate_by_domain(rows),
        )

    # --- private helpers ---
    def _aggregate_app_durations(self, rows): ...
    def _aggregate_category_durations(self, rows): ...
    def _aggregate_by_language(self, rows): ...
    def _aggregate_by_workspace(self, rows): ...
    def _aggregate_by_domain(self, rows): ...
```

```python
# app/routes/dashboard.py — becomes thin
from fastapi import APIRouter, Depends, Query
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.dashboard_service import DashboardService

router = APIRouter()

def get_dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    return DashboardService(db)

@router.get("/os")
def get_os_panel(
    user_id: str = Query(...),
    from_dt: datetime = Query(..., alias="from"),
    to_dt:   datetime = Query(..., alias="to"),
    svc: DashboardService = Depends(get_dashboard_service),
):
    return svc.get_os_summary(user_id, from_dt, to_dt)

@router.get("/ide")
def get_ide_panel(
    user_id: str = Query(...),
    from_dt: datetime = Query(..., alias="from"),
    to_dt:   datetime = Query(..., alias="to"),
    svc: DashboardService = Depends(get_dashboard_service),
):
    return svc.get_ide_summary(user_id, from_dt, to_dt)

@router.get("/browser")
def get_browser_panel(
    user_id: str = Query(...),
    from_dt: datetime = Query(..., alias="from"),
    to_dt:   datetime = Query(..., alias="to"),
    svc: DashboardService = Depends(get_dashboard_service),
):
    return svc.get_browser_summary(user_id, from_dt, to_dt)
```

---

### 4.5 Ingest routes — stop accepting `created_at` / `updated_at` from clients

```python
# app/routes/ingest/vscode.py
from datetime import datetime, timezone

@router.post("/minute-window")
def ingest_vscode_window(payload: VSCodeWindowIngest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    # Strip client-provided timestamps — set them server-side:
    record = VSCodeMinuteWindowRecord(**payload.dict(), created_at=now, updated_at=now)
    ...
```

---

### 4.6 Dashboard API contract (what the desktop app calls)

```
GET /dashboard/os?user_id=local_user&from=2026-05-06T00:00:00&to=2026-05-06T23:59:59
GET /dashboard/ide?user_id=local_user&from=2026-05-06T00:00:00&to=2026-05-06T23:59:59
GET /dashboard/browser?user_id=local_user&from=2026-05-06T00:00:00&to=2026-05-06T23:59:59
GET /dashboard/sessions?user_id=local_user&from=...&to=...

# Suggested time range helper the desktop app can construct:
# Today:    from = start of today local time,    to = now
# 7 days:   from = 7 days ago 00:00,             to = now
# 30 days:  from = 30 days ago 00:00,            to = now
```

---

## Part 5 — VS Code Extension Changes

### 5.1 Make timezone dynamic (not hardcoded)

```typescript
// REMOVE:
const COLOMBO_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const COLOMBO_TIMEZONE = "Asia/Colombo";

// REPLACE WITH:
function getTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function toLocalISOString(date: Date): string {
    // Use the system timezone offset dynamically
    const offsetMs = -date.getTimezoneOffset() * 60 * 1000;
    const local = new Date(date.getTime() + offsetMs);
    const sign = offsetMs >= 0 ? "+" : "-";
    const absOffset = Math.abs(date.getTimezoneOffset());
    const hh = String(Math.floor(absOffset / 60)).padStart(2, "0");
    const mm = String(absOffset % 60).padStart(2, "0");
    return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

function alignToLocalMinute(ms: number): number {
    const offsetMs = -new Date().getTimezoneOffset() * 60 * 1000;
    const shifted = ms + offsetMs;
    const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
    return aligned - offsetMs;
}
```

---

### 5.2 Read `user_id` and API URL from VS Code settings

```json
// package.json — add to contributes.configuration:
{
  "contributes": {
    "configuration": {
      "title": "SmartDesk",
      "properties": {
        "smartdesk.userId": {
          "type": "string",
          "default": "",
          "description": "Your SmartDesk user ID (leave blank to use machine hostname)"
        },
        "smartdesk.backendUrl": {
          "type": "string",
          "default": "http://localhost:8000",
          "description": "SmartDesk backend URL"
        }
      }
    }
  }
}
```

```typescript
// extension.ts
function getUserId(): string {
    const configured = vscode.workspace.getConfiguration("smartdesk").get("userId");
    if (configured && configured.trim()) return configured.trim();
    return require("os").hostname(); // fallback: machine hostname
}

function getBackendUrl(): string {
    return vscode.workspace.getConfiguration("smartdesk").get("backendUrl") 
        ?? "http://localhost:8000";
}
```

---

### 5.3 Hash `repo_id` — don't send raw git URLs

```typescript
// Replace raw URL with a deterministic hash:
function hashRepoId(remoteUrl: string): string {
    // Simple deterministic hash — no crypto library needed
    let hash = 0;
    for (let i = 0; i < remoteUrl.length; i++) {
        const char = remoteUrl.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // 32-bit int
    }
    return Math.abs(hash).toString(16).padStart(8, "0");
}

// In getGitInfo():
repoId = hashRepoId(urlMatch[1].trim());
```

---

### 5.4 Add `lines_added` / `lines_deleted` tracking

```typescript
// In MinuteWindowCounters type:
type MinuteWindowCounters = {
    // ... existing fields ...
    lines_added: number;
    lines_deleted: number;
};

// In createEmptyCounters():
lines_added: 0,
lines_deleted: 0,

// In the onDidChangeTextDocument listener:
const editTracking = vscode.workspace.onDidChangeTextDocument(e => {
    if (e.contentChanges.length === 0) return;
    if (vscode.window.activeTextEditor?.document !== e.document) return;

    // Count logical edits (not contentChanges.length which overcounts auto-format)
    let added = 0;
    let deleted = 0;
    for (const change of e.contentChanges) {
        const newLines = change.text.split("\n").length - 1;
        const oldLines = change.range.end.line - change.range.start.line;
        added += Math.max(0, newLines - oldLines);
        deleted += Math.max(0, oldLines - newLines);
    }
    counters.lines_added += added;
    counters.lines_deleted += deleted;
    // Use 1 for edit_count (one save event = one logical edit action)
    counters.edit_count += 1;
    lastActivityMs = Date.now();
});
```

---

### 5.5 Add offline buffering (don't lose data if backend is down)

```typescript
// Simple in-memory buffer — queues failed windows for retry next cycle
const pendingQueue: VSCodeMinuteWindowPayload[] = [];

async function sendMinuteWindow(payload: VSCodeMinuteWindowPayload): Promise {
    const toSend = [...pendingQueue, payload];
    pendingQueue.length = 0;

    for (const p of toSend) {
        try {
            const res = await fetch(`${getBackendUrl()}/api/v1/vscode/minute-window`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(p)
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (error) {
            output.appendLine(`[SmartDesk] Send failed, queued for retry: ${error}`);
            pendingQueue.push(p); // re-queue for next minute
        }
    }
}
```

---

### 5.6 Remove `created_at` / `updated_at` / `schema_version` from the payload type

These should be set by the backend. Remove from `VSCodeMinuteWindowPayload` and from `buildPayload()`.

---

## Part 6 — Browser Extension Changes

### 6.1 Make timezone dynamic

```javascript
// REMOVE:
const COLOMBO_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const COLOMBO_TIMEZONE = "Asia/Colombo";

// REPLACE WITH:
function getTimezone() {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function toLocalISOString(date) {
    const offsetMs = -date.getTimezoneOffset() * 60 * 1000;
    const local = new Date(date.getTime() + offsetMs);
    const sign = offsetMs >= 0 ? "+" : "-";
    const absOffset = Math.abs(date.getTimezoneOffset());
    const hh = String(Math.floor(absOffset / 60)).padStart(2, "0");
    const mm = String(absOffset % 60).padStart(2, "0");
    return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

function alignToLocalMinute(ms) {
    const offsetMs = -new Date().getTimezoneOffset() * 60 * 1000;
    const shifted = ms + offsetMs;
    const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
    return aligned - offsetMs;
}
```

---

### 6.2 Read `user_id` and `backendUrl` from storage (not hardcoded)

```javascript
// REMOVE:
const USER_ID = "demo_user";

// REPLACE WITH — read from chrome.storage.sync (configurable via options page):
async function getConfig() {
    return new Promise((resolve) => {
        chrome.storage.sync.get({
            userId: "",
            backendUrl: "http://127.0.0.1:8000"
        }, (config) => {
            // Fallback to hostname if userId not set (via content script or set during install)
            resolve(config);
        });
    });
}
```

Add an options page (`options.html` + `options.js`) where the developer enters their user ID and backend port on first install.

---

### 6.3 Fix `getBrowserName()` — use extension API instead of user agent

```javascript
// REMOVE:
function getBrowserName() {
    const ua = (navigator.userAgent || "").toLowerCase();
    if (ua.includes("edg")) return "Edge";
    ...
}

// REPLACE WITH:
function getBrowserName() {
    // chrome.runtime.getURL returns "chrome-extension://" in Chrome and Edge
    // navigator.userAgent is always Chrome in Edge's service worker
    // Use the extension's browser API instead:
    if (typeof browser !== "undefined") return "Firefox";
    if (navigator.userAgent.toLowerCase().includes("edg/")) return "Edge";
    return "Chrome";
}
```

---

### 6.4 Fix tab switch count logic

```javascript
// CURRENT (wrong — counts the first entry of each window as a switch):
if (entryStartMs >= windowStartMs && entryStartMs < windowEndMs) {
    tabSwitchCount += 1;
}

// FIX — only count switches after the first entry:
let isFirstEntry = true;
for (const entry of history) {
    ...
    if (!isFirstEntry && entryStartMs >= windowStartMs && entryStartMs < windowEndMs) {
        tabSwitchCount += 1;
    }
    isFirstEntry = false;
}
```

---

### 6.5 Add history size guard — prevent unbounded growth

```javascript
const MAX_HISTORY_ENTRIES = 500; // ~8 hours of 1-per-minute entries with buffer

function pruneHistory(history, windowEndMs) {
    // First remove old entries
    const timeFiltered = history.filter((entry) => {
        if (!entry.endTime) return true;
        const endMs = Date.parse(entry.endTime);
        return isNaN(endMs) || endMs > windowEndMs;
    });
    // Then enforce hard cap
    if (timeFiltered.length > MAX_HISTORY_ENTRIES) {
        return timeFiltered.slice(timeFiltered.length - MAX_HISTORY_ENTRIES);
    }
    return timeFiltered;
}
```

---

### 6.6 Improve category classification — add a developer allowlist

```javascript
// Add a third tier: dev-on-distraction-domain overrides
// e.g. reddit.com/r/programming should be Focused, not Distracted

const devSubreddits = ["programming", "learnprogramming", "webdev", "javascript", 
                        "python", "devops", "MachineLearning", "cscareerquestions"];

function classifyTab(tab) {
    if (!tab.url) return "Neutral";
    const text = (tab.url + " " + (tab.title || "")).toLowerCase();

    // Priority 1: Educational content always wins
    for (const word of educationalKeywords) {
        if (text.includes(word)) return "Focused";
    }

    // Priority 2: Dev subreddits on Reddit are Focused
    if (text.includes("reddit.com")) {
        for (const sub of devSubreddits) {
            if (text.includes(`/r/${sub.toLowerCase()}`)) return "Focused";
        }
    }

    // Priority 3: Distracted domains
    for (const word of distractedDomains) {
        if (text.includes(word)) return "Distracted";
    }

    // Priority 4: Focused developer domains
    for (const word of focusedDomains) {
        if (text.includes(word)) return "Focused";
    }

    return "Neutral";
}
```

---

### 6.7 Update `manifest.json`

```json
{
  "manifest_version": 3,
  "name": "SmartDesk Tracker",
  "version": "1.0.0",
  "description": "Tracks browser activity for SmartDesk developer productivity dashboard",
  "permissions": [
    "tabs",
    "storage",
    "idle",
    "alarms"
  ],
  "host_permissions": [
    "http://127.0.0.1/*",
    "http://localhost/*"
  ],
  "options_page": "options.html",
  "background": {
    "service_worker": "background.js"
  }
}
```

Key changes: renamed, removed `downloads` permission (unused), narrowed `host_permissions` to only localhost, added `options_page`.

---

### 6.8 Remove `created_at` / `updated_at` / `schema_version` from payload

Same as VS Code extension — the backend sets these.

---

## Part 7 — Implementation Order (Priority)

Execute in this exact sequence to avoid breaking a working system:

```
Phase A — Foundation (do first, nothing breaks)
  1. Add Alembic, create first migration from current models
  2. Add app/core/config.py with pydantic-settings
  3. Add app/core/logging.py, replace all print() calls
  4. Split models/ into models/db/ and models/schemas/

Phase B — Database (migration, data preserved)
  5. Redesign activity_session_summary to lean session index (new Alembic migration)
  6. Add lines_added / lines_deleted to vscode_minute_windows
  7. Add extra_data JSON column to all raw tables

Phase C — Backend logic (no API contract change yet)
  8. Create DashboardService, move all aggregation logic out of dashboard.py
  9. Fix ingest routes — strip created_at / updated_at from client payloads
  10. Tighten CORS to use settings.CORS_ORIGINS

Phase D — Extensions (update both, deploy together)
  11. VS Code: dynamic timezone, hashed repo_id, VS Code settings for userId/backendUrl
  12. VS Code: fix edit_count logic, add lines_added/lines_deleted, add offline buffer
  13. Browser: dynamic timezone, config via options page, fix tab switch count
  14. Browser: fix getBrowserName(), add history size guard, update manifest

Phase E — API contract (desktop app can now consume)
  15. Implement GET /dashboard/os, /dashboard/ide, /dashboard/browser endpoints
  16. Implement GET /dashboard/sessions endpoint

Phase F — Tests
  17. Unit tests for DashboardService aggregation logic
  18. Unit tests for session scheduler
  19. Integration test for each ingest endpoint
```

---

## Part 8 — Phase 2 Readiness Checklist

These decisions made during the MVP prevent expensive rewrites later:

| Decision | Do Now | Why |
|----------|--------|-----|
| Use `extra_data` JSON column on all tables | ✅ Phase B | New extension fields won't require migrations |
| Hash `repo_id` — never store raw git URLs | ✅ Phase D | Consistent identifier across installs for AI correlation |
| `user_id` as `os.hostname()` fallback | ✅ Phase D | Stable per-machine ID without auth system |
| Separate `ai_insights` table for generated content | Plan now | Keep raw data clean, AI output auditable and regeneratable |
| `DateTime(timezone=True)` types | Plan now | PostgreSQL migration won't require data re-import |
| `DashboardService` as a class | ✅ Phase C | AI service can call the same service layer without touching routes |
| Options page in browser extension | ✅ Phase D | Users can point extension at cloud backend in phase 2 with zero extension update |

---

## Part 9 — Full API Response Schemas (for desktop app)

```python
# app/models/schemas/dashboard.py

from pydantic import BaseModel
from typing import List

class AppUsage(BaseModel):
    name: str
    seconds: int

class CategoryUsage(BaseModel):
    category: str
    seconds: int

class OSDashboardResponse(BaseModel):
    active_time_sec: int
    idle_time_sec: int
    locked_time_sec: int
    top_apps: List[AppUsage]           # sorted by seconds desc, top 10
    category_breakdown: List[CategoryUsage]

class IDEDashboardResponse(BaseModel):
    coding_time_sec: int
    idle_sec: int
    edits: int
    saves: int
    terminal_commands: int
    debug_runs: int
    lines_added: int
    lines_deleted: int
    top_languages: List[AppUsage]      # reuse AppUsage shape {name, seconds}
    top_projects: List[AppUsage]       # workspace_name + total active_editor_sec

class BrowserDashboardResponse(BaseModel):
    browser_active_time_sec: int
    productive_time_sec: int
    distracting_time_sec: int
    neutral_time_sec: int
    top_domains: List[AppUsage]        # domain + seconds

class SessionEntry(BaseModel):
    session_start: str
    session_end: str
    duration_sec: int
    primary_source: str | None
    has_os: bool
    has_vscode: bool
    has_browser: bool
    has_calendar: bool

class SessionsResponse(BaseModel):
    sessions: List[SessionEntry]
```
## 10. CHANGES
Rename:
activity_session_summary
TO:
activity_timeline_index

---

*End of plan — 9 parts, 30+ specific changes, prioritized in execution order.*
Done