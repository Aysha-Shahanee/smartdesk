# SmartDesk Frontend — Logic Reference

How every number and chart in the desktop UI is produced: which endpoint it
comes from, what transformation is applied, and which figures are still
placeholders. Written after an audit that found and fixed 14 defects; the
"Defects found and fixed" section at the end records what was wrong and why.

---

## 1. Architecture

```
src/
  main.ts                    Electron main process (window, preload wiring)
  preload.ts                 contextBridge surface (currently unused by the UI)
  renderer/
    index.tsx / App.tsx      React root, HashRouter, nav shell
    index.css                Design system: tokens, utilities, light/dark themes
    contexts/
      DateContext.tsx        Globally selected date + manual refresh counter
      ThemeContext.tsx       light/dark, persisted to localStorage
    theme/chartTheme.ts      Category/emotion colours + per-theme chart chrome
    utils/time.ts            Canonical timestamp parsing and formatting
    services/
      api.ts                 Backend calls, date-window helpers, pagination
      fetchUtils.ts          fetch + JSON error handling
    components/
      DatePicker.tsx         Day stepper in the navbar
      ChangeLabelTable.tsx   Correction UI (writes back to the model)
      SampleDataBanner.tsx   Marks pages whose numbers are placeholders
    pages/
      Dashboard.tsx          Real data
      Timeline.tsx           Real data
      Report.tsx             Real data
      Insights.tsx           Placeholder
      Prediction.tsx         Placeholder
      Recommendations.tsx    Placeholder
      Settings.tsx           Local preferences
```

Two cross-cutting rules the UI now follows:

1. **Time totals come from activity segments.** `activity_segments` is
   documented as canonical and non-overlapping, so summing it cannot
   double-count. Per-source session tables can overlap (see §5.2).
2. **Provenance comes from the API, never from string matching.** Each segment
   reports `primary_source` and its source-session links; the UI filters on
   those.

---

## 2. Shared foundations

### 2.1 `utils/time.ts` — the timestamp contract

The API field is named `start_time_utc`, **but it does not hold UTC.** The
segment builder writes:

```python
local_date = seg_dict["start_time"].date().isoformat()
```

A bare `.date()` with no zone conversion only yields the correct local date if
`start_time` is already local. The value also arrives with no zone designator
(`2026-07-31T00:36:53.447862`). So it is **naive local wall time**.

| Function | Purpose |
|---|---|
| `parseSegmentTime(s)` | Strips any zone suffix, parses as local. Returns `null` if unusable. |
| `formatSegmentTime(s)` | `"14:05"` clock label. |
| `segmentDurationSec(a,b)` | Seconds between two segment timestamps. |
| `formatDuration(sec)` | `"2h 15m"` / `"45m"` / `"30s"`. |
| `formatEventTime(s)` | For **calendar** events, which *do* carry a real offset — parsed normally. |
| `todayString()` | Today from **local** fields. |
| `shiftDate(d, n)` | Day arithmetic anchored at local midnight. |
| `capitalize(s)` | `social_media` → `Social media`. |

### 2.2 `services/api.ts` — windows and pagination

**Day bounds carry an explicit UTC offset.** The backend's `ensure_aware()`
stamps any naive timestamp it receives as UTC:

```python
def ensure_aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
```

So `2026-06-14T00:00:00` is read as 05:30 local in Asia/Colombo. `dayBounds()`
therefore emits `2026-06-14T00:00:00+05:30`, computing the offset from the
browser for that specific date (DST-safe).

**`getAllSegments(date)` follows pagination to the end.** `limit` is capped at
500 server-side and real days exceed it (2026-07-25 has 700 rows). It reads
page 1, then requests the remaining offsets in parallel.

### 2.3 `theme/chartTheme.ts` — colour

- `CATEGORY_SLOTS` — a fixed hue order, one entry per category, with separate
  light and dark steps. Order is the colour-blindness safety mechanism, not
  decoration: adjacent-pair separation was validated for protanopia,
  deuteranopia and tritanopia in both modes.
