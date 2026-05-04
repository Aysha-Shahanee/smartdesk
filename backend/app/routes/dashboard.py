from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.database import SessionLocal
from app.models.db_models import (
    OSMinuteWindowRecord,
    BrowserMinuteWindowRecord,
    VSCodeMinuteWindowRecord,
    CalendarEventRecord,
)


router = APIRouter()


def _get_session():
    return SessionLocal()


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@router.get("/", response_class=HTMLResponse)
def dashboard_page() -> str:
    """Simple HTML UI with basic visualizations and guidance."""

    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SmartDesk Activity Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-6 space-y-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold">SmartDesk Data Collection</h1>
        <p class="text-sm text-slate-400">Quick view of what your OS, VS Code, Browser and Calendar collectors are storing locally.</p>
      </div>
      <div class="flex gap-2">
        <button id="connectCalendarBtn" class="px-3 py-1.5 rounded-md bg-blue-600 text-sm font-medium hover:bg-blue-500 transition-colors">Connect Calendar</button>
        <button id="syncCalendarBtn" class="px-3 py-1.5 rounded-md bg-indigo-600 text-sm font-medium hover:bg-indigo-500 transition-colors">Sync Calendar</button>
        <button id="refreshBtn" class="px-3 py-1.5 rounded-md bg-emerald-500 text-sm font-medium hover:bg-emerald-400 transition-colors">Refresh data</button>
      </div>
    </header>

    <section class="grid grid-cols-1 md:grid-cols-4 gap-4" id="summaryCards">
      <!-- Cards filled by JS -->
    </section>

    <section class="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
      <div class="md:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-medium text-slate-200">Events in the last 24 hours</h2>
          <p class="text-xs text-slate-500" id="lastUpdated"></p>
        </div>
        <canvas id="timelineChart" height="120"></canvas>
      </div>

      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
        <h2 class="text-sm font-medium text-slate-200">Setup checklist</h2>
        <p class="text-xs text-slate-400">These are static hints for now; you can adjust the copy later.</p>
        <ul class="space-y-2 text-xs text-slate-300">
          <li class="flex items-start gap-2"><span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-500"></span> Backend API running on <code class="px-1 rounded bg-slate-800 text-[10px]">http://127.0.0.1:8000</code></li>
          <li class="flex items-start gap-2"><span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-500"></span> OS collector active (Windows foreground app + idle tracking)</li>
          <li class="flex items-start gap-2"><span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-500"></span> Browser extension installed in Chrome / Edge / Firefox</li>
          <li class="flex items-start gap-2"><span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-500"></span> VS Code extension installed (SmartDesk IDE logger)</li>
          <li class="flex items-start gap-2"><span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-500"></span> Google Calendar connected (OAuth consent completed)</li>
        </ul>
      </div>
    </section>
  </div>

<script>
async function loadStats() {
  try {
    const res = await fetch('/dashboard/stats');
    if (!res.ok) throw new Error('Failed to load stats');
    const data = await res.json();
    renderSummaryCards(data.per_source);
    renderTimeline(data.timeseries);
    const el = document.getElementById('lastUpdated');
    if (el) el.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error(e);
  }
}

function renderSummaryCards(perSource) {
  const container = document.getElementById('summaryCards');
  if (!container) return;
  const items = [
    { key: 'os', label: 'OS Minute Windows' },
    { key: 'browser', label: 'Browser Minute Windows' },
    { key: 'vscode', label: 'VS Code Minute Windows' },
    { key: 'calendar', label: 'Calendar Events' },
  ];
  container.innerHTML = items.map(item => {
    const stats = perSource[item.key] || { total: 0, last_timestamp: null };
    return `
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-3">
        <p class="text-xs text-slate-400">${item.label}</p>
        <p class="mt-1 text-xl font-semibold">${stats.total}</p>
        <p class="mt-1 text-[11px] text-slate-500">Last: ${stats.last_timestamp || '—'}</p>
      </div>
    `;
  }).join('');
}

let timelineChart;

