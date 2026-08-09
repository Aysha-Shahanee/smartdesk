import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getEmotionColor, getChartChrome } from '../theme/chartTheme';
import SampleDataBanner from '../components/SampleDataBanner';
import {
  CurrentEmotionSession,
  EmotionStatus,
  getCurrentEmotionSession,
  getEmotionStatus,
  startEmotionDetection,
  stopEmotionDetection,
} from '../services/api';
import './Insights.css';

type InsightTab = 'Focus Insights' | 'Stress Insights' | 'Pattern Detection';

// ---- Sample data for Focus ----
const focusTrend = [
  { day: 'Mon', score: 65 }, { day: 'Tue', score: 72 }, { day: 'Wed', score: 85 },
  { day: 'Thu', score: 78 }, { day: 'Fri', score: 58 }, { day: 'Sat', score: 5 }, { day: 'Sun', score: 3 },
];

const deepVsShallow = [
  { day: 'Mon', deep: 110, shallow: 170 }, { day: 'Tue', deep: 165, shallow: 140 },
  { day: 'Wed', deep: 220, shallow: 110 }, { day: 'Thu', deep: 180, shallow: 120 },
  { day: 'Fri', deep: 95, shallow: 215 }, { day: 'Sat', deep: 0, shallow: 0 }, { day: 'Sun', deep: 0, shallow: 0 },
];

// ---- Sample data for Stress ----
const stressThroughDay = [
  { time: '09:00', level: 25 }, { time: '10:00', level: 30 }, { time: '11:00', level: 28 },
  { time: '12:00', level: 45 }, { time: '13:00', level: 55 }, { time: '14:00', level: 40 },
  { time: '15:00', level: 35 }, { time: '16:00', level: 42 }, { time: '17:00', level: 50 },
];

const DETECTOR_EMOTIONS = ['Angry', 'Happy', 'Neutral', 'Surprise'];

// ---- Patterns ----
const patterns = [
  { type: 'negative', title: 'High context switching after meetings', description: 'You tend to switch between apps 3x more in the hour following meetings.' },
  { type: 'positive', title: 'Peak productivity mid-week', description: 'Your focus score is consistently 20% higher on Wednesday and Thursday.' },
  { type: 'negative', title: 'Low focus on Mondays', description: 'Monday mornings show 35% lower deep work time compared to other weekdays.' },
  { type: 'positive', title: 'Best focus window: 10 AM - 12 PM', description: 'Your highest quality work happens in late morning hours.' },
];