- `system` and unknown categories map to a desaturated neutral — a recessive
  "not a real activity" bucket that never competes with the eight real hues.
- `getChartChrome(theme)` returns grid, axis, and tooltip colours. Recharts
  renders these as inline SVG/style values, so they must be resolved in JS;
  CSS variables do not reach them.

---

## 3. Dashboard (`pages/Dashboard.tsx`)

**Sources:** `getSegmentsSummary(date)` and `getAllSegments(date)`.

### Headline tiles

| Tile | Derivation |
|---|---|
| Tracked Active Time | `summary.total_duration_sec`. The endpoint filters `state = 'active'` and non-null category. |
| Activity Window | Earliest start to latest end across active segments. |
| Busiest Hour | Max of a 24-bucket histogram (see below). |
| Idle Time | Sum of `duration_sec` where `state = 'idle'` — **measured**, not inferred. |

**Hour bucketing** splits each segment across every hour it spans rather than
charging the whole span to its start hour:

```ts
while (cursor < endMs) {
  const hourEnd = <start of next local hour>;
  const sliceEnd = Math.min(hourEnd, endMs);
  perHour[new Date(cursor).getHours()] += (sliceEnd - cursor) / 1000;
  cursor = sliceEnd;
}
```

Verified conservative: bucketed totals match raw sums within rounding
(≤3.6 min over a 374-min day, from per-segment `duration_sec` rounding).

### Time by Category

A **ranked horizontal bar chart**, replacing a donut. With up to nine
categories, angular slices cannot be ranked by eye; bar length reads directly.
Sorted descending, zero-duration categories filtered out, each bar in its
category colour with a direct duration label.

### Today at a Glance

Observations computed from the loaded data — leading category with share and
segment count, most-used app, peak hour, and measured idle time. Renders an
empty state when the day has no activity.

---

## 4. Timeline (`pages/Timeline.tsx`)

Four tabs: **IDE**, **Browser**, **OS / Apps**, **Calendar**. All scoped to the
single selected date.

### 4.1 Tab routing — provenance, not app names

```ts
IDE:      primary_source === 'ide'     || has_ide_session
Browser:  primary_source === 'browser' || has_browser_session
OS/Apps:  everything
```

The previous implementation substring-matched `app_name` against hardcoded
keyword lists. Measured against the full database:

| | Old keyword filter | Real provenance |
|---|---|---|
| Browser segments found | **4 of 562** | 562 |
| Non-IDE segments wrongly shown as IDE | **736** | 0 |
| IDE segments missed | 34 | 0 |

The browser list (`chrome, firefox, edge, safari, brave, opera, browser`)
matched none of Comet, Acrobat, VLC, Explorer, Telegram or WhatsApp, while
`'code'` matched unrelated window titles.

### 4.2 Idle handling

Idle and gap segments are **excluded by default**, matching the summary
endpoint so the Timeline and Dashboard agree. A header checkbox — shown only
when idle segments exist — adds them back, rendered at reduced opacity.

Verified: active-segment totals equal `summary.total_duration_sec` exactly on
every date tested.

### 4.3 Per-tab data sources

| Tab | Time totals | Breakdown chart |
|---|---|---|
| IDE | `/dashboard/ide` `coding_time_sec` | **Time by Language** from `ide_sessions.active_language` |
| Browser | Activity segments (non-overlapping) | **Time by Domain** — hostname parsed from each segment's `detail` URL |
| OS / Apps | Activity segments | **Time by Application** from segment `app_name` |

Each breakdown chart carries a one-line provenance note.

**Why the browser tab does not use `/dashboard/browser`.** That endpoint sums
`browser_sessions.duration_sec` over foreground rows, and concurrent tabs are
each recorded as foreground. On 2026-07-25 it reports **15.2 h of browsing on a
day with 6.2 h of total OS activity** — a 1.4× overlap (naive sum 54 567 s vs
merged wall-clock union 38 962 s). Activity segments are non-overlapping and
browser segments carry the full URL, so the domain split is recoverable without
the double count.

