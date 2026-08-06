# SmartDesk Recent Changes — Team Guide

Read this before pulling. This round is bigger than the last one: it changes how
**time is measured**, so the numbers you see in the app will move — mostly
downward — and there are **two new migrations you must run**.

Branch: `dev`

---

## ⚠️ Read this first — your totals are going to drop

Before this change, the backend recorded **177.6 hours** of OS activity for
2026-07-21..28. About **123 of those hours never happened.** After pulling and
migrating you will see roughly **81 hours** for the same week.

Nothing was deleted from your real activity. The app was inventing time, and it
has stopped. Two separate causes, both fixed below:

- Sessions were closed at whatever moment the backend *noticed* them. If the
  process was not running — laptop asleep, backend restarted, machine off — the
  entire outage got billed to whichever window happened to be in front. One
  recorded block was **17.89 hours of "active" VS Code spanning a night** in
  which not a single row was written to any table.
- Every segment was marked `state = 'active'` regardless of what the OS session
  actually said. **47.8 of 81.5 hours** was time at an unattended machine
  counted as work.

If you have been quoting SmartDesk numbers anywhere, re-check them after
migrating.

---

## 🔧 What changed

### 1. Observer liveness — sessions can only claim time we were watching

**New:** `backend/app/services/liveness.py`,
`backend/app/models/db/service_heartbeat.py`, migration `0009`

The backend now records that it is alive. `SessionTimeoutJob` stamps a
single-row `service_heartbeat` table every tick (60 s), so a frozen heartbeat
marks the exact moment the observer stopped.

- `clamp_to_liveness()` refuses to stamp a session end more than 150 s past the
  last heartbeat. Grace exceeds the beat interval so live sessions are never
  truncated between beats.
- Clamped rows get `closed_by = 'recovered'` instead of `'timeout'`, so repaired
  rows stay identifiable afterwards.
- **Startup reconciliation** (`backend/app/main.py` lifespan) closes sessions
  orphaned by a previous process *before* the collector runs. This ordering
  matters: the collector's first tick always emits `focused`, which would close
  those sessions at *now* and bill the whole downtime as activity. The timeout
  job can't do it either — it fires on a 60 s timer and loses the race.
- Applied in `session_coordinator.py` (catches suspend/resume, where the process
  freezes and never restarts) and `session_timeout_job.py`.

### 2. Migration `0010` — repairs the history already in your database

Migration `0009` creates the heartbeat table. `0010` retroactively bounds every
existing session by evidence the observer was running: the `created_at` /
`updated_at` stamps written by *other* session rows.

- Only spans over 5 minutes are considered — anything shorter can't be
  meaningfully wrong.
- Grace is a deliberately generous 30 minutes (matching
  `BROKEN_SESSION_TIMEOUT_SEC`). A genuine focus block writes no events at all —
  typing in one window for 20 minutes produces no window switches and no idle
  transitions — so a tight grace would delete exactly the real work this is
  meant to protect. Up to 30 min of each outage survives; that's the right way
  to be wrong.
- **Original values are preserved in `extra_data.span_repair`.** The change is
  auditable and reversible.

### 3. Activity segment builder — substantially rewritten

`backend/app/services/activity_segment_builder.py`

- **Sessions are now loaded by overlap, not by start time.**
  (`os_session_repository.get_sessions_overlapping_db`.) The old query only saw
  a session in the single 5-minute build window containing its *start* — at
  which point it was still open, so the `session_end IS NOT NULL` filter dropped
  it. By the time it closed, no window contained its start any more. Net effect:
  **every one of the 2,899 segments ever built came from a session under 4.5
  minutes.** The longer you focused on something, the more certain it was to be
  thrown away.
- **Watermark-based ticks.** Each tick resumes from the furthest point already
  covered instead of always processing `[now − 5 min, now]`, so any gap in the
  builder's own uptime is no longer a permanent hole. Capped at 6 h of catch-up
  per tick.
- **`_determine_state()` reads the real OS session state** (attributed to
  whichever session covers most of the segment) instead of returning `"active"`
  unconditionally. `'idle'` had never once been written to the table despite the
  schema allowing it since migration `0006`.
