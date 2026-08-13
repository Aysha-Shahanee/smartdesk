import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ResponsiveContainer, LabelList,
} from 'recharts';
import { getSegmentsSummary, getAllSegments, getWindowClusters } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import { capitalize, formatDuration, parseSegmentTime } from '../utils/time';
import { bucketWindowsByScope, type PatternScope, type WindowCluster } from './patternDetection';
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
  const [patternRows, setPatternRows] = useState<Record<PatternScope, WindowCluster[]>>({
    day: [],
    week: [],
    month: [],
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const [sum, segs, dayRows, weekRows, monthRows] = await Promise.all([
        getSegmentsSummary(selectedDate).catch(() => null),
        getAllSegments(selectedDate).catch(() => []),
        getWindowClusters(undefined, 1000, 'day').catch(() => []),
        getWindowClusters(undefined, 1000, 'week').catch(() => []),
        getWindowClusters(undefined, 1000, 'month').catch(() => []),
      ]);
      if (cancelled) return;
      setSummary(sum || EMPTY_SUMMARY);
      setSegments(segs);
      setPatternRows({
        day: dayRows as WindowCluster[],
        week: weekRows as WindowCluster[],
        month: monthRows as WindowCluster[],
      });
      setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [selectedDate, refreshCount]);

  const { total_duration_sec = 0, duration_by_category = {} } = summary || {};

  const categoryRanking = useMemo(
    () =>
      Object.entries(duration_by_category as Record<string, number>)
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

  const derived = useMemo(() => {
    const active = segments.filter(s => (s.state ?? 'active') === 'active');
    if (active.length === 0) {
      return {
        firstSeen: null as Date | null,
        lastSeen: null as Date | null,
        peakHour: null as number | null,
        peakSec: 0,
        idleSec: 0,
      };
    }

    const perHour = new Array(24).fill(0);
    let firstSeen: Date | null = null;
    let lastSeen: Date | null = null;

    for (const seg of active) {
      const start = parseSegmentTime(seg.start_time_utc);
      const end = parseSegmentTime(seg.end_time_utc);
      if (!start || !end) continue;
      if (!firstSeen || start < firstSeen) firstSeen = start;
      if (!lastSeen || end > lastSeen) lastSeen = end;

      let cursor = start.getTime();
      const endMs = end.getTime();
      while (cursor < endMs) {
        const current = new Date(cursor);
        const hourEnd = new Date(current.getFullYear(), current.getMonth(), current.getDate(), current.getHours() + 1, 0, 0, 0).getTime();
        const sliceEnd = Math.min(hourEnd, endMs);
        perHour[current.getHours()] += (sliceEnd - cursor) / 1000;
        cursor = sliceEnd;
      }
    }

    let peakHour: number | null = null;
    let peakSec = 0;
    perHour.forEach((sec, hour) => {
      if (sec > peakSec) {
        peakSec = sec;
        peakHour = hour;
      }
    });

    const idleSec = segments
      .filter(s => s.state === 'idle')
      .reduce((acc, s) => acc + (s.duration_sec || 0), 0);

    return { firstSeen, lastSeen, peakHour, peakSec, idleSec };
  }, [segments]);

  const patternSnapshot = useMemo(() => {
    const summarize = (scope: PatternScope) => {
      const buckets = bucketWindowsByScope(patternRows[scope], scope);
      if (buckets.length === 0) return null;
      return {
        strongest: [...buckets].sort((a, b) => b.avgFocusScore - a.avgFocusScore)[0],
        weakest: [...buckets].sort((a, b) => a.avgFocusScore - b.avgFocusScore)[0],
      };
    };

    return {
      day: summarize('day'),
      week: summarize('week'),
      month: summarize('month'),
    };
  }, [patternRows]);

  if (loading) return <div className="sd-loader">Loading dashboard for {selectedDate}...</div>;

  const hasData = total_duration_sec > 0;
  const hourLabel = (h: number) => `${String(h).padStart(2, '0')}:00-${String((h + 1) % 24).padStart(2, '0')}:00`;
  const spanLabel = derived.firstSeen && derived.lastSeen
    ? `${derived.firstSeen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${derived.lastSeen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '-';

  return (
    <div className="dashboard sd-fade-in">
      <div className="sd-page-header">
        <h1>Dashboard</h1>
        <p className="subtitle">{selectedDate} - Activity Overview</p>
      </div>

      <div className="hub-layout">
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
              {derived.peakHour !== null ? hourLabel(derived.peakHour) : '-'}
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

        <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
          <div className="card-header">
            <h3><span className="card-icon">Time</span> Time by Category</h3>
            <span className="sd-view-details" onClick={() => navigate('/insights')}>View Insights</span>
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
                  formatter={(value: number, _name, entry: { payload?: { pct?: number } }) => [
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

        <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
          <div className="card-header">
            <h3><span className="card-icon">Pattern</span> Pattern Snapshot</h3>
            <span className="sd-view-details" onClick={() => navigate('/insights')}>Pattern Detection</span>
          </div>
          {patternSnapshot.day || patternSnapshot.week || patternSnapshot.month ? (
            <div className="hub-rec-preview">
              {patternSnapshot.day && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small green">^</span>
                  <div>
                    <strong>Yesterday's strongest hour was {patternSnapshot.day.strongest.label}</strong>
                    <p>{patternSnapshot.day.strongest.rangeLabel} - {Math.round(patternSnapshot.day.strongest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
              {patternSnapshot.week && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small green">^</span>
                  <div>
                    <strong>Last week's weakest day was {patternSnapshot.week.weakest.label}</strong>
                    <p>{patternSnapshot.week.weakest.rangeLabel} - {Math.round(patternSnapshot.week.weakest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
              {patternSnapshot.month && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small red">!</span>
                  <div>
                    <strong>Last month's best week was {patternSnapshot.month.strongest.label}</strong>
                    <p>{patternSnapshot.month.strongest.rangeLabel} - {Math.round(patternSnapshot.month.strongest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="dash-empty">Pattern snapshots appear once clustering results are available.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