IDE sessions were checked for the same problem and do **not** overlap
(sum 10 253 s vs union 10 261 s), so the IDE panel's own figure is quoted
directly — which is also what "read the IDE table directly" requires.

Domain labelling distinguishes three cases: a real hostname, `Local file` for
`file://` URLs (which have no hostname), and `No URL recorded` for segments
with a browser link but no URL.

### 4.4 Activity by Hour

Same hour-splitting algorithm as the Dashboard, but the axis range is derived
from the data (first touched hour to last) instead of a fixed 09:00–17:00
window. That window discarded 42 % of a typical day and **100 % of activity on
2026-07-31**, whose work ran 00:00–01:22.

### 4.5 Category Distribution

A donut weighted by **time**, not segment count. Counting segments made a
5-second window-focus blip rank equal to an hour of work. Full legend with
durations; zero-duration categories filtered.

### 4.6 Timeline View (flame chart)

Segments are packed into lanes — each segment goes in the first lane whose last
entry ends at or before it starts, capped at 12 lanes. Previously every segment
was absolutely positioned on one row, so overlapping segments painted over each
other. Hovering shows title, time range, duration, category, and idle state.

### 4.7 Calendar

Fetched with offset-aware day bounds, then filtered to events whose
`start_time` date equals the selected date. Shows meeting count, total
scheduled time, all-day count (excluded from the time total), longest block, a
**Meeting Load by Hour** chart, and the schedule list.

Previously the frontend passed `from = to = "2026-07-31"`, making the window a
single instant at midnight — this tab returned **zero events on every date**.

---

## 5. Reports (`pages/Report.tsx`)

Fetches 30 daily summaries in parallel ending at the selected date, so all
three tabs are served by one load.

| Tab | Contents |
|---|---|
| Daily | Tracked time, segment count, top category, active categories — each with a **computed** delta against the previous day. Category breakdown table with per-category colour and share bars. |
| Weekly | Last 7 days: total, daily average over active days, busiest day, top category, and a per-day tracked-time chart. |
| Monthly | Last 30 days grouped into 7-day buckets: total, active days, average, second-half vs first-half change, and a per-week chart. |

CSV export writes the selected day's real category breakdown.

---

## 6. Correction flow (`components/ChangeLabelTable.tsx`)

Renders every segment for the day (paginated fully), showing predicted
category, confidence, and any existing correction. Saving posts to
`/dashboard/corrections`, which routes through `categorizer.store_user_correction`
and increments the retraining counter. The table updates optimistically.

This is the **only write path** in the frontend.

---

## 7. Placeholder pages

**Insights**, **Prediction** and **Recommendations** contain module-level
constant arrays. No endpoint produces focus scores, stress levels, emotion
mixes or task predictions — the backend exposes only activity segments,
per-source session panels, and calendar events.

Each now renders `<SampleDataBanner>` stating that the figures are fixed
placeholders that do not respond to the date picker. Their charts were still
brought onto the shared colour system and made theme-aware, so they look
correct when real data does arrive.

---

## 8. Defects found and fixed

Grouped by severity. Every claim below was verified against the live database
or a running instance.

### Wrong data shown to the user

1. **Browser tab was 99.3 % empty.** Keyword matching on `app_name` found 4 of
   562 browser segments. Now filters on `primary_source`.
2. **736 non-IDE segments were shown as IDE**, because `'code'` matched
   unrelated window titles.
3. **Calendar tab was always empty.** `from = to = <date>` collapsed the query
   window to midnight. Fixed with real day bounds.
4. **Day windows were shifted by the UTC offset.** Naive bounds are read as UTC
   server-side; an all-day event at 00:00 local fell outside a window that
   effectively started at 05:30. Bounds now carry an explicit offset. *(Found by
   verification after the first fix — the initial fix was itself incomplete.)*