- **Gap segments are off** (`EMIT_GAP_SEGMENTS = False`). Synthesising a row for
  every uncovered window made the timeline read a continuous 24 h/day — 108.3 h
  of synthetic gap against 81.8 h of real coverage. Absence of a row now means
  "no data"; idle time is represented properly as `state='idle'` on a real row.
- **Segments are cut at 15 minutes** so one long focus block becomes a run of
  bounded rows.
- **Fixed an inverted ternary** in `_calculate_safe_processing_end()` that always
  returned `local_now_iso()`, discarding both the caller's end time and the
  arrival-delay guard it had just computed.
- **New `backfill()` method** to reprocess history in chunks — see step 5 below.

### 4. Categorizer — one bad label no longer discards a whole batch

`backend/app/services/categorizer.py`

`CATEGORY_KEYWORDS` and `LABEL_TEXTS` carried a `documentation` label that
`ck_activity_segments_category` has never allowed. Segments are persisted in one
batch, so **a single segment scoring highest on it failed the INSERT and
discarded every segment in that build window.** Predictions are now filtered to
`PERSISTABLE_CATEGORIES`, so a taxonomy that drifts ahead of the schema degrades
one label instead of losing the batch.

### 5. Dashboard API — two changes, one of them breaking-ish

`backend/app/routes/dashboard.py`

- `/dashboard/segments/summary` now filters `state = 'active'`. Idle segments
  carry a category too, so without this the breakdown counted unattended time as
  work.
- `/dashboard/segments` gained six **additive** fields:
  `duration_sec`, `state`, `primary_source`, `has_ide_session`,
  `has_browser_session`, `has_os_session`.

  The desktop UI needs these to tell an IDE segment from a browser one. Without
  them it had to guess by substring-matching `app_name`. **You must restart the
  API server** for these to be served — the Timeline detects their absence and
  shows an explicit warning rather than rendering empty tabs.

### 6. Frontend — 21 defects fixed, full audit in `FRONTEND_LOGIC.md`

**New file: `FRONTEND_LOGIC.md`** documents how every number and chart in the
desktop UI is produced, which endpoint it comes from, and which figures are
still placeholders. Read it if you touch the renderer.

Highlights:

- **Browser tab was 99.3 % empty** — keyword matching on `app_name` found 4 of
  562 browser segments, and **736 non-IDE segments were shown as IDE** because
  `'code'` matched unrelated window titles. Tabs now route on `primary_source`.
- **Calendar tab was always empty on every date** — `from = to = <date>`
  collapsed the query window to a single instant at midnight.
- **Up to 200 segments per day were silently dropped** — one request with
  `limit=500` truncated days holding 700 rows. Now paginates fully.
- **Day windows were shifted by the UTC offset**, and the app opened on
  yesterday's data between midnight and 05:30 local.
- **"Idle Time" was invented arithmetic** (`8h − active_time`, an assumed
  workday). Now sums real idle segments.
- **Activity outside 09:00–17:00 was discarded** by the hourly chart — 42 % of a
  typical day.
- New `theme/chartTheme.ts` (colour-blindness-validated palette, light + dark)
  and `utils/time.ts` (canonical timestamp parsing — the API field is named
  `start_time_utc` but holds **naive local wall time**).
- **Insights, Prediction and Recommendations are placeholders** and now say so
  via `SampleDataBanner`. Nothing in the backend produces focus scores, stress
  levels, emotion mixes or task predictions. Don't demo them as real.

### 7. Electron entry point fix

`frontend/package.json` had `"main": "src/main.ts"` — pointing Electron at the
TypeScript *source*. electron-vite compiles to `out/main/main.js`, but Electron
loaded the `.ts` file as CommonJS and died with
`SyntaxError: Cannot use import statement outside a module`.

Fixed to `"main": "out/main/main.js"`. `frontend/src/main.ts` also had its
preload path corrected (`../preload/preload.js`, not `../preload.js`) — the
bridge had been silently disabled.

**If `npm run dev` was crashing on startup for you, this is why.**

---

## 📋 What you need to do

### 1. Pull

```bash
git pull origin dev
```

### 2. Back up your database (recommended)

Migration `0010` rewrites historical session rows. Originals are kept in
`extra_data.span_repair`, but a file copy is cheaper than trusting that.

