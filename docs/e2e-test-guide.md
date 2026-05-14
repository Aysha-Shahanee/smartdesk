# SmartDesk End-to-End Test Guide

Run these tests in order after a fresh backend startup with a clean database.

## Prerequisites

```powershell
# 1. Clean DB and start backend
cd backend
Remove-Item smartdesk.db -Force -ErrorAction SilentlyContinue
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

Expected startup log:
```
SmartDesk backend started.
SessionTimeoutJob started (interval=60s, timeout=1800s).
WorkPeriodScheduler started (interval=60s, idle_gap=1800s).
OSCollector started in background thread.
Application startup complete.
```

---

## Test 1 — Health & Status

```powershell
# All should return 200
Invoke-WebRequest http://127.0.0.1:8000/           -UseBasicParsing | Select StatusCode
Invoke-WebRequest http://127.0.0.1:8000/health/    -UseBasicParsing | Select StatusCode
Invoke-WebRequest http://127.0.0.1:8000/api/v1/ingest/status -UseBasicParsing | Select StatusCode
Invoke-WebRequest http://127.0.0.1:8000/dashboard/status     -UseBasicParsing | Select StatusCode
```

**Expected root response:**
```json
{
  "service": "SmartDesk Session Backend",
  "status": "running",
  "background_jobs": ["session_timeout_job", "work_period_scheduler", "os_collector"]
}
```

---

## Test 2 — OS Collector (automatic)

OS events are sent automatically every second by the embedded OS collector.

**Check after 5 seconds:**

```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/sessions" -UseBasicParsing | Select Content
```

**Expected:** `os_sessions` rows appear with your current foreground app.

```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/os" -UseBasicParsing | Select Content
```

**Expected:** `active_time_sec > 0`, `top_apps` shows your current app.

---

## Test 3 — OS Ingest (manual curl)

```powershell
$body = '{"user_id":"local_user","event":"focused","timestamp":"2026-05-12T10:00:00Z","app_name":"TestApp","app_category":"Other","process_id":9999}'
Invoke-WebRequest http://127.0.0.1:8000/api/v1/ingest/os/event -Method POST -Body $body -ContentType "application/json" -UseBasicParsing | Select Content
```

**Expected:**
```json
{"status": "open", "session_id": "...", "accepted": true}
```

---

## Test 4 — VS Code Extension

1. Open VS Code (with SmartDesk extension installed)
2. Open any file
3. Make a few edits and save

**Check:**
```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/sessions" -UseBasicParsing | Select Content
```

**Expected:** `vscode_sessions` rows with `source: "vscode"`, non-zero `edit_count`, correct `active_language`.

**Check IDE dashboard:**
```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/ide" -UseBasicParsing | Select Content
```

**Expected:** `coding_time_sec > 0`, `edits > 0`, `top_languages` shows your language.

---

## Test 5 — Browser Extension

1. Open Chrome (with SmartDesk extension loaded)
2. Navigate to `github.com` — stay 5+ seconds
3. Navigate to `youtube.com` — stay 5+ seconds
4. Navigate to `slack.com` — stay 5+ seconds

**Check:**
```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/browser" -UseBasicParsing | Select Content
```

**Expected:**
- `browser_active_time_sec > 0`
- `productive_time_sec > 0` (github = Focused)
- `distracting_time_sec > 0` (youtube = Distracted)
- `communication_time_sec > 0` (slack = Communication)
- `top_domains` shows `github.com`, `youtube.com`, `slack.com`

---

## Test 6 — Work Period Scheduler

Wait ~60 seconds after activity, then:

```powershell
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/timeline" -UseBasicParsing | Select Content
```

**Expected:**
```json
{
  "work_periods": [
    {
      "has_os_data": true,
      "has_vscode_data": true,
      "has_browser_data": true,
      "primary_source": "os"
    }
  ]
}
```

---

## Test 7 — Session Timeout

1. Open SQLite and manually create a stale open session:

```python
# Run from backend/
import sqlite3, datetime
conn = sqlite3.connect("smartdesk.db")
stale_time = (datetime.datetime.utcnow() - datetime.timedelta(minutes=35)).isoformat()
conn.execute("""
  INSERT INTO os_sessions (id, user_id, app_name, state, is_idle, is_locked,
    session_start, closed_by, created_at, updated_at)
  VALUES ('stale-test-001', 'local_user', 'FakeApp', 'active', 0, 0,
    ?, NULL, ?, ?)
""", (stale_time, stale_time, stale_time))
conn.commit(); conn.close()
```

2. Wait up to 60 seconds for the timeout job to run.

**Expected log:**
```
SessionTimeoutJob closed 1 stale session(s).
```

**Expected in DB:** `closed_by = "timeout"`, `session_end` is set.

---

## Test 8 — Legacy Endpoint (Old Extension Compatibility)

Old extensions hitting deprecated endpoints should get 410, not 404:

```powershell
try {
    Invoke-WebRequest http://127.0.0.1:8000/api/v1/ide/minute-window -Method POST -Body '{}' -ContentType "application/json" -UseBasicParsing
} catch {
    Write-Host "Status: $($_.Exception.Response.StatusCode.value__)"
}
```

**Expected:** `Status: 410`  
**Expected:** This request does NOT appear in the server log (filtered out).

---

## Test 9 — Dashboard Date Range

```powershell
$from = "2026-05-12T00:00:00Z"
$to   = "2026-05-12T23:59:59Z"
Invoke-WebRequest "http://127.0.0.1:8000/dashboard/os?from=$from&to=$to" -UseBasicParsing | Select Content
```

**Expected:** Valid response with time-filtered data, no 422 errors.

---

## Test 10 — Graceful Shutdown

Stop the backend with `Ctrl+C`.

**Expected log:**
```
OSCollector stopped.
SessionTimeoutJob stopped.
WorkPeriodScheduler stopped.
SmartDesk backend stopped.
```

**Check DB:** Any open `os_sessions` for `local_user` should now have `session_end` set (from the shutdown event POSTed by the OS collector before stopping).

---

## Quick Summary Checklist

| Test | Component | Pass Condition |
|---|---|---|
| 1 | Health endpoints | All 200 OK |
| 2 | OS Collector auto | `os_sessions` rows appear within 5s |
| 3 | OS Ingest manual | Returns `session_id` |
| 4 | VS Code Extension | `vscode_sessions` rows, non-zero counters |
| 5 | Browser Extension | All 3 categories populated |
| 6 | Work Period Scheduler | `work_periods` row with source flags |
| 7 | Session Timeout | Stale session closed with `closed_by=timeout` |
| 8 | Legacy Shim | 410 Gone, no log spam |
| 9 | Date Range Query | Filtered results, no errors |
| 10 | Graceful Shutdown | All jobs log "stopped" |
