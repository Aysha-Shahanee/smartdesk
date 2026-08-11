import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import {
  dayBounds,
  getAllSegments,
  getGitHubActiveTasks,
  getIDEDashboard,
  getSegmentsSummary,
  GitHubActiveTask,
} from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import SampleBadge from '../components/SampleBadge';
import { capitalize, formatDuration, parseSegmentTime } from '../utils/time';
import './Dashboard.css';

const EMPTY_SUMMARY = {
  total_segments: 0,
  total_duration_sec: 0,
  count_by_category: {} as Record<string, number>,
  duration_by_category: {} as Record<string, number>,
};

/* Segments this close together are treated as one continuous stretch of work.
   The builder emits a new segment on every window change, so without a merge
   tolerance a day of normal alt-tabbing looks like hundreds of one-minute
   "sessions" and no focus block ever exceeds a couple of minutes. */
const BLOCK_GAP_SEC = 120;

/* A merged block at least this long counts as deep work. 25 minutes is the
   conventional threshold for an uninterrupted focus stretch. */
const DEEP_WORK_MIN_SEC = 25 * 60;

/* Switch-density thresholds, in app switches per hour of tracked activity. */
const SWITCH_RATE_LOW = 6;
const SWITCH_RATE_HIGH = 15;
/* Full scale of the density meter — anything above reads as pinned. */
const SWITCH_RATE_SCALE = 30;

/* Placeholders. Focus and stress have no collector or endpoint behind them:
   `activity_segments.focus_score` exists as a column but is written as NULL and
   nothing ever fills it in, and there is no stress model at all. Task detection
   is the same story, which is why the whole Prediction page is sample data.
   These are flagged in the UI with <SampleBadge /> rather than presented as
   measurements. */
const SAMPLE_FOCUS_SCORE = 78;
const SAMPLE_STRESS_SCORE = 42;

interface ActiveSegment {
  start: Date;
  end: Date;
  app: string;
}

interface Block {
  start: Date;
  end: Date;
  seconds: number;
  switches: number;
}

const hourLabel = (h: number) =>
  `${String(h).padStart(2, '0')}:00–${String((h + 1) % 24).padStart(2, '0')}:00`;

const clock = (d: Date) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

const formatInitialEstimate = (hours?: number) =>
  hours === undefined || hours === null
    ? 'Estimate unavailable'
    : `Initial estimate: ${hours.toFixed(1)} hours`;

