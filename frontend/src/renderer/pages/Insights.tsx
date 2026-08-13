import { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { useTheme } from '../contexts/ThemeContext';
import { useDateContext } from '../contexts/DateContext';
import { getCategoryColor, getEmotionColor, getChartChrome } from '../theme/chartTheme';
import { getWindowClusters } from '../services/api';
import SampleDataBanner from '../components/SampleDataBanner';
import { formatSegmentTime } from '../utils/time';
import {
  buildFocusTrend,
  bucketWindowsByScope,
  describeBucketUnit,
  describeRangeLabel,
  type FocusLevel,
  type PatternBucket,
  type PatternScope,
  type WindowCluster,
} from './patternDetection';
import './Insights.css';

type InsightTab = 'Focus Insights' | 'Stress Insights' | 'Pattern Detection';

const focusTrend = [
  { day: 'Mon', score: 65 }, { day: 'Tue', score: 72 }, { day: 'Wed', score: 85 },
  { day: 'Thu', score: 78 }, { day: 'Fri', score: 58 }, { day: 'Sat', score: 5 }, { day: 'Sun', score: 3 },
];

const deepVsShallow = [
  { day: 'Mon', deep: 110, shallow: 170 }, { day: 'Tue', deep: 165, shallow: 140 },
  { day: 'Wed', deep: 220, shallow: 110 }, { day: 'Thu', deep: 180, shallow: 120 },
  { day: 'Fri', deep: 95, shallow: 215 }, { day: 'Sat', deep: 0, shallow: 0 }, { day: 'Sun', deep: 0, shallow: 0 },
];

const stressThroughDay = [
  { time: '09:00', level: 25 }, { time: '10:00', level: 30 }, { time: '11:00', level: 28 },
  { time: '12:00', level: 45 }, { time: '13:00', level: 55 }, { time: '14:00', level: 40 },
  { time: '15:00', level: 35 }, { time: '16:00', level: 42 }, { time: '17:00', level: 50 },
];

const EMOTION_DATA = [
  { name: 'Calm', key: 'calm', value: 45 },
  { name: 'Focused', key: 'focused', value: 18 },
  { name: 'Neutral', key: 'neutral', value: 32 },
  { name: 'Stressed', key: 'stressed', value: 5 },
];

const FOCUS_LEVEL_LABELS: Record<FocusLevel, string> = {
  high_focus: 'High Focus',
  low_focus: 'Low Focus',
  distracted: 'Distracted',
};

const PATTERN_SCOPE_LABELS: Record<PatternScope, string> = {
  day: 'Last Day',
  week: 'Last Week',
  month: 'Last Month',
};

const focusLevelColor = (level: FocusLevel, theme: 'light' | 'dark') => {
  if (level === 'high_focus') return getCategoryColor('learn', theme);
  if (level === 'low_focus') return getCategoryColor('documentation', theme);
  return getEmotionColor('stressed', theme);
};

const formatPct = (value: number) => `${Math.round(value * 100)}%`;

const describeScopeSelection = (scope: PatternScope) => {
  if (scope === 'day') return 'the latest completed day (yesterday)';
  if (scope === 'week') return 'latest weekly clustering run';
  return 'latest monthly clustering run';
};

const Insights: React.FC = () => {
  const { theme } = useTheme();
  const { refreshCount } = useDateContext();
  const chrome = getChartChrome(theme);
  const emotionDistribution = EMOTION_DATA.map(e => ({ ...e, color: getEmotionColor(e.key, theme) }));
  const [activeTab, setActiveTab] = useState<InsightTab>('Focus Insights');
  const [patternScope, setPatternScope] = useState<PatternScope>('day');
  const [patternWindows, setPatternWindows] = useState<WindowCluster[]>([]);
  const [patternLoading, setPatternLoading] = useState(false);
  const [patternError, setPatternError] = useState<string | null>(null);
  const [selectedBucketId, setSelectedBucketId] = useState<string | null>(null);

  useEffect(() => {
    if (activeTab !== 'Pattern Detection') return;
    let cancelled = false;

    const loadPatterns = async () => {
      setPatternLoading(true);
      setPatternError(null);
      try {
        const rows = await getWindowClusters(undefined, 1000, patternScope) as WindowCluster[];
        if (cancelled) return;
        const sorted = [...rows].sort((a, b) => a.window_start.localeCompare(b.window_start));
        setPatternWindows(sorted);
      } catch (error) {
        if (cancelled) return;
        setPatternWindows([]);
        setSelectedBucketId(null);
        setPatternError(error instanceof Error ? error.message : 'Failed to load pattern data');
      } finally {
        if (!cancelled) setPatternLoading(false);
      }
    };

    loadPatterns();
    return () => { cancelled = true; };
  }, [activeTab, patternScope, refreshCount]);

  const patternBuckets = useMemo(
    () => bucketWindowsByScope(patternWindows, patternScope),
    [patternScope, patternWindows]
  );

  useEffect(() => {
    setSelectedBucketId(prev => (
      prev && patternBuckets.some(bucket => bucket.id === prev)
        ? prev
        : patternBuckets[patternBuckets.length - 1]?.id ?? null
    ));
  }, [patternBuckets]);

  const selectedBucket = useMemo(
    () => patternBuckets.find(bucket => bucket.id === selectedBucketId) ?? patternBuckets[patternBuckets.length - 1] ?? null,
    [patternBuckets, selectedBucketId]
  );

  const selectedTrend = useMemo(
    () => buildFocusTrend(patternWindows, patternScope, selectedBucket),
    [patternScope, patternWindows, selectedBucket]
  );

  const patternSummary = useMemo(() => {
    const counts: Record<FocusLevel, number> = {
      high_focus: 0,
      low_focus: 0,
      distracted: 0,
    };

    for (const row of patternWindows) counts[row.focus_level] += 1;

    const total = patternWindows.length;
    const avgFocus = total > 0
      ? patternWindows.reduce((sum, row) => sum + row.avg_focus_score, 0) / total
      : 0;
    const unusual = [...patternWindows]
      .filter(row => row.anomaly_score !== null)
      .sort((a, b) => (a.anomaly_score ?? 0) - (b.anomaly_score ?? 0))
      .slice(0, 5);
    const unit = describeBucketUnit(patternScope);
    const bestBucket = [...patternBuckets]
      .sort((a, b) => b.counts.high_focus - a.counts.high_focus || b.avgFocusScore - a.avgFocusScore)[0] ?? null;
    const weakestBucket = [...patternBuckets]
      .sort((a, b) => (
        (b.counts.low_focus + b.counts.distracted) - (a.counts.low_focus + a.counts.distracted)
        || a.avgFocusScore - b.avgFocusScore
      ))[0] ?? null;

    const findings: string[] = [];
    if (bestBucket) {
      findings.push(`Best focus ${unit}: ${bestBucket.label} (${bestBucket.rangeLabel}) with ${formatPct(bestBucket.avgFocusScore)} average focus.`);
    }
    if (weakestBucket) {
      findings.push(`Weakest ${unit}: ${weakestBucket.label} (${weakestBucket.rangeLabel}) with ${weakestBucket.counts.low_focus + weakestBucket.counts.distracted} lower-focus windows.`);
    }
    if (counts.distracted > 0) {
      findings.push(`${counts.distracted} distracted windows were detected in this ${PATTERN_SCOPE_LABELS[patternScope].toLowerCase()} view.`);
    }
    if (total > 0) {
      findings.push(`Average focus score across analyzed windows: ${formatPct(avgFocus)}.`);
    }

    const distribution = (Object.keys(counts) as FocusLevel[])
      .map(level => ({
        key: level,
        name: FOCUS_LEVEL_LABELS[level],
        value: counts[level],
        color: focusLevelColor(level, theme),
      }))
      .filter(item => item.value > 0);

    return { counts, total, avgFocus, unusual, findings, distribution };
  }, [patternBuckets, patternScope, patternWindows, theme]);

  return (
    <div className="insights-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Insights</h1>
        <p className="subtitle">Focus, stress and pattern analysis</p>
      </div>

      {activeTab !== 'Pattern Detection' && (
        <SampleDataBanner what="Focus scoring, stress level and emotion detection" />
      )}

      <div className="sd-tabs">
        {(['Focus Insights', 'Stress Insights', 'Pattern Detection'] as InsightTab[]).map(tab => (
          <button
            key={tab}
            className={`sd-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Focus Insights' && (
        <div className="insights-content sd-fade-in">
          <div className="sd-card">
            <h3>Focus Score Trend (Last 7 Days)</h3>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={focusTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: chrome.axisText }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: chrome.axisText }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }} />
                <Line type="monotone" dataKey="score" name="Focus score" stroke={getCategoryColor('work', theme)} strokeWidth={2.5} dot={{ r: 4, fill: getCategoryColor('work', theme) }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Deep Work vs Shallow Work (Minutes)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={deepVsShallow} barGap={4}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: chrome.axisText }} />
                <YAxis tick={{ fontSize: 13, fill: chrome.axisText }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }} />
                <Legend wrapperStyle={{ fontSize: 12, color: 'var(--color-text-secondary)' }} />
                <Bar dataKey="deep" fill={getCategoryColor('learn', theme)} radius={[4, 4, 0, 0]} name="Deep Work" />
                <Bar dataKey="shallow" fill={getCategoryColor('communication', theme)} radius={[4, 4, 0, 0]} name="Shallow Work" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-alert sd-alert--success" style={{ marginTop: 'var(--space-xl)' }}>
            <span className="sd-alert-icon">↑</span>
            <div className="sd-alert-content">
              <h4>Key Finding</h4>
              <p>Your best focus window is between <strong>10:00 AM - 12:00 PM</strong>. During this time, your focus score averages 85/100 with minimal context switching.</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Stress Insights' && (
        <div className="insights-content sd-fade-in">
          <div className="sd-card">
            <h3>Stress Level Throughout Day</h3>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={stressThroughDay}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="time" tick={{ fontSize: 13, fill: chrome.axisText }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: chrome.axisText }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }} />
                <Line type="monotone" dataKey="level" name="Stress level" stroke={getEmotionColor('stressed', theme)} strokeWidth={2.5} dot={{ r: 4, fill: getEmotionColor('stressed', theme) }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
            <div className="sd-card">
              <h3>Emotion Distribution</h3>
              <div className="donut-container">
                <ResponsiveContainer width="50%" height={200}>
                  <PieChart>
                    <Pie data={emotionDistribution} dataKey="value" cx="50%" cy="50%" innerRadius={45} outerRadius={80} paddingAngle={2} strokeWidth={0}>
                      {emotionDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
                    </Pie>
                    <Tooltip
                      formatter={(value: number) => `${value}%`}
                      contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="donut-legend">
                  {emotionDistribution.map((item, i) => (
                    <div className="legend-item" key={i}>
                      <span className="legend-dot" style={{ background: item.color }} />
                      <span className="legend-name">{item.name}</span>
                      <span className="legend-value">{item.value}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="sd-card">
              <h3>Privacy Controls</h3>
              <div className="privacy-list">
                <div className="privacy-item">
                  <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                  <div>
                    <strong>No Face Images Stored</strong>
                    <p>Only emotion labels are saved</p>
                  </div>
                </div>
                <div className="privacy-item">
                  <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                  <div>
                    <strong>No Raw Camera Feed</strong>
                    <p>Processing happens locally</p>
                  </div>
                </div>
                <div className="privacy-item">
                  <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                  <div>
                    <strong>Data Stays Local</strong>
                    <p>Cloud sync is optional</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="sd-alert sd-alert--warning" style={{ marginTop: 'var(--space-xl)' }}>
            <span className="sd-alert-icon">!</span>
            <div className="sd-alert-content">
              <h4>Elevated Stress After Lunch</h4>
              <p>Your stress levels increase by 40% between 1 PM - 3 PM. Consider scheduling less demanding tasks during this window.</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Pattern Detection' && (
        <div className="insights-content sd-fade-in">
          <div className="pattern-scope-bar">
            <div>
              <h3>Pattern Detection</h3>
              <p className="pattern-description">
                Compare focus patterns {describeRangeLabel(patternScope)} using {describeScopeSelection(patternScope)}.
              </p>
            </div>
            <div className="pattern-scope-toggle">
              {(['day', 'week', 'month'] as PatternScope[]).map(scope => (
                <button
                  key={scope}
                  type="button"
                  className={`pattern-scope-button ${patternScope === scope ? 'active' : ''}`}
                  onClick={() => setPatternScope(scope)}
                >
                  {PATTERN_SCOPE_LABELS[scope]}
                </button>
              ))}
            </div>
          </div>

          {patternLoading ? (
            <div className="sd-loader">Loading {PATTERN_SCOPE_LABELS[patternScope].toLowerCase()} pattern data…</div>
          ) : patternError ? (
            <div className="sd-alert sd-alert--danger">
              <span className="sd-alert-icon">!</span>
              <div className="sd-alert-content">
                <h4>Pattern data could not be loaded</h4>
                <p>{patternError}</p>
              </div>
            </div>
          ) : patternSummary.total === 0 ? (
            <div className="sd-card">
              <h3>Pattern Detection</h3>
              <p className="pattern-description">
                No clustered windows are available for this {patternScope} view yet. Run pattern analysis and refresh to see focus patterns here.
              </p>
            </div>
          ) : (
            <>
              <div className="sd-grid-3 pattern-overview-grid">
                <div className="pattern-stat-card">
                  <span className="pattern-stat-value" style={{ color: focusLevelColor('high_focus', theme) }}>
                    {patternSummary.counts.high_focus}
                  </span>
                  <span className="pattern-stat-label">High Focus Windows</span>
                  <span className="pattern-stat-sub">Strong focus in this scope</span>
                </div>
                <div className="pattern-stat-card">
                  <span className="pattern-stat-value" style={{ color: focusLevelColor('low_focus', theme) }}>
                    {patternSummary.counts.low_focus}
                  </span>
                  <span className="pattern-stat-label">Low Focus Windows</span>
                  <span className="pattern-stat-sub">Windows to improve</span>
                </div>
                <div className="pattern-stat-card">
                  <span className="pattern-stat-value" style={{ color: focusLevelColor('distracted', theme) }}>
                    {patternSummary.counts.distracted}
                  </span>
                  <span className="pattern-stat-label">Distracted Windows</span>
                  <span className="pattern-stat-sub">Interruption-heavy periods</span>
                </div>
              </div>

              <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                <h3>{describeRangeLabel(patternScope).replace('-', ' ').replace('-', ' ').replace(/\b\w/g, char => char.toUpperCase())} View</h3>
                <p className="pattern-description">
                  Select a {describeBucketUnit(patternScope)} to inspect the dominant pattern, focus score, and work mix for that period.
                </p>
                <div className="pattern-period-grid">
                  {patternBuckets.map((bucket: PatternBucket) => (
                    <button
                      key={bucket.id}
                      type="button"
                      className={`pattern-period-card ${selectedBucket?.id === bucket.id ? 'active' : ''}`}
                      onClick={() => setSelectedBucketId(bucket.id)}
                    >
                      <span
                        className="pattern-period-accent"
                        style={{ background: focusLevelColor(bucket.focusLevel, theme) }}
                      />
                      <span className="pattern-period-label">{bucket.label}</span>
                      <span className="pattern-period-range">{bucket.rangeLabel}</span>
                      <span className="pattern-period-meta">
                        {bucket.totalWindows} windows · {formatPct(bucket.avgFocusScore)}
                      </span>
                    </button>
                  ))}
                </div>
                {selectedBucket && (
                  <div className="pattern-window-detail">
                    <div>
                      <span className="pattern-detail-label">Period</span>
                      <strong>{selectedBucket.label}</strong>
                      <p>{selectedBucket.rangeLabel}</p>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Dominant Pattern</span>
                      <strong style={{ color: focusLevelColor(selectedBucket.focusLevel, theme) }}>
                        {FOCUS_LEVEL_LABELS[selectedBucket.focusLevel]}
                      </strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Avg Focus</span>
                      <strong>{formatPct(selectedBucket.avgFocusScore)}</strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Windows</span>
                      <strong>{selectedBucket.totalWindows}</strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Work Mix</span>
                      <strong>{formatPct(selectedBucket.workRatio)}</strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Learning Mix</span>
                      <strong>{formatPct(selectedBucket.learnRatio)}</strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Communication Mix</span>
                      <strong>{formatPct(selectedBucket.communicationRatio)}</strong>
                    </div>
                    <div>
                      <span className="pattern-detail-label">Anomaly</span>
                      <strong>{selectedBucket.anomalyScore?.toFixed(2) ?? '—'}</strong>
                    </div>
                  </div>
                )}
              </div>

              {patternScope === 'week' && selectedBucket && selectedTrend.length > 0 && (
                <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                  <h3>Focus Score vs Time</h3>
                  <p className="pattern-description">
                    {selectedBucket.label} ({selectedBucket.rangeLabel}) shown in 10-minute windows.
                  </p>
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={selectedTrend}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                      <XAxis dataKey="label" tick={{ fontSize: 12, fill: chrome.axisText }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: chrome.axisText }} />
                      <Tooltip
                        formatter={(value: number) => [`${value}%`, 'Focus score']}
                        contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                      />
                      <Line
                        type="monotone"
                        dataKey="focusScore"
                        stroke={getCategoryColor('work', theme)}
                        strokeWidth={2.5}
                        dot={false}
                        activeDot={{ r: 4 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                <div className="sd-card">
                  <h3>Pattern Findings</h3>
                  <div className="patterns-list">
                    {patternSummary.findings.map((finding, i) => (
                      <div key={i} className="sd-alert sd-alert--success">
                        <span className="sd-alert-icon">→</span>
                        <div className="sd-alert-content">
                          <p>{finding}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="sd-card">
                  <h3>Most Unusual Windows</h3>
                  <div className="pattern-unusual-list">
                    {patternSummary.unusual.map(window => (
                      <div key={window.window_id} className="pattern-unusual-item">
                        <div>
                          <strong>{formatSegmentTime(window.window_start)} - {formatSegmentTime(window.window_end)}</strong>
                          <p>{FOCUS_LEVEL_LABELS[window.focus_level]}</p>
                        </div>
                        <div className="pattern-anomaly-pill">
                          {window.anomaly_score?.toFixed(2) ?? '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                <h3>Pattern Distribution</h3>
                <p className="pattern-description">
                  Average focus across this {patternScope} scope is {formatPct(patternSummary.avgFocus)}.
                </p>
                <div className="donut-container">
                  <ResponsiveContainer width="45%" height={220}>
                    <PieChart>
                      <Pie
                        data={patternSummary.distribution}
                        dataKey="value"
                        cx="50%"
                        cy="50%"
                        innerRadius={48}
                        outerRadius={82}
                        paddingAngle={2}
                        strokeWidth={0}
                      >
                        {patternSummary.distribution.map(item => (
                          <Cell key={item.key} fill={item.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: number, _name, entry: { payload?: { name?: string } }) => {
                          const pct = patternSummary.total > 0
                            ? Math.round((value / patternSummary.total) * 100)
                            : 0;
                          return [`${value} windows (${pct}%)`, entry?.payload?.name ?? ''];
                        }}
                        contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-legend">
                    {patternSummary.distribution.map(item => (
                      <div className="legend-item" key={item.key}>
                        <span className="legend-dot" style={{ background: item.color }} />
                        <span className="legend-name">{item.name}</span>
                        <span className="legend-value">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default Insights;
