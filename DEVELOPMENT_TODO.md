# SmartDesk Development TODO

This checklist follows `plan.md` but keeps each phase manually testable.

## Phase 0 - Baseline

- [x] FastAPI app starts.
- [x] `/` returns foundation status.
- [x] `/health/` returns `ok`.
- [x] Old minute-window collectors and APIs removed.

Manual check:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/health/
```

## Phase 1 - Architecture Skeleton

- [x] Add `app/repositories/`.
- [x] Add `app/services/`.
- [x] Add `app/routes/ingest.py`.
- [x] Add `app/routes/dashboard.py`.
- [x] Wire skeleton routers into `app/main.py`.
- [x] Add status endpoints for manual route checks.

Manual check:

```text
http://127.0.0.1:8000/api/v1/ingest/status
http://127.0.0.1:8000/dashboard/status
```

## Phase 2 - New Database Schema

- [x] Add Alembic.
- [x] Add `os_sessions` model and migration.
- [x] Add `vscode_sessions` model and migration.
- [x] Add `browser_sessions` model and migration.
- [x] Add `calendar_events` model and migration.
- [x] Add `work_periods` model and migration.

Manual check:

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./phase2_schema_test.db"
python -m alembic upgrade head
```

Inspect SQLite and confirm these tables exist:

- `alembic_version`
- `os_sessions`
- `vscode_sessions`
- `browser_sessions`
- `calendar_events`
- `work_periods`

## Phase 3 - Event Schemas

- [x] Add OS event request schema.
- [x] Add VS Code event request schema.
- [x] Add browser event request schema.
- [x] Add dashboard response schemas.

Manual check:

```powershell
cd backend
python -m compileall app
```

Validate sample payloads in Python and confirm:

- valid OS, VS Code, and browser payloads parse
- invalid event names are rejected
- dashboard response defaults serialize cleanly

## Phase 4 - Ingest Route Validation

- [x] Add `POST /api/v1/ingest/os/event`.
- [x] Add `POST /api/v1/ingest/vscode/event`.
- [x] Add `POST /api/v1/ingest/browser/event`.
- [x] Return validation-only responses before adding DB writes.

Manual check:

- Use `docs/manual-tests/phase4-ingest-validation.md`.
- Send valid and invalid sample payloads.
- Confirm bad payloads fail with useful validation errors.

## Phase 5 - Session Coordinator

- [x] Implement OS session open/close.
- [x] Implement VS Code session open/close.
- [x] Implement browser session open/close.
- [x] Calculate `duration_sec` on close.
- [x] Track `closed_by`.

Manual check:

- Use `docs/manual-tests/phase5-session-lifecycle.md`.
- Send two focus events.
- Confirm first session closes and second session remains open.
- Send VS Code and browser events.
- Confirm durations and counters are stored.

## Phase 6 - Foreground Matching

- [x] Match VS Code sessions to OS foreground PID.
- [x] Match browser sessions to OS foreground PID when available.
- [x] Update `is_foreground` and `confirmed_by_os`.

> Implemented inside `app/services/session_coordinator.py` via `_is_foreground()` and `_update_foreground_flags()`.

Manual check:

- Send OS and detail-provider events with matching PIDs.
- Confirm foreground flags update in `vscode_sessions` and `browser_sessions`.

## Phase 7 - Safety Timeout

- [x] Add `app/services/session_timeout_job.py` with `SessionTimeoutJob` class.
- [x] Implement `run_once()` manual trigger for testing without background thread.
- [x] Add background thread via `threading.Timer`.
- [x] Wire job into `app/main.py` lifespan startup/shutdown.

Manual check:

```powershell
# Create a stale open session (or patch BROKEN_SESSION_TIMEOUT_SEC to 1 min).
# Call run_once() or wait for background tick.
# Confirm closed_by="timeout" and duration_sec are set.
```

## Phase 8 - Work Periods

- [x] Add `app/repositories/work_period_repository.py` with open/close/flag helpers.
- [x] Build `app/services/work_period_scheduler.py` with `WorkPeriodScheduler` class.
- [x] Store `has_os_data`, `has_vscode_data`, `has_browser_data`, `has_calendar_data` flags.
- [x] Determine `primary_source` by total `duration_sec` per source.
- [x] Wire scheduler into `app/main.py` lifespan startup/shutdown.

Manual check:

```powershell
# Seed session rows.
# Trigger scheduler.run_once() via debug endpoint or directly.
# Confirm work_periods rows appear with correct source flags.
```

## Phase 9 - Dashboard API

- [x] Add `app/repositories/os_session_repository.py`.
- [x] Add `app/repositories/vscode_session_repository.py`.
- [x] Add `app/repositories/browser_session_repository.py`.
- [x] Add `app/repositories/work_period_repository.py`.
- [x] Add `app/services/dashboard_service.py` with full aggregation logic.
- [x] Replace dashboard stub with real endpoints in `app/routes/dashboard.py`.
- [x] `GET /dashboard/os` — active/idle/locked time, top apps, category breakdown.
- [x] `GET /dashboard/ide` — coding time, edits, saves, lines, top languages & projects.
- [x] `GET /dashboard/browser` — productive/distracted/neutral time, top domains.
- [x] `GET /dashboard/timeline` — work periods with source flags.
- [x] `GET /dashboard/sessions` — flat chronological session list across all sources.

Manual check:

```text
http://127.0.0.1:8000/dashboard/os?user_id=local_user
http://127.0.0.1:8000/dashboard/ide?user_id=local_user
http://127.0.0.1:8000/dashboard/browser?user_id=local_user
http://127.0.0.1:8000/dashboard/timeline?user_id=local_user
http://127.0.0.1:8000/dashboard/sessions?user_id=local_user
```

Confirm:
- Empty responses (not errors) when no data is present.
- Seeded data produces correct totals.
- Use `/docs` for interactive Swagger testing.

## Phase 10 - Real Collectors

- [x] Add `app/services/os_collector.py` — Windows foreground monitor (psutil + ctypes).
  - Auto-starts with backend inside a daemon thread (no separate terminal needed).
  - Detects: app switch, idle_start/end, locked/unlocked, shutdown.
  - Updated IDE classifier: Code, Cursor, Windsurf, Zed, all JetBrains, Vim, Emacs, Xcode.
- [x] Build VS Code extension — `vscode-extension/extension.js`.
  - Tracks: file edits, saves, lines, file switches, terminal opens, debug runs, idle.
  - Events: `started` / `ended` posted to `/api/v1/ingest/vscode/event`.
  - Installed as VSIX: `smartdesk-vscode-2.0.0.vsix`.
  - Old `smartdesk.smartdesk-ide-logger` extension uninstalled.
- [x] Build browser extension — `browser-extension/background.js`.
  - Manifest V3 service worker for Chrome / Edge / Brave.
  - Tracks: tab switches, URL changes, window focus, 30s heartbeats.
  - Domain categories: Focused / Distracted / Communication / Neutral.
  - Events: `started` / `ended` / `state` posted to `/api/v1/ingest/browser/event`.
  - Load via `chrome://extensions/` → Developer mode → Load unpacked.
- [x] Add offline retry queue to both extensions (max 50 events, auto-flush on reconnect).
- [x] Add legacy shim (`app/routes/legacy.py`) — old minute-window endpoints return 410 Gone.
- [x] Suppress 410/legacy log spam via `uvicorn.access` log filter.

Manual check:

```powershell
# Single command — backend + OS collector start together
python -m uvicorn app.main:app --reload
```

- Switch apps → `os_sessions` rows appear.
- Edit files in VS Code → `vscode_sessions` rows appear.
- Switch tabs in browser → `browser_sessions` rows appear.
- See `docs/e2e-test-guide.md` for the full structured test plan.

## Phase 11 - Tests

- [x] Created `docs/e2e-test-guide.md` — 10-test manual E2E guide covering all components.
- [x] Add `tests/` directory with `pytest` setup (`conftest.py` with file-based test DB).
- [x] Unit test `SessionCoordinator` (open, close, PID matching, idle state, shutdown) — 12 tests.
- [x] Unit test `SessionTimeoutJob.run_once()` (stale close, fresh skip, multi-source, already-closed) — 4 tests.
- [x] Unit test `DashboardService` aggregation with known seed data — via integration tests.
- [x] Integration test all ingest endpoints via `TestClient` — 16 tests.
- [x] Integration test all dashboard endpoints via `TestClient` — 11 tests.

**Result: 51/51 tests passing ✅**

```powershell
cd backend
Remove-Item test_smartdesk.db -Force -ErrorAction SilentlyContinue
python -m pytest tests/ -v
```
