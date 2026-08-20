import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, Cell,
} from 'recharts';
import {
  getAllSegments,
  getSegmentsSummary,
  getReport,
  getReportMarkdown,
  type NarrativeReport,
  type ReportMetric,
} from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import { capitalize, formatDuration, shiftDate } from '../utils/time';
import './Report.css';

type ReportTab = 'Daily Report' | 'Weekly Report' | 'Monthly Report';

interface DaySummary {
  date: string;
  total_segments: number;
  total_duration_sec: number;
  count_by_category: Record<string, number>;
  duration_by_category: Record<string, number>;
}

const EMPTY = (date: string): DaySummary => ({
  date,
  total_segments: 0,
  total_duration_sec: 0,
  count_by_category: {},
  duration_by_category: {},
});

/** Fetch summaries for `count` days ending on `endDate` (inclusive). */
const fetchRange = async (endDate: string, count: number): Promise<DaySummary[]> => {
  const dates = Array.from({ length: count }, (_, i) => shiftDate(endDate, -(count - 1 - i)));
  return Promise.all(
    dates.map(d =>
      getSegmentsSummary(d)
        .then((r: any) => ({ ...EMPTY(d), ...r, date: d }))
        .catch(() => EMPTY(d))
    )
  );
};

const TAB_SCOPE: Record<ReportTab, 'daily' | 'weekly' | 'monthly'> = {
  'Daily Report': 'daily',
  'Weekly Report': 'weekly',
  'Monthly Report': 'monthly',
};

/** One application's share of a day. */
interface AppUsage {
  app: string;
  activeSec: number;
  pct: number;
}

/** How many apps the table shows before "Show all". */
const APP_ROWS_COLLAPSED = 5;

/**
 * Time per application for one day, from activity segments.
 *
 * **Active seconds only.** Idle time is discarded rather than ranked: an editor
 * left open over lunch would otherwise outrank whatever the day was actually
 * spent on. Apps that were only ever idle drop out entirely instead of sitting
 * at the bottom on 0%.
 *
 * Segments with no app name are grouped as "Unknown" rather than dropped, so
 * the column still sums to the active total the narrative quotes above it.
 */
const summariseApps = (segments: any[]): AppUsage[] => {
  const byApp = new Map<string, number>();
  for (const segment of segments) {
    if (segment.state !== 'active') continue;
    const app = (segment.app_name || '').trim() || 'Unknown';
    byApp.set(app, (byApp.get(app) ?? 0) + (segment.duration_sec || 0));
  }

  const total = [...byApp.values()].reduce((sum, sec) => sum + sec, 0) || 1;
  return [...byApp.entries()]
    .filter(([, activeSec]) => activeSec > 0)
    .map(([app, activeSec]) => ({
      app,
      activeSec,
      pct: Math.round((activeSec / total) * 100),
    }))
    .sort((a, b) => b.activeSec - a.activeSec);
};

/* One marker per section key, so a reader can find "what went wrong" without
   reading the heading. Keys come from `build_sections` in the report service. */
const SECTION_ICON: Record<string, string> = {
  headline: '📌',
  where: '🗂️',
  focus: '🎯',
  broke: '⚠️',
  wins: '✅',
  watch: '💡',
};

/** A metric in the same shape the prose uses, so the two never disagree. */
const formatMetric = (value: number, unit: ReportMetric['unit']): string => {
  if (unit === 'min') return formatDuration(value * 60);
  if (unit === 'share') return `${Math.round(value * 100)}%`;
  if (unit === 'score') return value.toFixed(2);
  return String(Math.round(value));
};

/**
 * One headline figure with its comparison against the user's own baseline.
 *
 * A null `baseline` means the backend has no comparison for this metric, and
 * the tile then shows the figure alone. It used to say "Not enough history to
 * compare", which was misleading in both directions: monthly totals have no
 * baseline defined at all — a 30-day total is one sample, so no amount of
 * recording would produce one — while metrics that *do* have baselines were
 * reading as history problems when the argument had simply not been passed.
 * Claiming nothing is the honest form, and the backend suppresses the
 * comparison in the prose on the same condition.
 */