5. **Up to 200 segments per day were silently dropped.** A single request with
   `limit=500` truncated days holding 700 rows. Now paginates fully.
6. **Correction table timestamps were 5.5 h off.** It appended `'Z'` to a value
   that already held local time, disagreeing with the Timeline for the same
   segment.
7. **The app opened on yesterday's data.** `new Date().toISOString()` returns
   the UTC date, so between midnight and 05:30 local the frontend requested the
   previous day while the backend considered it today.
8. **Activity outside 09:00–17:00 was discarded.** The hourly chart seeded a
   fixed office-hours window — 42 % of a typical day, and 100 % of 2026-07-31.
9. **Multi-hour segments were charged entirely to their starting hour.**
10. **"Idle Time" was invented arithmetic.** The Dashboard showed
    `8h − active_time`, an assumed workday, not measured idle. Real idle
    segments exist and are now summed.
11. **Timeline counted idle time as activity** while the Dashboard excluded it,
    so the two pages disagreed on the same day.
12. **Reports never refreshed.** `useEffect(..., [])` meant the page kept
    showing whichever date loaded first.
13. **The Week/Month toggle did nothing.** It widened only the calendar query;
    segments were always fetched for one day, so wider periods showed
    day-scoped numbers under a week/month heading. Removed rather than left
    lying about scope.
14. **The preload script never loaded.** `main.js` resolved
    `../preload.js` (`out/preload.js`) but the build emits
    `out/preload/preload.js`. Harmless today because the renderer never calls
    `electronAPI`, but it silently disabled the bridge.

### Misleading presentation

15. **Distribution was weighted by segment count, not time** — a 5-second blip
    ranked equal to an hour of work.
16. **Flame chart segments painted over each other** on a single row.
17. **Dashboard legend listed only 4 of N categories** while drawing all
    slices, leaving the rest identified by colour alone.
18. **Zero-duration categories drew empty bars** labelled `0s`.
19. **Fabricated deltas** (`+5 from yesterday`, `+22min from yesterday`) were
    hardcoded next to real values. Now computed.
20. **Hardcoded "insights"** ("Focus peak observed between 9:30–11:30") were
    presented as analysis on the Dashboard. Replaced with derived observations.

### Known upstream issue, surfaced not hidden

21. **`/dashboard/browser` double-counts by ~1.4×** because concurrent tabs are
    each foreground. The UI now avoids it for time totals. Fixing the collector
    or the aggregation is a backend change and was left alone.

---

## 9. Backend change required by this UI

`/dashboard/segments` gained six additive fields:

```
duration_sec, state, primary_source,
has_ide_session, has_browser_session, has_os_session
```

Without them the UI cannot distinguish an IDE segment from a browser one
except by guessing at `app_name`. **The API server must be restarted** to serve
them; the Timeline detects their absence and shows an explicit warning rather
than rendering empty tabs.

---

## 10. Verification performed

- **Pagination** — fetched vs API total vs direct SQL count, matched on every
  date tested; confirmed the old path dropped 200 rows on 2026-07-25.
- **Tab routing** — new provenance filter vs old keyword filter, counted across
  the whole database.
- **Idle exclusion** — Timeline active totals equal
  `summary.total_duration_sec` exactly.
- **Hour bucketing** — bucketed totals conserve raw duration within rounding.
- **Calendar windows** — offset-aware bounds match SQL per-day counts,
  including the all-day event at local midnight that naive bounds dropped.
- **Overlap analysis** — browser sessions 1.4× overlap confirmed by comparing
  naive sums to merged interval unions; IDE sessions confirmed non-overlapping.
- **Runtime** — the app was driven through Dashboard, Timeline (all four tabs),
  Reports and Insights against the live backend and real data: all pages
  rendered, all tiles populated, **zero console or page errors**.
- **Build** — `electron-vite build` succeeds. Pre-existing `tsc` errors in
  `preload.ts`/`api.ts` (`import.meta` under a CommonJS `module` setting) are
  unrelated to this work and were present before it.