```bash
cd backend
copy smartdesk.db smartdesk.db.bak
```

### 3. Run the migrations — **required**

Two new revisions (`0009`, `0010`). The app will not behave correctly without
them; `service_heartbeat` won't exist and every session close will fail.

```bash
cd backend
.\venv\Scripts\python.exe -m alembic upgrade head
```

### 4. Restart the backend — **required**

Not optional this time. The new `/dashboard/segments` fields only appear after a
restart, and the desktop UI will show a warning banner until they do.

```bash
.\venv\Scripts\python.exe -m uvicorn app.main:app
```

Watch the startup log for the reconciliation line — it tells you how many
sessions the previous process left open.

### 5. Optional — rebuild historical segments

Migration `0010` repairs the *session* tables. It does not rebuild
`activity_segments`, which were derived from the old broken spans and from the
<4.5-minute selection bug. If you want your history to reflect the fixed logic,
run a backfill. There is no CLI or endpoint yet — call it directly:

```bash
cd backend
.\venv\Scripts\python.exe -c "from app.services.activity_segment_builder import ActivitySegmentBuilder; from app.core.config import settings; b = ActivitySegmentBuilder(user_id=settings.DEFAULT_USER_ID, device_id=settings.DEVICE_ID); print(b.backfill('2026-07-01T00:00:00+05:30', '2026-08-01T00:00:00+05:30'))"
```

It works in 1-hour chunks, each its own transaction, and prints a summary. It
**purges and rebuilds** segments in the range — necessary because rebuilt
boundaries move once clipping and length-splitting apply, so without a purge old
rows would survive alongside new ones and the range would double-count. Your
manual corrections are preserved: labels are anchored to a timestamp before the
purge and re-pointed at whichever rebuilt segment covers them. The summary
reports `labels_relinked` and `labels_lost` — check that `labels_lost` is 0.

Adjust the date range to whatever history you care about.

### 6. Frontend

No dependency changes — `npm install` is not needed. Just:

```bash
cd frontend
npm run dev
```

The Electron window should open. If you still get
`Cannot use import statement outside a module`, your `package.json` didn't
update — check the `main` field reads `out/main/main.js`.

### 7. Verify

- Dashboard totals are **lower** than before and no longer show impossible
  overnight blocks.
- Timeline → Browser tab actually has content in it.
- Timeline → Calendar tab shows events (it used to be empty on every date).
- Insights / Prediction / Recommendations show the yellow "Sample data" banner.
- No warning banner about missing segment fields — if you see one, the backend
  wasn't restarted.

---

## 🗒️ Notes for whoever picks this up next

- `/dashboard/browser` **double-counts by ~1.4×** because concurrent tabs are
  each recorded as foreground — on 2026-07-25 it reports 15.2 h of browsing on a
  day with 6.2 h of total OS activity. The UI now avoids it for time totals.
  Fixing the collector or the aggregation is a backend change and was left
  alone deliberately.
- `backfill()` has no CLI or endpoint. Worth adding one.
- Pre-existing `tsc` errors in `preload.ts` / `api.ts` (`import.meta` under a
  CommonJS `module` setting) are unrelated to this work and predate it.
  `electron-vite build` succeeds regardless.

---

<details>
<summary><b>Previous round (already merged) — dashboard display fix</b></summary>

### Dashboard fix (`backend/app/static/dashboard.html`)
- Fixed JavaScript syntax error: `'Synced!"` → `'Synced!'` (mismatched quotes)
- Added missing event listeners for Google Calendar Connect and Sync buttons
- Changed Chart.js from CDN to local `/static/chart.js`

### Backend configuration (`backend/app/main.py`)
- Added python-dotenv, static file serving, and CORS middleware

### Session handling (`backend/app/services/session_coordinator.py`)
- Removed unsafe manual `db.commit()` calls in favour of `db.begin()`
- Added missing `self._ide_lock` in `handle_browser_event()`
- `_close_timed_session()` handles both `idle_time` and `idle_sec`

### Chart.js library
- `backend/app/static/chart.js` committed to the repo — required now that the
  dashboard loads it locally

### Database
- Dropped unused tables; enabled model retraining after dashboard corrections
- Schema was at revision `2798bd862f43` (now superseded by `0009` / `0010`)

</details>