const formatSessionTime = (value?: string | null) => {
  if (!value) return 'Not started';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const sumEmotionScores = (session: CurrentEmotionSession | null) => {
  const totals = DETECTOR_EMOTIONS.reduce<Record<string, number>>((acc, emotion) => {
    acc[emotion] = 0;
    return acc;
  }, {});

  const blocks = session?.completed_blocks || session?.blocks || [];
  blocks.forEach(block => {
    DETECTOR_EMOTIONS.forEach(emotion => {
      totals[emotion] += Number(block.emotion_scores?.[emotion] || 0);
    });
  });

  return totals;
};

const Insights: React.FC = () => {
  const { theme } = useTheme();
  const chrome = getChartChrome(theme);
  const [activeTab, setActiveTab] = useState<InsightTab>('Focus Insights');
  const [emotionStatus, setEmotionStatus] = useState<EmotionStatus | null>(null);
  const [currentEmotionSession, setCurrentEmotionSession] = useState<CurrentEmotionSession | null>(null);
  const [emotionError, setEmotionError] = useState<string | null>(null);
  const [isEmotionLoading, setIsEmotionLoading] = useState(false);
  const [isStartingEmotion, setIsStartingEmotion] = useState(false);
  const [isStoppingEmotion, setIsStoppingEmotion] = useState(false);

  const refreshEmotionData = useCallback(async () => {
    setIsEmotionLoading(true);
    setEmotionError(null);
    try {
      const [status, session] = await Promise.all([
        getEmotionStatus(),
        getCurrentEmotionSession(),
      ]);
      setEmotionStatus(status);
      setCurrentEmotionSession(session);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Emotion backend is unavailable.';
      setEmotionError(message);
    } finally {
      setIsEmotionLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'Stress Insights') {
      refreshEmotionData();
    }
  }, [activeTab, refreshEmotionData]);

  useEffect(() => {
    if (activeTab !== 'Stress Insights' || !emotionStatus?.running) return;
    const intervalId = window.setInterval(refreshEmotionData, 15 * 60 * 1000);
    return () => window.clearInterval(intervalId);
  }, [activeTab, emotionStatus?.running, refreshEmotionData]);

  const handleStartEmotion = async () => {
    setIsStartingEmotion(true);
    setEmotionError(null);
    try {
      const result = await startEmotionDetection();
      setEmotionStatus(result?.status || result);
      await refreshEmotionData();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not start webcam detection.';
      setEmotionError(message);
    } finally {
      setIsStartingEmotion(false);
    }
  };

  const handleStopEmotion = async () => {
    setIsStoppingEmotion(true);
    setEmotionError(null);
    try {
      const result = await stopEmotionDetection();
      setEmotionStatus(result?.status || result);
      await refreshEmotionData();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not stop webcam detection.';
      setEmotionError(message);
    } finally {
      setIsStoppingEmotion(false);
    }
  };

  const emotionTotals = useMemo(
    () => sumEmotionScores(currentEmotionSession),
    [currentEmotionSession],
  );
  const emotionTotalValue = Object.values(emotionTotals).reduce((sum, value) => sum + value, 0);
  const detectorEmotionDistribution = DETECTOR_EMOTIONS.map(emotion => {
    const value = emotionTotals[emotion] || 0;
    const percent = emotionTotalValue > 0 ? Math.round((value / emotionTotalValue) * 100) : 0;
    const color =
      emotion === 'Angry' ? getCategoryColor('meetings', theme) :
      emotion === 'Happy' ? getCategoryColor('learn', theme) :
      emotion === 'Surprise' ? getCategoryColor('documentation', theme) :
      getEmotionColor('neutral', theme);

    return {
      name: emotion,
      value,
      percent,
      color,
    };
  });

  const statusLabel = emotionError
    ? 'Error'
    : emotionStatus?.running
      ? 'Running'
      : emotionStatus?.session_id
        ? 'Stopped'
        : 'Not running';
  const statusBadgeClass =
    statusLabel === 'Running' ? 'sd-badge--success' :
    statusLabel === 'Error' ? 'sd-badge--danger' :
    'sd-badge--warning';
  const completedBlocks = currentEmotionSession?.completed_blocks || currentEmotionSession?.blocks || [];

  return (
    <div className="insights-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Insights</h1>
        <p className="subtitle">Focus, stress and pattern analysis</p>
      </div>

      <SampleDataBanner what="Focus scoring and stress level" />

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

      {/* ---- Focus Insights ---- */}
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
            <span className="sd-alert-icon">📈</span>
            <div className="sd-alert-content">
              <h4>Key Finding</h4>
              <p>Your best focus window is between <strong>10:00 AM - 12:00 PM</strong>. During this time, your focus score averages 85/100 with minimal context switching.</p>
            </div>
          </div>
        </div>
      )}

      {/* ---- Stress Insights ---- */}
      {activeTab === 'Stress Insights' && (
        <div className="insights-content sd-fade-in">
          <div className="sd-card">
            <div className="stress-chart-header">
              <h3>Stress Level Throughout Day</h3>
              <div className="emotion-actions stress-chart-actions">
                <button
                  className="sd-btn sd-btn--primary"
                  onClick={handleStartEmotion}
                  disabled={Boolean(emotionStatus?.running) || isStartingEmotion}
                >
                  {isStartingEmotion ? 'Starting...' : 'Start Webcam Detection'}
                </button>
                <button
                  className="sd-btn sd-btn--danger"
                  onClick={handleStopEmotion}
                  disabled={!emotionStatus?.running || isStoppingEmotion}
                >
                  {isStoppingEmotion ? 'Stopping...' : 'Stop Webcam Detection'}
                </button>
              </div>
            </div>
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
              <div className="emotion-card-header">
                <h3>Webcam Emotion Detection Status</h3>
                <span className={`sd-badge ${statusBadgeClass}`}>{statusLabel}</span>
              </div>

              <div className="emotion-status-grid">
                <div>
                  <span>Session started</span>
                  <strong>{formatSessionTime(emotionStatus?.session_start_time)}</strong>
                </div>
                <div>
                  <span>Latest emotion</span>
                  <strong>{emotionStatus?.latest_emotion || 'Unknown'}</strong>
                </div>
                <div>
                  <span>Model</span>
                  <strong>{emotionStatus?.model_ready ? 'Ready' : 'Not ready'}</strong>
                </div>
                <div>
                  <span>Camera</span>
                  <strong>{emotionStatus?.camera_ready ? 'Ready' : 'Not ready'}</strong>
                </div>
              </div>

              {emotionError && (
                <div className="sd-alert sd-alert--warning emotion-inline-alert">
                  <span className="sd-alert-icon">!</span>
                  <div className="sd-alert-content">
                    <h4>Emotion backend unavailable</h4>
                    <p>The frontend is ready, but the emotion API endpoints are not responding yet.</p>
                  </div>
                </div>
              )}

              <button className="sd-view-details emotion-refresh" onClick={refreshEmotionData} disabled={isEmotionLoading}>
                {isEmotionLoading ? 'Refreshing...' : 'Refresh emotion data'}
              </button>
            </div>

            <div className="sd-card">
              <h3>Emotion Distribution Current Session</h3>
              {emotionTotalValue > 0 ? (
                <div className="donut-container">
                  <ResponsiveContainer width="50%" height={200}>
                    <PieChart>
                      <Pie data={detectorEmotionDistribution} dataKey="value" cx="50%" cy="50%" innerRadius={45} outerRadius={80} paddingAngle={2} strokeWidth={0}>
                        {detectorEmotionDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
                      </Pie>
                      <Tooltip
                        formatter={(value: number, name: string) => {
                          const item = detectorEmotionDistribution.find(emotion => emotion.name === name);
                          return [`${item?.percent || 0}%`, name];
                        }}
                        contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-legend">
                    {detectorEmotionDistribution.map((item, i) => (
                      <div className="legend-item" key={i}>
                        <span className="legend-dot" style={{ background: item.color }} />
                        <span className="legend-name">{item.name}</span>
                        <span className="legend-value">{item.percent}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="dash-empty emotion-empty">
                  {emotionStatus?.running
                    ? 'Detection is running. The first completed 15-minute block will appear here.'
                    : completedBlocks.length === 0
                      ? 'No completed emotion blocks for the current session yet.'
                      : 'No emotion scores are available for this session.'}
                </div>
              )}
              <p className="chart-note">Based on completed 15-minute blocks from the current emotion session.</p>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
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
                  <strong>Data Stays Local First</strong>
                  <p>Only session and 15-minute block summaries are sent when backend sync is enabled</p>
                </div>
              </div>
            </div>
          </div>

          <div className="sd-alert sd-alert--warning" style={{ marginTop: 'var(--space-xl)' }}>
            <span className="sd-alert-icon">⚠️</span>
            <div className="sd-alert-content">
              <h4>Elevated Stress After Lunch</h4>
              <p>Your stress levels increase by 40% between 1 PM - 3 PM. Consider scheduling less demanding tasks during this window.</p>
            </div>
          </div>
        </div>
      )}

      {/* ---- Pattern Detection ---- */}
      {activeTab === 'Pattern Detection' && (
        <div className="insights-content sd-fade-in">
          <div className="patterns-list">
            {patterns.map((p, i) => (
              <div key={i} className={`sd-alert ${p.type === 'positive' ? 'sd-alert--success' : 'sd-alert--danger'}`}>
                <span className="sd-alert-icon">{p.type === 'positive' ? '📈' : '📉'}</span>
                <div className="sd-alert-content">
                  <h4>{p.title}</h4>
                  <p>{p.description}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Pattern Analysis</h3>
            <p className="pattern-description">These patterns are detected by analyzing your activity over the past 30 days. Patterns are updated weekly based on new data.</p>
            <div className="sd-grid-3" style={{ marginTop: 'var(--space-xl)' }}>
              <div className="pattern-stat-card">
                <span className="pattern-stat-value">2</span>
                <span className="pattern-stat-label">Positive Patterns</span>
              </div>
              <div className="pattern-stat-card">
                <span className="pattern-stat-value">2</span>
                <span className="pattern-stat-label">Areas for Improvement</span>
              </div>
              <div className="pattern-stat-card">
                <span className="pattern-stat-value">30</span>
                <span className="pattern-stat-label">Days Analyzed</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Insights;