const MetricTile: React.FC<{ metric: ReportMetric }> = ({ metric }) => {
  const { delta, baseline, unit, higher_is_better } = metric;
  const better = delta === null || delta === 0 ? null : (delta > 0) === higher_is_better;

  return (
    <div className="narrative-metric">
      <span className="narrative-metric-label">{metric.label}</span>
      <span className="narrative-metric-value">{formatMetric(metric.value, unit)}</span>
      {baseline === null ? null : delta === null || delta === 0 ? (
        <span className="narrative-metric-sub">Same as your usual</span>
      ) : (
        <span className="narrative-metric-sub">
          <span className={`narrative-delta ${better ? 'up' : 'down'}`}>
            {delta > 0 ? '▲' : '▼'} {formatMetric(Math.abs(delta), unit)}
          </span>
          {' '}vs usual {formatMetric(baseline, unit)}
        </span>
      )}
    </div>
  );
};

/**
 * The narrative half of a report.
 *
 * Prose is assembled server-side from a fact base that is computed before any
 * sentence exists, so nothing here can contain a number the data does not
 * support. The charts below render the same period from the same segments.
 *
 * Presentation only, but deliberate: the previous version stacked every
 * section's lines as full-width paragraphs, which turned a set of independent
 * one-sentence facts into a wall of prose nobody reads. Each line is now its
 * own bullet at a readable measure, the figures the sentences quote are lifted
 * into a strip of tiles above them, and the caveats are demoted to a footer.
 */