const Dashboard: React.FC = () => {
  const { selectedDate, refreshCount } = useDateContext();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const chrome = getChartChrome(theme);

  const [summary, setSummary] = useState<any>(null);
  const [segments, setSegments] = useState<any[]>([]);
  const [ide, setIde] = useState<any>(null);
  const [githubTasks, setGithubTasks] = useState<GitHubActiveTask[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const { from, to } = dayBounds(selectedDate);
      const [sum, segs, ideSummary, github] = await Promise.all([
        getSegmentsSummary(selectedDate).catch(() => null),
        getAllSegments(selectedDate).catch(() => []),
        getIDEDashboard(from, to).catch(() => null),
        getGitHubActiveTasks().catch(() => ({ tasks: [] })),
      ]);
      if (cancelled) return;
      setSummary(sum || EMPTY_SUMMARY);
      setSegments(segs);
      setIde(ideSummary);
      setGithubTasks(github.tasks);
      setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [selectedDate, refreshCount]);

  const { total_duration_sec = 0, duration_by_category = {} } = summary || {};

  /* Category breakdown feeding the Usage Breakdown donut. Sorted largest
     first so the legend doubles as a ranking — with up to nine categories the
     slices themselves are hard to compare by eye, but the legend reads
     top-down. */
  const categoryRanking = useMemo(
    () =>
      Object.entries(duration_by_category as Record<string, number>)
        // Categories that total zero seconds draw an invisible slice and a
        // dead legend row.
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

  /* Everything the cards need, derived from the segments actually recorded for
     the selected date. Idle/gap segments are excluded from the active figures
     so they agree with the summary endpoint, which counts active only. */
  const stats = useMemo(() => {
    const active: ActiveSegment[] = segments
      .filter(s => (s.state ?? 'active') === 'active')
      .map(s => {
        const start = parseSegmentTime(s.start_time_utc);
        const end = parseSegmentTime(s.end_time_utc);
        return start && end ? { start, end, app: s.app_name || 'Unknown' } : null;
      })
      .filter((s): s is ActiveSegment => s !== null)
      .sort((a, b) => a.start.getTime() - b.start.getTime());

    const idleSec = segments
      .filter(s => s.state === 'idle')
      .reduce((acc, s) => acc + (s.duration_sec || 0), 0);

    const perHour = new Array(24).fill(0);
    const switchesByHour = new Array(24).fill(0);
    const appTotals: Record<string, number> = {};
    const blocks: Block[] = [];

    let firstSeen: Date | null = null;
    let lastSeen: Date | null = null;
    let switches = 0;
    let previous: ActiveSegment | null = null;

    for (const seg of active) {
      const seconds = (seg.end.getTime() - seg.start.getTime()) / 1000;
      if (!firstSeen || seg.start < firstSeen) firstSeen = seg.start;
      if (!lastSeen || seg.end > lastSeen) lastSeen = seg.end;
      appTotals[seg.app] = (appTotals[seg.app] || 0) + seconds;

      // Charge every hour the segment touches rather than billing the whole
      // span to its starting hour.
      let cursor = seg.start.getTime();
      const endMs = seg.end.getTime();
      while (cursor < endMs) {
        const c = new Date(cursor);
        const hourEnd = new Date(
          c.getFullYear(), c.getMonth(), c.getDate(), c.getHours() + 1, 0, 0, 0
        ).getTime();
        const sliceEnd = Math.min(hourEnd, endMs);
        perHour[c.getHours()] += (sliceEnd - cursor) / 1000;
        cursor = sliceEnd;
      }

      const tail = blocks[blocks.length - 1];
      const contiguous =
        previous !== null &&
        tail !== undefined &&
        (seg.start.getTime() - tail.end.getTime()) / 1000 <= BLOCK_GAP_SEC;

      if (contiguous && tail && previous) {
        // An app change only counts as a context switch inside a block. After
        // a long break it is a fresh start, not an interruption.
        if (seg.app !== previous.app) {
          switches += 1;
          switchesByHour[seg.start.getHours()] += 1;
          tail.switches += 1;
        }
        // Segments can overlap when two collectors saw the same window.
        if (seg.end > tail.end) tail.end = seg.end;
        tail.seconds = (tail.end.getTime() - tail.start.getTime()) / 1000;
      } else {
        blocks.push({ start: seg.start, end: seg.end, seconds, switches: 0 });
      }
      previous = seg;
    }

    let peakHour: number | null = null;
    let peakSec = 0;
    perHour.forEach((sec, h) => {
      if (sec > peakSec) { peakSec = sec; peakHour = h; }
    });

    let switchPeakHour: number | null = null;
    let switchPeakCount = 0;
    switchesByHour.forEach((count, h) => {
      if (count > switchPeakCount) { switchPeakCount = count; switchPeakHour = h; }
    });

    const deepBlocks = blocks.filter(b => b.seconds >= DEEP_WORK_MIN_SEC);
    const peakBlock = blocks.reduce<Block | null>(
      (best, b) => (!best || b.seconds > best.seconds ? b : best),
      null
    );

    const activeSec = total_duration_sec || blocks.reduce((acc, b) => acc + b.seconds, 0);
    const [topApp, topAppSec] = Object.entries(appTotals).sort((a, b) => b[1] - a[1])[0] ?? [null, 0];

    return {
      firstSeen,
      lastSeen,
      peakHour,
      peakSec,
      idleSec,
      blocks,
      deepWorkSec: deepBlocks.reduce((acc, b) => acc + b.seconds, 0),
      peakBlock,
      switches,
      switchPeakHour,
      switchPeakCount,
      switchesPerHour: activeSec > 0 ? (switches / activeSec) * 3600 : 0,
      avgSwitchIntervalMin: switches > 0 ? activeSec / switches / 60 : null,
      topApp: topApp as string | null,
      topAppSec: topAppSec as number,
    };
  }, [segments, total_duration_sec]);

  if (loading) return <div className="sd-loader">Loading dashboard for {selectedDate}…</div>;

  const hasData = total_duration_sec > 0;
  const githubTask = githubTasks[0];

  const trackedSec = total_duration_sec + stats.idleSec;
  const activePct = trackedSec > 0 ? Math.round((total_duration_sec / trackedSec) * 100) : 0;

  const switchLabel =
    stats.switches === 0
      ? 'No switching recorded'
      : stats.switchesPerHour < SWITCH_RATE_LOW
        ? 'Low switching'
        : stats.switchesPerHour < SWITCH_RATE_HIGH
          ? 'Moderate switching'
          : 'High switching';

  const activityWindow =
    stats.firstSeen && stats.lastSeen
      ? `${clock(stats.firstSeen)} – ${clock(stats.lastSeen)}`
      : '—';

  /* Observations, all computed above from recorded segments — nothing here is
     a fixed string about a time of day the user may never have worked. */
  const insights: { tone: 'positive' | 'warning'; title: string; detail: string }[] = [];
  if (stats.peakHour !== null) {
    insights.push({
      tone: 'positive',
      title: `Peak activity between ${hourLabel(stats.peakHour)}`,
      detail: `${formatDuration(stats.peakSec)} of tracked activity in your busiest hour`,
    });
  }
  if (stats.peakBlock && stats.peakBlock.seconds >= DEEP_WORK_MIN_SEC) {
    insights.push({
      tone: 'positive',
      title: `Longest focus block ran ${formatDuration(stats.peakBlock.seconds)}`,
      detail: `${clock(stats.peakBlock.start)} – ${clock(stats.peakBlock.end)}, with ${stats.peakBlock.switches} app switches`,
    });
  }
  if (stats.switchPeakHour !== null && stats.switchPeakCount >= 5) {
    insights.push({
      tone: 'warning',
      title: `Context switching peaked between ${hourLabel(stats.switchPeakHour)}`,
      detail: `${stats.switchPeakCount} app switches in that hour — consider blocking it for focused work`,
    });
  }
  if (stats.idleSec > 0) {
    insights.push({
      tone: 'warning',
      title: `${formatDuration(stats.idleSec)} recorded as idle`,
      detail: 'Time the machine was on but unattended — excluded from the active totals',
    });
  }

  return (
    <div className="dashboard sd-fade-in">
      <div className="sd-page-header">
        <h1>Dashboard</h1>
        <p className="subtitle">{selectedDate} • Activity Overview</p>
      </div>

      <div className="hub-layout">
        {/* ---- Key insights → Recommendations ---- */}
        <div className="insight-panel">
          <div className="insight-panel-header">
            <span className="insight-panel-icon">❗</span>
            <div>
              <h3>Key Insights for Today</h3>
              <p>Derived from your recorded activity segments</p>
            </div>
            <span className="sd-view-details" onClick={() => navigate('/recommendations')}>
              Recommendations →
            </span>
          </div>

          {insights.length > 0 ? (
            <div className="insight-rows">
              {insights.map(item => (
                <div className="insight-row" key={item.title}>
                  <span className={`rec-icon-small ${item.tone === 'positive' ? 'green' : 'red'}`}>
                    {item.tone === 'positive' ? '↗' : '!'}
                  </span>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="dash-empty">No activity recorded for {selectedDate}.</p>
          )}
        </div>

        {/* ---- Daily Activity → Timeline / Usage Breakdown → Timeline OS tab ---- */}
        <div className="sd-grid-2">
          <div className="sd-card">
            <div className="card-header">
              <h3><span className="card-icon">🕐</span> Daily Activity</h3>
              <span className="sd-view-details" onClick={() => navigate('/timeline')}>
                View Timeline →
              </span>
            </div>

            <div className="activity-metrics">
              <div className="activity-row">
                <span className="metric-label">Total Active Time</span>
                <span className="metric-value">{formatDuration(total_duration_sec)}</span>
              </div>
              <div className="activity-row">
                <span className="metric-label" title={`Uninterrupted stretches of at least ${DEEP_WORK_MIN_SEC / 60} minutes`}>
                  Deep Work Time
                </span>
                <span className="metric-value">{formatDuration(stats.deepWorkSec)}</span>
              </div>
              <div className="activity-row">
                <span className="metric-label">Idle Time</span>
                <span className="metric-value">{formatDuration(stats.idleSec)}</span>
              </div>
            </div>

            <div className="split-bar">
              <div className="sd-progress">
                <div
                  className="sd-progress-fill"
                  style={{ width: `${activePct}%`, background: 'var(--color-primary)' }}
                />
              </div>
              <div className="split-bar-labels">
                <span>Active: {activePct}%</span>
                <span>Idle: {trackedSec > 0 ? 100 - activePct : 0}%</span>
              </div>
            </div>
          </div>

          <div className="sd-card">
            <div className="card-header">
              <h3><span className="card-icon">📈</span> Usage Breakdown</h3>
              {/* Lands on the OS / Apps tab, which lists every segment, rather
                  than Timeline's default IDE tab. */}
              <span
                className="sd-view-details"
                onClick={() => navigate('/timeline', { state: { tab: 'OS / Apps' } })}
              >
                OS Segments →
              </span>
            </div>

            {hasData ? (
              <div className="donut-container">
                <ResponsiveContainer width={160} height={160}>
                  <PieChart>
                    <Pie
                      data={categoryRanking}
                      dataKey="seconds"
                      nameKey="name"
                      innerRadius={46}
                      outerRadius={72}
                      paddingAngle={2}
                      stroke="none"
                    >
                      {categoryRanking.map(entry => (
                        <Cell key={entry.key} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value: number, name: string) => [formatDuration(value), name]}
                      contentStyle={{
                        borderRadius: 8,
                        border: `1px solid ${chrome.tooltipBorder}`,
                        background: chrome.tooltipBg,
                        color: chrome.tooltipText,
                        fontSize: 13,
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>

                <div className="donut-legend">
                  {categoryRanking.map(entry => (
                    <div className="legend-item" key={entry.key}>
                      <span className="legend-dot" style={{ background: entry.color }} />
                      <span className="legend-name">{entry.name}</span>
                      <span className="legend-value">
                        {formatDuration(entry.seconds)}
                        <span className="legend-pct"> · {entry.pct}%</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="dash-empty">No activity recorded for {selectedDate}.</p>
            )}
          </div>
        </div>

        {/* ---- Focus & Stress → Insights / Productivity → Reports ---- */}
        <div className="sd-grid-2">
          <div className="sd-card">
            <div className="card-header">
              <h3><span className="card-icon">🧠</span> Focus &amp; Stress</h3>
              <span className="sd-view-details" onClick={() => navigate('/insights')}>
                View Insights →
              </span>
            </div>

            <div className="score-list">
              <div className="score-block">
                <div className="score-head">
                  <span className="metric-label">Focus Score</span>
                  <span className="metric-value">{SAMPLE_FOCUS_SCORE}/100</span>
                </div>
                <div className="sd-progress">
                  <div
                    className="sd-progress-fill"
                    style={{ width: `${SAMPLE_FOCUS_SCORE}%`, background: 'var(--color-success)' }}
                  />
                </div>
              </div>

              <div className="score-block">
                <div className="score-head">
                  <span className="metric-label">Stress Score</span>
                  <span className="metric-value">{SAMPLE_STRESS_SCORE}/100</span>
                </div>
                <div className="sd-progress">
                  <div
                    className="sd-progress-fill"
                    style={{ width: `${SAMPLE_STRESS_SCORE}%`, background: 'var(--color-warning)' }}
                  />
                </div>
              </div>
            </div>

            <p className="card-footnote">
              <SampleBadge title="Focus and stress scoring are not implemented — no collector or model produces these numbers, so they are fixed and do not change with the selected date." />{' '}
              Focus and stress scoring have no collector behind them yet — the figures above are
              placeholders, not measurements.
            </p>
          </div>

          <div className="sd-card">
            <div className="card-header">
              <h3><span className="card-icon">⚡</span> Productivity</h3>
              <span className="sd-view-details" onClick={() => navigate('/report')}>
                View Reports →
              </span>
            </div>

            <div className="activity-metrics">
              <div className="activity-row">
                <span className="metric-label" title="App changes within a continuous stretch of work">
                  Context Switches
                </span>
                <span className="metric-value">{stats.switches}</span>
              </div>
              <div className="activity-row">
                <span className="metric-label">Avg Switch Interval</span>
                <span className="metric-value">
                  {stats.avgSwitchIntervalMin !== null
                    ? `${Math.round(stats.avgSwitchIntervalMin)} min`
                    : '—'}
                </span>
              </div>
              <div className="activity-row">
                <span className="metric-label">Peak Focus Block</span>
                <span className="metric-value">
                  {stats.peakBlock ? formatDuration(stats.peakBlock.seconds) : '—'}
                </span>
              </div>
            </div>

            <div className="split-bar">
              <div className="sd-progress">
                <div
                  className="sd-progress-fill"
                  style={{
                    width: `${Math.min(100, Math.round((stats.switchesPerHour / SWITCH_RATE_SCALE) * 100))}%`,
                    background: stats.switchesPerHour >= SWITCH_RATE_HIGH
                      ? 'var(--color-danger)'
                      : stats.switchesPerHour >= SWITCH_RATE_LOW
                        ? 'var(--color-warning)'
                        : 'var(--color-success)',
                  }}
                />
              </div>
              <div className="split-bar-labels">
                <span>{stats.switchesPerHour.toFixed(1)} switches/hour</span>
                <span>{switchLabel}</span>
              </div>
            </div>
          </div>
        </div>

        {/* ---- Initial GitHub issue prediction ---- */}
        <div className="sd-card prediction-panel">
          <div className="card-header">
            <h3><span className="card-icon">🎯</span> Active GitHub issue</h3>
            <span className="sd-view-details" onClick={() => navigate('/settings')}>GitHub settings →</span>
          </div>
          <p className="card-subtitle">Initial duration estimate captured when work becomes active</p>

          {githubTask ? (
            <div className="pred-panel-task">
              <div className="pred-task-card-header">
                <h4>{githubTask.title}</h4>
                <span className="pred-status-badge ongoing">{githubTask.logical_status}</span>
              </div>
              <div className="pred-task-context">{githubTask.repository || 'Repository unavailable'}</div>
              <div className="github-task-estimate">
                {formatInitialEstimate(githubTask.predicted_typical_hours)}
              </div>
              <div className="card-footnote">
                Started {new Date(githubTask.started_at).toLocaleString()}
              </div>
            </div>
          ) : (
            <div className="pred-panel-task">
              <h4>No ACTIVE GitHub issue</h4>
              <p className="card-footnote">
                Connect a Project and map its statuses in Settings, then move an issue to ACTIVE.
              </p>
            </div>
          )}
        </div>

        {/* ---- Reference figures. No redirects: these are endpoints, not
               previews of another page. ---- */}
        <div className="sd-grid-4">
          <div className="sd-card metric-card">
            <span className="metric-card-label">Activity Window</span>
            <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
              {activityWindow}
            </span>
            <span className="metric-card-sub">First to last recorded activity</span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Most-Used App</span>
            <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
              {stats.topApp ?? '—'}
            </span>
            <span className="metric-card-sub">
              {stats.topApp ? `${formatDuration(stats.topAppSec)} in the foreground` : 'No activity recorded'}
            </span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Work Blocks</span>
            <span className="metric-card-value">{stats.blocks.length}</span>
            <span className="metric-card-sub">
              Continuous stretches from {summary?.total_segments ?? 0} segments
            </span>
          </div>
          <div className="sd-card metric-card">
            <span className="metric-card-label">Files Modified</span>
            <span className="metric-card-value">{ide?.files_modified ?? 0}</span>
            <span className="metric-card-sub">
              Across {ide?.top_projects?.length ?? 0} IDE project
              {(ide?.top_projects?.length ?? 0) === 1 ? '' : 's'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