function renderTimeline(timeseries) {
  const ctx = document.getElementById('timelineChart');
  if (!ctx) return;

  const labels = timeseries.labels || [];
  const dsOs = timeseries.os || [];
  const dsBrowser = timeseries.browser || [];
  const dsVsCode = timeseries.vscode || [];
  const dsCalendar = timeseries.calendar || [];

  const config = {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'OS', data: dsOs, borderColor: '#22c55e', tension: 0.25 },
        { label: 'Browser', data: dsBrowser, borderColor: '#3b82f6', tension: 0.25 },
        { label: 'VS Code', data: dsVsCode, borderColor: '#eab308', tension: 0.25 },
        { label: 'Calendar', data: dsCalendar, borderColor: '#f97316', tension: 0.25 },
      ]
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          labels: { color: '#cbd5f5', font: { size: 10 } }
        }
      },
      scales: {
        x: {
          ticks: { color: '#64748b', maxTicksLimit: 8, font: { size: 9 } },
          grid: { color: '#1e293b' }
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#64748b', stepSize: 1, font: { size: 9 } },
          grid: { color: '#1e293b' }
        }
      }
    }
  };

  if (timelineChart) {
    timelineChart.destroy();
  }
  timelineChart = new Chart(ctx, config);
}

document.getElementById('refreshBtn')?.addEventListener('click', loadStats);

document.getElementById('connectCalendarBtn')?.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/v1/calendar/connect', { method: 'POST' });
    const data = await res.json();
    alert(data.message || 'Calendar connected!');
    loadStats();
  } catch (e) {
    console.error(e);
    alert('Failed to connect calendar');
  }
});

document.getElementById('syncCalendarBtn')?.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/v1/calendar/sync', { method: 'POST' });
    const data = await res.json();
    alert(`Synced ${data.fetched_events} events. Inserted: ${data.inserted}, Updated: ${data.updated}`);
    loadStats();
  } catch (e) {
    console.error(e);
    alert('Failed to sync calendar');
  }
});

loadStats();
</script>

</body>
</html>"""


@router.get("/stats", response_class=JSONResponse)
def dashboard_stats():
    """Return summary counts and simple 24h timeseries from minute-window tables."""

    session = _get_session()
    try:
        def summarize(model, time_col: str = "window_start") -> Dict[str, object]:
            total = session.query(model).count()
            col = getattr(model, time_col)
            last = (
                session.query(model)
                .order_by(col.desc())
                .limit(1)
                .one_or_none()
            )
            last_ts = getattr(last, time_col, None) if last else None
            return {"total": total, "last_timestamp": last_ts}

        per_source = {
            "os": summarize(OSMinuteWindowRecord),
            "browser": summarize(BrowserMinuteWindowRecord),
            "vscode": summarize(VSCodeMinuteWindowRecord),
            "calendar": summarize(CalendarEventRecord, "start_time"),
        }

        # Timeseries: count per hour for the last 24h
        now = datetime.now(timezone.utc)
        window_start_filter = (now - timedelta(hours=24)).isoformat()

        def load_records(model, time_col: str = "window_start"):
            col = getattr(model, time_col)
            return session.query(model).filter(col >= window_start_filter).all()

        os_records = load_records(OSMinuteWindowRecord)
        browser_records = load_records(BrowserMinuteWindowRecord)
        vscode_records = load_records(VSCodeMinuteWindowRecord)
        calendar_records = load_records(CalendarEventRecord, "start_time")

        def build_buckets(records, time_col: str = "window_start") -> Dict[str, int]:
            buckets: Dict[str, int] = {}
            for r in records:
                ts_str = getattr(r, time_col, None)
                ts = _parse_iso(ts_str)
                if not ts:
                    continue
                hour = ts.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat()
                buckets[hour] = buckets.get(hour, 0) + 1
            return buckets

        os_b = build_buckets(os_records)
        br_b = build_buckets(browser_records)
        vs_b = build_buckets(vscode_records)
        ca_b = build_buckets(calendar_records, "start_time")

        labels_set = set(os_b.keys()) | set(br_b.keys()) | set(vs_b.keys()) | set(ca_b.keys())
        labels: List[str] = sorted(labels_set)

        def series_for(buckets: Dict[str, int]) -> List[int]:
            return [buckets.get(label, 0) for label in labels]

        timeseries = {
            "labels": labels,
            "os": series_for(os_b),
            "browser": series_for(br_b),
            "vscode": series_for(vs_b),
            "calendar": series_for(ca_b),
        }

        return {"per_source": per_source, "timeseries": timeseries}
    finally:
        session.close()