const NarrativePanel: React.FC<{ report: NarrativeReport | null; loading: boolean }> = ({
  report,
  loading,
}) => {
  if (loading) return <div className="sd-card"><p className="dash-empty">Writing the report…</p></div>;
  if (!report) return null;
  if (!report.has_activity) {
    return (
      <div className="sd-card">
        <p className="dash-empty">No activity was recorded for {report.period_label}.</p>
      </div>
    );
  }

  return (
    <div className="sd-card narrative" style={{ marginBottom: 'var(--space-xl)' }}>
      <div className="card-header">
        <h3><span className="card-icon">📝</span> {report.period_label}</h3>
      </div>

      {report.metrics.length > 0 && (
        <div className="narrative-metrics">
          {report.metrics.map(metric => (
            <MetricTile key={metric.key} metric={metric} />
          ))}
        </div>
      )}

      {report.sections.map(section => (
        <section key={section.key} className="narrative-section">
          <h4 className="narrative-section-head">
            <span className="narrative-section-icon">{SECTION_ICON[section.key] ?? '•'}</span>
            {section.heading}
          </h4>

          {section.body.length > 0 && (
            <ul className="narrative-points">
              {section.body.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          )}

          {(section.items ?? []).length > 0 && (
            <div className="narrative-findings">
              {(section.items ?? []).map(item => (
                <article
                  className={`narrative-finding sev-${item.severity}`}
                  key={item.rule_id + item.title}
                >
                  <h5>{item.title}</h5>
                  <p className="narrative-finding-why">{item.why}</p>
                  <p className="narrative-finding-action">
                    <span className="narrative-finding-tag">Do this</span>
                    {item.action}
                  </p>
                  <p className="narrative-finding-src">{item.based_on} • {item.rule_id}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  );
};

const Report: React.FC = () => {
  const { selectedDate, refreshCount } = useDateContext();
  const { theme } = useTheme();
  const chrome = getChartChrome(theme);
  const [activeTab, setActiveTab] = useState<ReportTab>('Daily Report');
  const [days, setDays] = useState<DaySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<NarrativeReport | null>(null);
  const [reportLoading, setReportLoading] = useState(true);
  const [apps, setApps] = useState<AppUsage[]>([]);
  const [appsLoading, setAppsLoading] = useState(true);
  const [showAllApps, setShowAllApps] = useState(false);

  // 30 days covers all three tabs, so switching tabs needs no extra fetch.
  // The previous version passed an empty dependency array, so the report kept
  // showing the first date it ever loaded even as the date picker moved.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchRange(selectedDate, 30)
      .then(rows => { if (!cancelled) { setDays(rows); setLoading(false); } })
      .catch(() => { if (!cancelled) { setDays([]); setLoading(false); } });
    return () => { cancelled = true; };
  }, [selectedDate, refreshCount]);

  useEffect(() => {
    let cancelled = false;
    setReportLoading(true);
    getReport(TAB_SCOPE[activeTab], selectedDate)
      .then(r => { if (!cancelled) { setReport(r); setReportLoading(false); } })
      .catch(() => { if (!cancelled) { setReport(null); setReportLoading(false); } });
    return () => { cancelled = true; };
  }, [activeTab, selectedDate, refreshCount]);

  /* The day the app breakdown describes.
   *
   * Deliberately the report's own period, not `selectedDate`. A daily report
   * asked for today describes yesterday — reports.py moves `as_of` back a day
   * rather than measuring a partial day against full-day baselines — so keying
   * this off the date picker would put a table for one day directly beneath
   * prose about another, with nothing on screen saying they differ. */
  const dailyDate = report?.scope === 'daily' ? report.period_start : selectedDate;

  useEffect(() => {
    if (activeTab !== 'Daily Report') return;
    let cancelled = false;
    setAppsLoading(true);
    // Collapse again on a new day — "show all" is about this table, not a
    // preference that should follow the user across dates.
    setShowAllApps(false);
    getAllSegments(dailyDate)
      .then(rows => { if (!cancelled) { setApps(summariseApps(rows)); setAppsLoading(false); } })
      .catch(() => { if (!cancelled) { setApps([]); setAppsLoading(false); } });
    return () => { cancelled = true; };
  }, [activeTab, dailyDate, refreshCount]);

  const today = days[days.length - 1];
  const week = useMemo(() => days.slice(-7), [days]);

  const dailyCategories = useMemo(() => {
    if (!today) return [];
    const total = today.total_duration_sec || 1;
    return Object.entries(today.duration_by_category)
      .map(([key, seconds]) => ({
        key,
        name: capitalize(key),
        seconds,
        count: today.count_by_category[key] || 0,
        pct: Math.round((seconds / total) * 100),
        color: getCategoryColor(key, theme),
      }))
      .sort((a, b) => b.seconds - a.seconds);
  }, [today, theme]);

  const weeklyChart = useMemo(
    () =>
      week.map(d => ({
        day: new Date(`${d.date}T00:00:00`).toLocaleDateString([], { weekday: 'short' }),
        date: d.date,
        hours: +(d.total_duration_sec / 3600).toFixed(2),
      })),
    [week]
  );

  const monthlyChart = useMemo(() => {
    // Group the 30-day window into 7-day buckets, oldest first.
    const buckets: { label: string; hours: number; segments: number }[] = [];
    for (let i = 0; i < days.length; i += 7) {
      const chunk = days.slice(i, i + 7);
      if (chunk.length === 0) continue;
      buckets.push({
        label: `${chunk[0].date.slice(5)} – ${chunk[chunk.length - 1].date.slice(5)}`,
        hours: +(chunk.reduce((a, d) => a + d.total_duration_sec, 0) / 3600).toFixed(2),
        segments: chunk.reduce((a, d) => a + d.total_segments, 0),
      });
    }
    return buckets;
  }, [days]);

  const weekTotals = useMemo(() => {
    const totalSec = week.reduce((a, d) => a + d.total_duration_sec, 0);
    const activeDays = week.filter(d => d.total_duration_sec > 0);
    const best = week.reduce(
      (acc, d) => (d.total_duration_sec > (acc?.total_duration_sec ?? -1) ? d : acc),
      null as DaySummary | null
    );
    const catTotals: Record<string, number> = {};
    week.forEach(d =>
      Object.entries(d.duration_by_category).forEach(([k, v]) => {
        catTotals[k] = (catTotals[k] || 0) + v;
      })
    );
    const topCat = Object.entries(catTotals).sort((a, b) => b[1] - a[1])[0];
    return {
      totalSec,
      avgSec: activeDays.length ? totalSec / activeDays.length : 0,
      activeDays: activeDays.length,
      best,
      topCat: topCat ? { name: capitalize(topCat[0]), seconds: topCat[1] } : null,
    };
  }, [week]);

  const monthTotals = useMemo(() => {
    const totalSec = days.reduce((a, d) => a + d.total_duration_sec, 0);
    const activeDays = days.filter(d => d.total_duration_sec > 0);
    const catTotals: Record<string, number> = {};
    days.forEach(d =>
      Object.entries(d.duration_by_category).forEach(([k, v]) => {
        catTotals[k] = (catTotals[k] || 0) + v;
      })
    );
    const topCat = Object.entries(catTotals).sort((a, b) => b[1] - a[1])[0];
    const firstHalf = days.slice(0, 15).reduce((a, d) => a + d.total_duration_sec, 0);
    const secondHalf = days.slice(15).reduce((a, d) => a + d.total_duration_sec, 0);
    return {
      totalSec,
      activeDays: activeDays.length,
      avgSec: activeDays.length ? totalSec / activeDays.length : 0,
      topCat: topCat ? { name: capitalize(topCat[0]), seconds: topCat[1] } : null,
      trend: secondHalf - firstHalf,
    };
  }, [days]);

  /* `delta()` and `DeltaBadge` were removed with the Daily tab's metric grid,
     which was their only caller. The narrative's own MetricTile carries the
     comparison against the user's baseline, which is a stronger statement than
     a one-day difference. */

  const handleExport = () => {
    if (!today) return;
    const rows = [['Category', 'Segments', 'Duration (s)', 'Hours', '% of Total']];
    dailyCategories.forEach(c => {
      rows.push([c.key, String(c.count), String(c.seconds), (c.seconds / 3600).toFixed(2), String(c.pct)]);
    });
    rows.push(['TOTAL', String(today.total_segments), String(today.total_duration_sec),
      (today.total_duration_sec / 3600).toFixed(2), '100']);
    const csv = rows.map(r => r.map(v => `"${v}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `smartdesk_report_${today.date}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportMarkdown = async () => {
    try {
      const markdown = await getReportMarkdown(TAB_SCOPE[activeTab], selectedDate);
      const blob = new Blob([markdown], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `smartdesk_${TAB_SCOPE[activeTab]}_${selectedDate}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* Export is a convenience; the report itself is already on screen. */
    }
  };

  const handleExportPdf = async () => {
    if (!window.electronAPI) return;
    await window.electronAPI.exportReportPdf(TAB_SCOPE[activeTab], selectedDate);
  };

  if (loading) return <div className="sd-loader">Loading reports…</div>;

  const tooltipStyle = {
    borderRadius: 8,
    border: `1px solid ${chrome.tooltipBorder}`,
    background: chrome.tooltipBg,
    color: chrome.tooltipText,
  };

  return (
    <div className="report-page sd-fade-in">
      <div className="report-header">
        <div>
          <h1>Reports</h1>
          <p className="subtitle">Generated from recorded activity • window ending {selectedDate}</p>
        </div>
        {window.electronAPI && (
          <button className="sd-btn" onClick={handleExportPdf} style={{ marginRight: 8 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 6 2 18 2 18 9" /><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><rect x="6" y="14" width="12" height="8" /></svg>
            Export PDF
          </button>
        )}
        <button className="sd-btn" onClick={handleExportMarkdown} style={{ marginRight: 8 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
          Export Report
        </button>
        <button className="sd-btn" onClick={handleExport}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
          Export CSV
        </button>
      </div>

      <div className="sd-tabs">
        {(['Daily Report', 'Weekly Report', 'Monthly Report'] as ReportTab[]).map(tab => (
          <button
            key={tab}
            className={`sd-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ---- Daily ---- */}
      {activeTab === 'Daily Report' && (
        <div className="report-content sd-fade-in">
          <NarrativePanel report={report} loading={reportLoading} />

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Applications used</h3>
            {appsLoading ? (
              <p className="dash-empty">Loading…</p>
            ) : apps.length > 0 ? (
              <>
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Application</th><th>Active</th><th>% of Active</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(showAllApps ? apps : apps.slice(0, APP_ROWS_COLLAPSED)).map(a => (
                      <tr key={a.app}>
                        <td>{a.app}</td>
                        <td>{formatDuration(a.activeSec)}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div className="sd-progress" style={{ width: 80 }}>
                              <div
                                className="sd-progress-fill"
                                style={{ width: `${a.pct}%`, background: 'var(--color-primary)' }}
                              />
                            </div>
                            {a.pct}%
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {apps.length > APP_ROWS_COLLAPSED && (
                  <button
                    className="sd-btn app-table-toggle"
                    onClick={() => setShowAllApps(v => !v)}
                  >
                    {showAllApps
                      ? 'Show top 5'
                      : `Show all ${apps.length} apps`}
                  </button>
                )}
              </>
            ) : (
              <p className="dash-empty">No activity recorded on {dailyDate}.</p>
            )}
          </div>
        </div>
      )}

      {/* ---- Weekly ---- */}
      {activeTab === 'Weekly Report' && (
        <div className="report-content sd-fade-in">
          <NarrativePanel report={report} loading={reportLoading} />
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Total Tracked Time</span>
              <span className="metric-card-value">{formatDuration(weekTotals.totalSec)}</span>
              <span className="metric-card-sub">Last 7 days to {selectedDate}</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Daily Average</span>
              <span className="metric-card-value">{formatDuration(weekTotals.avgSec)}</span>
              <span className="metric-card-sub">Across {weekTotals.activeDays} active day(s)</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Busiest Day</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {weekTotals.best && weekTotals.best.total_duration_sec > 0
                  ? new Date(`${weekTotals.best.date}T00:00:00`).toLocaleDateString([], { weekday: 'long' })
                  : '—'}
              </span>
              <span className="metric-card-sub">
                {weekTotals.best ? formatDuration(weekTotals.best.total_duration_sec) : ''}
              </span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Top Category</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {weekTotals.topCat?.name ?? '—'}
              </span>
              <span className="metric-card-sub">
                {weekTotals.topCat ? formatDuration(weekTotals.topCat.seconds) : 'No activity'}
              </span>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Tracked Time per Day</h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={weeklyChart}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: chrome.axisText }} />
                <YAxis tick={{ fontSize: 13, fill: chrome.axisText }} unit="h" />
                <Tooltip
                  formatter={(v: number) => [`${v} h`, 'Tracked']}
                  labelFormatter={(_l, p: any) => p?.[0]?.payload?.date ?? ''}
                  contentStyle={tooltipStyle}
                />
                <Bar dataKey="hours" name="Tracked hours" fill={getCategoryColor('work', theme)} radius={[6, 6, 0, 0]} maxBarSize={64} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ---- Monthly ---- */}
      {activeTab === 'Monthly Report' && (
        <div className="report-content sd-fade-in">
          <NarrativePanel report={report} loading={reportLoading} />
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Total Tracked Time</span>
              <span className="metric-card-value">{formatDuration(monthTotals.totalSec)}</span>
              <span className="metric-card-sub">Last 30 days to {selectedDate}</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Active Days</span>
              <span className="metric-card-value">{monthTotals.activeDays}</span>
              <span className="metric-card-sub">Days with recorded activity</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Daily Average</span>
              <span className="metric-card-value">{formatDuration(monthTotals.avgSec)}</span>
              <span className="metric-card-sub">On active days</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Second vs First Half</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {monthTotals.trend >= 0 ? '↑' : '↓'} {formatDuration(Math.abs(monthTotals.trend))}
              </span>
              <span className="metric-card-sub">Change across the window</span>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Tracked Time by Week</h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={monthlyChart}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="label" tick={{ fontSize: 12, fill: chrome.axisText }} />
                <YAxis tick={{ fontSize: 13, fill: chrome.axisText }} unit="h" />
                <Tooltip formatter={(v: number) => [`${v} h`, 'Tracked']} contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="hours" name="Tracked hours" radius={[6, 6, 0, 0]} maxBarSize={80}>
                  {monthlyChart.map((_, i) => (
                    <Cell key={i} fill={getCategoryColor('work', theme)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Top Category Across the Window</h3>
            {monthTotals.topCat ? (
              <p style={{ color: 'var(--color-text-secondary)' }}>
                <strong style={{ color: 'var(--color-text-primary)' }}>{monthTotals.topCat.name}</strong>
                {' '}accounted for {formatDuration(monthTotals.topCat.seconds)} of the
                {' '}{formatDuration(monthTotals.totalSec)} recorded in the last 30 days
                {monthTotals.totalSec > 0
                  ? ` (${Math.round((monthTotals.topCat.seconds / monthTotals.totalSec) * 100)}%).`
                  : '.'}
              </p>
            ) : (
              <p className="dash-empty">No activity recorded in this window.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default Report;
