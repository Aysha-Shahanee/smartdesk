import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import {
  getSegmentsSummary,
  getAllSegments,
  getGitHubActiveTasks,
  getIDEDashboard,
  getRecommendations,
  getWindowClusters,
  type GitHubActiveTask,
  type Recommendation,
  dayBounds,
} from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import SampleBadge from '../components/SampleBadge';
import { capitalize, formatDuration, parseSegmentTime } from '../utils/time';
import { buildDashboardPredictionSummary } from '../utils/dashboardPrediction.mjs';
import { focusOutOf100, summarizeFocus } from '../utils/focus';
/* Shared with the Insights page so "deep work" cannot come to mean two
   different things depending on which page you are looking at. */
import { BLOCK_GAP_SEC, DEEP_WORK_MIN_SEC } from '../utils/blocks';
import { bucketWindowsByScope, type PatternScope, type WindowCluster } from './patternDetection';
import './Dashboard.css';

const EMPTY_SUMMARY = {
  total_segments: 0,
  total_duration_sec: 0,
  count_by_category: {} as Record<string, number>,
  duration_by_category: {} as Record<string, number>,
};

/* Switch-density thresholds, in app switches per hour of tracked activity. */
const SWITCH_RATE_LOW = 6;
const SWITCH_RATE_HIGH = 15;
/* Full scale of the density meter — anything above reads as pinned. */
const SWITCH_RATE_SCALE = 30;

/* Stress has no collector or model behind it — there is no stress column, no
   scorer and no endpoint — so it stays a placeholder, flagged in the UI with
   <SampleBadge /> rather than presented as a measurement.

   Focus is no longer among them. `activity_segments.focus_score` is written per
   segment by the backend's FocusScorer and covers upwards of 97% of a day's
   active time, so the Focus Score below is measured — see utils/focus.ts. */
/* GitHub task predictions are provided separately by the real GitHub task
   prediction integration. */
const SAMPLE_STRESS_SCORE = 42;
const PREDICTION_REFRESH_INTERVAL_MS = 15_000;

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

