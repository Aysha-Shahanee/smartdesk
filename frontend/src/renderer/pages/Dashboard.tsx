import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ResponsiveContainer, LabelList,
} from 'recharts';
import { getSegmentsSummary, getAllSegments } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import { capitalize, formatDuration, parseSegmentTime } from '../utils/time';
import './Dashboard.css';

const EMPTY_SUMMARY = {
  total_segments: 0,
  total_duration_sec: 0,
  count_by_category: {} as Record<string, number>,
  duration_by_category: {} as Record<string, number>,
};

const Dashboard: React.FC = () => {
  const { selectedDate, refreshCount } = useDateContext();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const chrome = getChartChrome(theme);

  const [summary, setSummary] = useState<any>(null);
  const [segments, setSegments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const [sum, segs] = await Promise.all([
        getSegmentsSummary(selectedDate).catch(() => null),
        getAllSegments(selectedDate).catch(() => []),
      ]);
      if (cancelled) return;
      setSummary(sum || EMPTY_SUMMARY);
      setSegments(segs);
      setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [selectedDate, refreshCount]);

  const { total_duration_sec = 0, duration_by_category = {} } = summary || {};

  /* Ranked category breakdown. A horizontal bar chart is used instead of the
     previous donut: with up to nine categories, angular slices are very hard
     to rank by eye, whereas bar length reads directly. */
  const categoryRanking = useMemo(
    () =>
      Object.entries(duration_by_category as Record<string, number>)
        // Categories that total zero seconds draw a zero-length bar with a
        // "0s" label — noise that pushes real categories out of the ranking.
        .filter(([, seconds]) => seconds > 0)
        .map(([key, seconds]) => ({
          key,
          name: capitalize(key),
          seconds,
          pct: total_duration_sec > 0 ? Math.round((seconds / total_duration_sec) * 100) : 0,
          color: getCategoryColor(key, theme),
        }))
        .sort((a, b) => b.seconds - a.seconds),
    [duration_by_category, total_duration_sec, theme]
  );

  /* Real observed activity window and busiest hour, replacing the previously
     hardcoded "focus peak 9:30-11:30" copy. Idle/gap segments are excluded so
     the numbers agree with the summary endpoint, which counts active only. */
  const derived = useMemo(() => {
    const active = segments.filter(s => (s.state ?? 'active') === 'active');
    if (active.length === 0) {
      return { firstSeen: null as Date | null, lastSeen: null as Date | null, peakHour: null as number | null, peakSec: 0, idleSec: 0, topApp: null as string | null };
    }

    const perHour = new Array(24).fill(0);
    let firstSeen: Date | null = null;
    let lastSeen: Date | null = null;
    const appTotals: Record<string, number> = {};

    for (const seg of active) {
      const start = parseSegmentTime(seg.start_time_utc);
      const end = parseSegmentTime(seg.end_time_utc);
      if (!start || !end) continue;
      if (!firstSeen || start < firstSeen) firstSeen = start;
      if (!lastSeen || end > lastSeen) lastSeen = end;

      const app = seg.app_name || 'Unknown';
      appTotals[app] = (appTotals[app] || 0) + (end.getTime() - start.getTime()) / 1000;

      // Split across every hour the segment touches rather than charging the
      // whole span to its starting hour.
      let cursor = start.getTime();
      const endMs = end.getTime();
      while (cursor < endMs) {
        const c = new Date(cursor);
        const hourEnd = new Date(c.getFullYear(), c.getMonth(), c.getDate(), c.getHours() + 1, 0, 0, 0).getTime();
        const sliceEnd = Math.min(hourEnd, endMs);
        perHour[c.getHours()] += (sliceEnd - cursor) / 1000;
        cursor = sliceEnd;
      }
    }

    let peakHour: number | null = null;
    let peakSec = 0;
    perHour.forEach((sec, h) => {
      if (sec > peakSec) { peakSec = sec; peakHour = h; }
    });

    const idleSec = segments
      .filter(s => s.state === 'idle')
      .reduce((acc, s) => acc + (s.duration_sec || 0), 0);

    const topApp = Object.entries(appTotals).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

    return { firstSeen, lastSeen, peakHour, peakSec, idleSec, topApp };
  }, [segments]);

  if (loading) return <div className="sd-loader">Loading dashboard for {selectedDate}…</div>;

  const hasData = total_duration_sec > 0;
  const topCategory = categoryRanking[0];
  const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00–${String((h + 1) % 24).padStart(2, '0')}:00`;
  const spanLabel = derived.firstSeen && derived.lastSeen
    ? `${derived.firstSeen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${derived.lastSeen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '—';

  return (
    <div className="dashboard sd-fade-in">
      <div className="sd-page-header">
        <h1>Dashboard</h1>
        <p className="subtitle">{selectedDate} • Activity Overview</p>
      </div>

      <div className="hub-layout">
        {/* Headline metrics — all derived from the segments actually recorded
            for the selected date, with no assumed target workday. */}
        <div className="sd-grid-4">
          <div className="sd-card metric-card">
            <span className="metric-card-label">Tracked Active Time</span>
            <span className="metric-card-value">{formatDuration(total_duration_sec)}</span>
            <span className="metric-card-sub">{summary?.total_segments ?? 0} segments</span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Activity Window</span>
            <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>{spanLabel}</span>
            <span className="metric-card-sub">First to last recorded activity</span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Busiest Hour</span>
            <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
              {derived.peakHour !== null ? hourLabel(derived.peakHour) : '—'}
            </span>
            <span className="metric-card-sub">
              {derived.peakHour !== null ? `${formatDuration(derived.peakSec)} of activity` : 'No activity recorded'}
            </span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Idle Time</span>
            <span className="metric-card-value">{formatDuration(derived.idleSec)}</span>
            <span className="metric-card-sub">Measured idle segments</span>
          </div>
        </div>

        {/* Category breakdown — ranked bars replace the donut. */}
        <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
          <div className="card-header">
            <h3><span className="card-icon">📊</span> Time by Category</h3>
            <span className="sd-view-details" onClick={() => navigate('/insights')}>View Insights →</span>
          </div>

          {hasData ? (
            <ResponsiveContainer width="100%" height={Math.max(180, categoryRanking.length * 44)}>
              <BarChart
                data={categoryRanking}
                layout="vertical"
                margin={{ top: 8, right: 72, bottom: 8, left: 8 }}
                barCategoryGap={8}
              >
                <CartesianGrid horizontal={false} stroke={chrome.grid} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12, fill: chrome.axisText }}
                  tickFormatter={(v: number) => formatDuration(v)}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={110}
                  tick={{ fontSize: 13, fill: chrome.axisText }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: chrome.grid, fillOpacity: 0.4 }}
                  formatter={(value: number, _n, entry: any) => [
                    `${formatDuration(value)} (${entry?.payload?.pct ?? 0}%)`,
                    'Time',
                  ]}
                  contentStyle={{
                    borderRadius: 8,
                    border: `1px solid ${chrome.tooltipBorder}`,
                    background: chrome.tooltipBg,
                    color: chrome.tooltipText,
                    fontSize: 13,
                  }}
                />
                <Bar dataKey="seconds" radius={[0, 4, 4, 0]} maxBarSize={26}>
                  {categoryRanking.map(entry => (
                    <Cell key={entry.key} fill={entry.color} />
                  ))}
                  <LabelList
                    dataKey="seconds"
                    position="right"
                    formatter={(v: number) => formatDuration(v)}
                    style={{ fill: chrome.axisText, fontSize: 12 }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="dash-empty">No activity recorded for {selectedDate}.</p>
          )}
        </div>

        {/* Observations derived from the loaded data. */}
        <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
          <div className="card-header">
            <h3><span className="card-icon">💡</span> Today at a Glance</h3>
            <span className="sd-view-details" onClick={() => navigate('/recommendations')}>Recommendations →</span>
          </div>
          {hasData ? (
            <div className="hub-rec-preview">
              <div className="rec-insight-row">
                <span className="rec-icon-small green">↗</span>
                <div>
                  <strong>
                    {topCategory.name} led your day at {formatDuration(topCategory.seconds)} ({topCategory.pct}%)
                  </strong>
                  <p>
                    Across {summary?.count_by_category?.[topCategory.key] ?? 0} segments
                    {derived.topApp ? ` • most-used app: ${derived.topApp}` : ''}
                  </p>
                </div>
              </div>
              {derived.peakHour !== null && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small green">↗</span>
                  <div>
                    <strong>Peak activity between {hourLabel(derived.peakHour)}</strong>
                    <p>{formatDuration(derived.peakSec)} of tracked activity in that hour</p>
                  </div>
                </div>
              )}
              {derived.idleSec > 0 && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small red">!</span>
                  <div>
                    <strong>{formatDuration(derived.idleSec)} recorded as idle</strong>
                    <p>Time the machine was on but unattended — excluded from the totals above</p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="dash-empty">Observations appear once activity is recorded for this date.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