const Dashboard: React.FC = () => {
  const { selectedDate, refreshCount } = useDateContext();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const chrome = getChartChrome(theme);

  const [summary, setSummary] = useState<any>(null);
  const [segments, setSegments] = useState<any[]>([]);
  const [ide, setIde] = useState<any>(null);
  const [activeTasks, setActiveTasks] = useState<GitHubActiveTask[]>([]);
  const [predictionLoading, setPredictionLoading] = useState(true);
  const [predictionError, setPredictionError] = useState('');
  const [insights, setInsights] = useState<Recommendation[]>([]);
  const [insightTotal, setInsightTotal] = useState(0);
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
      const { from, to } = dayBounds(selectedDate);
      const [sum, segs, ideSummary, recs, dayRows, weekRows, monthRows] = await Promise.all([
        getSegmentsSummary(selectedDate).catch(() => null),
        getAllSegments(selectedDate).catch(() => []),
        getIDEDashboard(from, to).catch(() => null),
        getRecommendations(selectedDate).catch(() => null),
        getWindowClusters(undefined, 1000, 'day').catch(() => []),
        getWindowClusters(undefined, 1000, 'week').catch(() => []),
        getWindowClusters(undefined, 1000, 'month').catch(() => []),
      ]);
      if (cancelled) return;
      setSummary(sum || EMPTY_SUMMARY);
      setSegments(segs);
      setIde(ideSummary);
      /* Highest-scoring findings across every section, capped at four. The
         engine has already deduped them by concern, so two rules describing
         the same problem cannot both land here. The total is kept so the panel
         can say what fraction of the day's findings it is showing. */
      const ranked: Recommendation[] = recs
        ? (Object.values(recs.sections) as Recommendation[][])
            .flat()
            .sort((a, b) => b.score - a.score)
        : [];
      setInsights(ranked.slice(0, 4));
      setInsightTotal(recs?.total ?? ranked.length);
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

  useEffect(() => {
    let cancelled = false;
    const loadActiveTasks = async (showLoading = false) => {
      if (showLoading) setPredictionLoading(true);
      try {
        const response = await getGitHubActiveTasks();
        if (!cancelled) {
          setActiveTasks(response.tasks || []);
          setPredictionError('');
        }
      } catch (error) {
        if (!cancelled) {
          setPredictionError(
            error instanceof Error ? error.message : 'Unable to load active GitHub tasks'
          );
        }
      } finally {
        if (!cancelled && showLoading) setPredictionLoading(false);
      }
    };

    loadActiveTasks(true);
    const interval = window.setInterval(
      () => loadActiveTasks(false),
      PREDICTION_REFRESH_INTERVAL_MS
    );
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshCount]);

  const { total_duration_sec = 0, duration_by_category = {} } = summary || {};
  const predictionSummary = useMemo(
    () => buildDashboardPredictionSummary(activeTasks),
    [activeTasks]
  );

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

  /* The day's focus, from the per-segment scores the backend already writes.
     Duration-weighted over active segments, which is the definition `day_focus`
     uses server-side, so this card and the Recommendations page cannot report
     different focus for the same day. See utils/focus.ts. */
  const focus = useMemo(() => summarizeFocus(segments), [segments]);

  /* Strongest and weakest bucket per scope, from the nightly clustering run.
     Unlike the metrics above these are not scoped to the selected date — they
     summarise the last completed day, week and month, so the card stays empty
     until `run_pattern_analysis.py` has populated activity_window_patterns. */
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

  if (loading) return <div className="sd-loader">Loading dashboard for {selectedDate}…</div>;

  const hasData = total_duration_sec > 0;

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

  /* Observations come from the rule engine rather than being re-derived here.
     This panel used to compute four of its own from the full segment list —
     peak hour, longest block, switch peak, idle total — which meant the
     Dashboard and the Recommendations page could describe the same day
     differently, and every one of those four was an unconditional statement
     with no comparison behind it. The engine's versions are ranked, deduped
     against each other, and carry the evidence that justifies them. */

  return (
    <div className="dashboard sd-fade-in">
      <div className="sd-page-header">
        <h1>Dashboard</h1>
        <p className="subtitle">{selectedDate} • Activity Overview</p>
      </div>

      <div className="hub-layout">
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
                  <span
                    className="metric-label"
                    title="Duration-weighted mean of every scored segment: sustained presence on one thing, from the segment's active time, unbroken length and surrounding switch rate."
                  >
                    Focus Score
                  </span>
                  <span className="metric-value">
                    {focus.score !== null ? `${focusOutOf100(focus.score)}/100` : '—'}
                  </span>
                </div>
                <div className="sd-progress">
                  <div
                    className="sd-progress-fill"
                    style={{
                      width: `${focus.score !== null ? focusOutOf100(focus.score) : 0}%`,
                      background: 'var(--color-primary)',
                    }}
                  />
                </div>
                <div className="split-bar-labels">
                  {focus.score !== null ? (
                    <>
                      <span>{focus.segments} scored segments</span>
                      {/* What the number rests on. A day whose segments are
                          mostly unscored would otherwise quote a confident
                          figure drawn from a sliver of it. */}
                      <span>{Math.round(focus.coverage * 100)}% of active time scored</span>
                    </>
                  ) : (
                    <span>No scored activity for {selectedDate}</span>
                  )}
                </div>
              </div>

              <div className="score-block">
                <div className="score-head">
                  <span className="metric-label">
                    Stress Score{' '}
                    <SampleBadge title="Stress scoring is not implemented — no collector or model produces this number, so it is fixed and does not change with the selected date." />
                  </span>
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
              Focus is measured per segment and weighted by duration. Stress has no collector or
              model behind it — that figure is a placeholder and does not change with the selected
              date.
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

        {/* ---- Prediction → Prediction page ---- */}
        <div
          className="sd-card prediction-panel"
          role="link"
          tabIndex={0}
          onClick={() => navigate('/prediction')}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') navigate('/prediction'); }}
        >
          <div className="card-header">
            <h3><span className="card-icon">🎯</span> Prediction</h3>
            <span className="card-goto" aria-label="Open Prediction">→</span>
          </div>
          <p className="card-subtitle">Active GitHub task estimates</p>

          {predictionLoading ? (
            <div className="pred-panel-task pred-panel-message">Loading active GitHub tasks…</div>
          ) : predictionError && !predictionSummary ? (
            <div className="pred-panel-task pred-panel-message">{predictionError}</div>
          ) : !predictionSummary ? (
            <div className="pred-panel-task pred-panel-message">
              <h4>No active GitHub tasks</h4>
              <span>Move an issue into the mapped ACTIVE status to see its estimate.</span>
            </div>
          ) : (
            <>
              <div className="pred-panel-task">
                <div className="pred-task-card-header">
                  <h4>{predictionSummary.task.title}</h4>
                  <span className="pred-status-badge ongoing">Active</span>
                </div>
                <div className="pred-task-context">
                  {predictionSummary.task.repository || 'GitHub'}
                  {predictionSummary.task.issue_number
                    ? ` • Issue #${predictionSummary.task.issue_number}`
                    : ''}
                </div>
                <div className="pred-task-count">
                  Active Tasks: {predictionSummary.activeTaskCount}
                  {predictionSummary.moreTaskCount > 0
                    ? ` • +${predictionSummary.moreTaskCount} more active task${predictionSummary.moreTaskCount === 1 ? '' : 's'}`
                    : ''}
                </div>
              </div>

              <div className="pred-panel-stats">
                <div>
                  <span className="metric-card-label">Initial Estimate</span>
                  <span className="metric-card-value">{predictionSummary.initialEstimate}</span>
                  <span className="pred-subtext">{predictionSummary.initialEstimateDetail}</span>
                </div>
                <div>
                  <span className="metric-card-label">Time Spent</span>
                  <span className="metric-card-value">{predictionSummary.timeSpent}</span>
                  <span className="pred-subtext">{predictionSummary.timeSpentDetail}</span>
                </div>
                <div>
                  <span className="metric-card-label">Remaining Estimate</span>
                  <span className="metric-card-value">{predictionSummary.remainingEstimate}</span>
                  <span className="pred-subtext">{predictionSummary.remainingEstimateDetail}</span>
                </div>
              </div>
              {predictionError && <p className="card-footnote">Refresh failed: {predictionError}</p>}
            </>
          )}
        </div>

        {/* ---- Key insights → Recommendations ----
               Two per row rather than four stacked, and each row carries the
               action as well as the finding: the same four items in roughly
               half the height, and the half that tells you what to do about it
               no longer requires opening the Recommendations page. ---- */}
        <div className="insight-panel">
          <div className="insight-panel-header">
            <span className="insight-panel-icon">❗</span>
            <div>
              <h3>Key Insights for Today</h3>
              <p>
                {insightTotal > insights.length
                  ? `Top ${insights.length} of ${insightTotal} findings ranked by the local rule engine`
                  : 'Ranked by the local rule engine from your recorded activity'}
              </p>
            </div>
            <span className="sd-view-details" onClick={() => navigate('/recommendations')}>
              Recommendations →
            </span>
          </div>

          {insights.length > 0 ? (
            <div className="insight-rows">
              {insights.map(item => (
                <button
                  type="button"
                  className="insight-row"
                  key={item.id}
                  onClick={() => navigate('/recommendations')}
                >
                  <span
                    className={`insight-severity ${item.severity}`}
                    title={`${capitalize(item.severity)} severity`}
                  />
                  <span className="insight-row-body">
                    <strong>{item.title}</strong>
                    <span className="insight-row-why">{item.why}</span>
                    <span className="insight-row-action">{item.action}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="dash-empty">No findings for {selectedDate} yet.</p>
          )}
        </div>

        {/* ---- Pattern snapshot → Insights ---- */}
        <div className="sd-card">
          <div className="card-header">
            <h3><span className="card-icon">🔍</span> Pattern Snapshot</h3>
            <span className="sd-view-details" onClick={() => navigate('/insights')}>
              Pattern Detection →
            </span>
          </div>
          {patternSnapshot.day || patternSnapshot.week || patternSnapshot.month ? (
            <div className="hub-rec-preview">
              {patternSnapshot.day && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small green">↗</span>
                  <div>
                    <strong>Yesterday's strongest hour was {patternSnapshot.day.strongest.label}</strong>
                    <p>{patternSnapshot.day.strongest.rangeLabel} — {Math.round(patternSnapshot.day.strongest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
              {patternSnapshot.week && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small red">!</span>
                  <div>
                    <strong>Last week's weakest day was {patternSnapshot.week.weakest.label}</strong>
                    <p>{patternSnapshot.week.weakest.rangeLabel} — {Math.round(patternSnapshot.week.weakest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
              {patternSnapshot.month && (
                <div className="rec-insight-row">
                  <span className="rec-icon-small green">↗</span>
                  <div>
                    <strong>Last month's best week was {patternSnapshot.month.strongest.label}</strong>
                    <p>{patternSnapshot.month.strongest.rangeLabel} — {Math.round(patternSnapshot.month.strongest.avgFocusScore * 100)}% focus score</p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="dash-empty">Pattern snapshots appear once clustering results are available.</p>
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
