import { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import { getSegmentsList, recordCorrection, getCalendarEvents } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { ChangeLabelTable } from '../components/ChangeLabelTable';
import './Timeline.css';

const CATEGORIES = [
  'work', 'learn', 'communication', 'entertainment',
  'social_media', 'system', 'meetings', 'documentation', 'other',
];

const CATEGORY_COLORS: Record<string, string> = {
  work: '#3366FF', learn: '#22C55E', communication: '#F59E0B',
  entertainment: '#EC4899', social_media: '#8B5CF6', system: '#94A3B8',
  meetings: '#EF4444', documentation: '#14B8A6', other: '#6366F1',
};

const SUB_TABS = ['IDE', 'Browser', 'OS / Apps', 'Calendar', 'Emotion'] as const;
type SubTab = typeof SUB_TABS[number];

const TAB_ICONS: Record<SubTab, string> = {
  IDE: '💻', Browser: '🌐', 'OS / Apps': '⌨️', Calendar: '📅', Emotion: '😊',
};

// Map sub-tabs to which app_names are relevant
const TAB_FILTER: Record<SubTab, (seg: any) => boolean> = {
  IDE: (s) => {
    const name = (s.app_name || '').toLowerCase();
    return ['code', 'vs code', 'visual studio', 'intellij', 'pycharm', 'webstorm', 'sublime', 'atom', 'vim', 'neovim', 'cursor'].some(k => name.includes(k));
  },
  Browser: (s) => {
    const name = (s.app_name || '').toLowerCase();
    return ['chrome', 'firefox', 'edge', 'safari', 'brave', 'opera', 'browser'].some(k => name.includes(k));
  },
  'OS / Apps': () => true,
  Calendar: (s) => {
    const cat = (s.predicted_category || s.correction_label || '').toLowerCase();
    return cat === 'meetings';
  },
  Emotion: () => true,
};

function capitalize(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ') : '';
}

function formatDuration(sec: number) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatTime(isoStr: string) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

// ---- Sample fallback segments ----
const SAMPLE_SEGMENTS = [
  { id: 's1', app_name: 'VS Code', title: 'smartdesk - App.tsx', predicted_category: 'work', predicted_confidence: 0.92, correction_label: null, start_time_utc: '2026-07-15T03:30:00Z', end_time_utc: '2026-07-15T04:15:00Z', detail: 'TypeScript' },
  { id: 's2', app_name: 'VS Code', title: 'smartdesk - Timeline.tsx', predicted_category: 'work', predicted_confidence: 0.88, correction_label: null, start_time_utc: '2026-07-15T04:45:00Z', end_time_utc: '2026-07-15T06:00:00Z', detail: 'TypeScript' },
  { id: 's3', app_name: 'Chrome', title: 'Stack Overflow - React hooks', predicted_category: 'learn', predicted_confidence: 0.78, correction_label: null, start_time_utc: '2026-07-15T04:15:00Z', end_time_utc: '2026-07-15T04:45:00Z', detail: 'stackoverflow.com' },
  { id: 's4', app_name: 'Chrome', title: 'GitHub - smartdesk repo', predicted_category: 'work', predicted_confidence: 0.85, correction_label: null, start_time_utc: '2026-07-15T06:00:00Z', end_time_utc: '2026-07-15T06:15:00Z', detail: 'github.com' },
  { id: 's5', app_name: 'VS Code', title: 'smartdesk - Dashboard.tsx', predicted_category: 'work', predicted_confidence: 0.95, correction_label: null, start_time_utc: '2026-07-15T08:15:00Z', end_time_utc: '2026-07-15T10:00:00Z', detail: 'TypeScript' },
  { id: 's6', app_name: 'Teams', title: 'Team Standup', predicted_category: 'meetings', predicted_confidence: 0.98, correction_label: null, start_time_utc: '2026-07-15T06:00:00Z', end_time_utc: '2026-07-15T06:30:00Z', detail: null },
  { id: 's7', app_name: 'Chrome', title: 'YouTube - React Tutorial', predicted_category: 'entertainment', predicted_confidence: 0.62, correction_label: null, start_time_utc: '2026-07-15T07:45:00Z', end_time_utc: '2026-07-15T08:15:00Z', detail: 'youtube.com' },
  { id: 's8', app_name: 'VS Code', title: 'smartdesk - api.ts', predicted_category: 'work', predicted_confidence: 0.91, correction_label: null, start_time_utc: '2026-07-15T10:30:00Z', end_time_utc: '2026-07-15T11:45:00Z', detail: 'TypeScript' },
];

const Timeline: React.FC = () => {
  const { selectedDate: date, refreshCount } = useDateContext();
  const [allSegments, setAllSegments] = useState<any[]>([]);
  const [calendarEvents, setCalendarEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<SubTab>('IDE');
  const [period, setPeriod] = useState<'Day' | 'Week' | 'Month'>('Day');
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');

  // ---- Fetch segments (base truth) and calendar ----
  const fetchSegments = async () => {
    setLoading(true);
    try {
      let fromDate = date;
      let toDate = date;
      if (period === 'Week') {
        const d = new Date(date);
        d.setDate(d.getDate() + 7);
        toDate = d.toISOString().split('T')[0];
      } else if (period === 'Month') {
        const d = new Date(date);
        d.setMonth(d.getMonth() + 1);
        toDate = d.toISOString().split('T')[0];
      }

      const [segData, calData] = await Promise.all([
        getSegmentsList(date).catch(() => null),
        getCalendarEvents(fromDate, toDate).catch(() => null),
      ]);
      setAllSegments(segData?.segments?.length ? segData.segments : []);
      setCalendarEvents(calData?.events || []);
    } catch {
      setAllSegments([]);
      setCalendarEvents([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSegments(); }, [date, period, refreshCount]);

  // Filter segments by active tab
  const filteredSegments = useMemo(() => {
    return allSegments.filter(TAB_FILTER[activeTab]);
  }, [allSegments, activeTab]);

  // ---- Derived data for charts ----
  const hourlyData = useMemo(() => {
    const hours: Record<number, { active: number; idle: number }> = {};
    for (let h = 9; h <= 17; h++) hours[h] = { active: 0, idle: 60 };
    filteredSegments.forEach(seg => {
      try {
        const start = new Date(seg.start_time_utc);
        const end = new Date(seg.end_time_utc);
        const dur = (end.getTime() - start.getTime()) / 60000;
        const hour = start.getHours();
        if (hours[hour]) {
          hours[hour].active += Math.min(60, dur);
          hours[hour].idle = Math.max(0, 60 - hours[hour].active);
        }
      } catch { /* skip */ }
    });
    return Object.entries(hours).map(([h, v]) => ({
      hour: `${h}:00`,
      Active: Math.round(v.active),
      Idle: Math.round(v.idle),
    }));
  }, [filteredSegments]);

  const categoryDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    filteredSegments.forEach(seg => {
      const cat = seg.correction_label || seg.predicted_category || 'other';
      counts[cat] = (counts[cat] || 0) + 1;
    });
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(counts).map(([name, value]) => ({
      name: capitalize(name),
      value,
      percent: Math.round((value / total) * 100),
      color: CATEGORY_COLORS[name] || '#94A3B8',
    }));
  }, [filteredSegments]);

  // Summary stats
  const summaryStats = useMemo(() => {
    if (filteredSegments.length === 0) return { topItem: '—', activeWindow: '—', totalDuration: '0m', fileCount: 0 };
    const catCount: Record<string, number> = {};
    let totalSec = 0;
    filteredSegments.forEach(seg => {
      const detail = seg.detail || seg.app_name || 'Unknown';
      catCount[detail] = (catCount[detail] || 0) + 1;
      try {
        totalSec += (new Date(seg.end_time_utc).getTime() - new Date(seg.start_time_utc).getTime()) / 1000;
      } catch { /* skip */ }
    });
    const topItem = Object.entries(catCount).sort((a, b) => b[1] - a[1])[0]?.[0] || '—';
    // Find most active window
    let maxDur = 0, activeWindowStr = '—';
    filteredSegments.forEach(seg => {
      try {
        const dur = (new Date(seg.end_time_utc).getTime() - new Date(seg.start_time_utc).getTime()) / 1000;
        if (dur > maxDur) { maxDur = dur; activeWindowStr = `${formatTime(seg.start_time_utc)} - ${formatTime(seg.end_time_utc)}`; }
      } catch { /* skip */ }
    });
    return { topItem, activeWindow: activeWindowStr, totalDuration: formatDuration(totalSec), fileCount: filteredSegments.length };
  }, [filteredSegments]);

  const flameData = useMemo(() => {
    if (filteredSegments.length === 0) return { minTime: 0, maxTime: 1 };
    let minT = Infinity, maxT = -Infinity;
    
    filteredSegments.forEach(seg => {
      try {
        const st = new Date(seg.start_time_utc).getTime();
        const et = new Date(seg.end_time_utc).getTime();
        if (st < minT) minT = st;
        if (et > maxT) maxT = et;
      } catch { /* skip */ }
    });
    
    if (minT === Infinity) return { minTime: 0, maxTime: 1 };
    // Pad bounds slightly (5 minutes)
    minT -= 5 * 60000;
    maxT += 5 * 60000;
    
    return { minTime: minT, maxTime: maxT };
  }, [filteredSegments]);

  // Summary label names per tab
  const summaryLabels = {
    IDE: ['Most Used Language', 'Most Active Window', 'Total Coding Duration', 'Files Edited'],
    Browser: ['Most Visited Category', 'Most Active Window', 'Total Duration', 'Tabs Switched'],
    'OS / Apps': ['Most Used App', 'Most Active Window', 'Total Duration', 'Apps Used'],
    Calendar: ['Meetings Today', 'Next Meeting', 'Total Meeting Time', 'Free Blocks'],
    Emotion: ['Dominant Emotion', 'Stress Peaks', 'Calm Periods', 'Readings'],
  };

  // Distribution chart title per tab
  const distTitle: Record<SubTab, string> = {
    IDE: 'Language Distribution',
    Browser: 'Category Distribution',
    'OS / Apps': 'App Distribution',
    Calendar: 'Meeting Types',
    Emotion: 'Emotion Distribution',
  };

  // ---- Change Label Handler ----
  const handleSaveLabel = async (segmentId: string) => {
    if (!editLabel) return;
    setSaving(prev => new Set([...prev, segmentId]));
    try {
      await recordCorrection(segmentId, editLabel);
      setAllSegments(prev =>
        prev.map(seg => seg.id === segmentId ? { ...seg, correction_label: editLabel, predicted_category: editLabel } : seg)
      );
      setEditingId(null);
      setEditLabel('');
    } catch (err) {
      console.error('Failed to save correction:', err);
    } finally {
      setSaving(prev => new Set([...prev].filter(id => id !== segmentId)));
    }
  };

  if (loading) return <div className="sd-loader">Loading timeline…</div>;

  return (
    <div className="timeline-page sd-fade-in">
      {/* Header */}
      <div className="timeline-header">
        <div>
          <h1>Activity Timeline</h1>
          <p className="subtitle">Source-based activity analysis</p>
        </div>
        <div className="timeline-controls">
          <div className="period-toggle">
            <button className={`sd-btn ${period === 'Day' ? 'sd-btn--primary active' : ''}`} onClick={() => setPeriod('Day')}>Day</button>
            <button className={`sd-btn ${period === 'Week' ? 'sd-btn--primary active' : ''}`} onClick={() => setPeriod('Week')}>Week</button>
            <button className={`sd-btn ${period === 'Month' ? 'sd-btn--primary active' : ''}`} onClick={() => setPeriod('Month')}>Month</button>
          </div>
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="sd-tabs">
        {SUB_TABS.map(tab => (
          <button
            key={tab}
            className={`sd-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_ICONS[tab]} {tab}
          </button>
        ))}
      </div>

      {/* Calendar Tab — special layout */}
      {activeTab === 'Calendar' ? (
        <div className="calendar-section">
          <div className="sd-card">
            <h3>Meeting Timeline</h3>
            {calendarEvents.length > 0 ? (
              <div className="meeting-list">
                {calendarEvents.map(evt => (
                  <div key={evt.event_id} className="meeting-item">
                    <span className="meeting-time">
                      {new Date(evt.start_time).toLocaleDateString()} {formatTime(evt.start_time)} - {formatTime(evt.end_time)}
                    </span>
                    <div className="meeting-info">
                      <strong>{evt.title || 'Untitled Event'}</strong>
                      <span>{Math.round(evt.duration_sec / 60)} minutes • {evt.is_all_day ? 'All Day' : 'Scheduled'}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="meeting-list">
                <p style={{ color: 'var(--color-text-muted)', padding: 20, textAlign: 'center' }}>No calendar events found for this {period.toLowerCase()}.</p>
              </div>
            )}
            <div className="sd-alert sd-alert--info" style={{ marginTop: 20 }}>
              <div className="sd-alert-content">
                <p>Only meeting times are tracked. No content, attendees, or descriptions are stored.</p>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Summary Row */}
          <div className="sd-card summary-card">
            <h3>Summary</h3>
            <div className="summary-grid">
              <div className="summary-stat">
                <span className="summary-stat-label">{summaryLabels[activeTab][0]}</span>
                <span className="summary-stat-value">{summaryStats.topItem}</span>
              </div>
              <div className="summary-stat">
                <span className="summary-stat-label">{summaryLabels[activeTab][1]}</span>
                <span className="summary-stat-value">{summaryStats.activeWindow}</span>
              </div>
              <div className="summary-stat">
                <span className="summary-stat-label">{summaryLabels[activeTab][2]}</span>
                <span className="summary-stat-value">{summaryStats.totalDuration}</span>
              </div>
              <div className="summary-stat">
                <span className="summary-stat-label">{summaryLabels[activeTab][3]}</span>
                <span className="summary-stat-value">{summaryStats.fileCount}</span>
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
            {/* Active vs Idle */}
            <div className="sd-card">
              <div className="card-header">
                <h3>Active vs Idle Time</h3>
                <span className="sd-view-details" style={{ color: 'var(--color-primary)' }}>Expand</span>
              </div>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={hourlyData} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                  <XAxis dataKey="hour" tick={{ fontSize: 12, fill: '#94A3B8' }} />
                  <YAxis tick={{ fontSize: 12, fill: '#94A3B8' }} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0', fontSize: 13 }} />
                  <Bar dataKey="Active" fill="#22C55E" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="Idle" fill="#E2E8F0" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Distribution Pie */}
            <div className="sd-card">
              <div className="card-header">
                <h3>{distTitle[activeTab]}</h3>
                <span className="sd-view-details" style={{ color: 'var(--color-primary)' }}>Expand</span>
              </div>
              <div className="donut-container">
                <ResponsiveContainer width="45%" height={200}>
                  <PieChart>
                    <Pie data={categoryDistribution} dataKey="value" cx="50%" cy="50%" outerRadius={80} strokeWidth={0}>
                      {categoryDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0', fontSize: 13 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="donut-legend">
                  {categoryDistribution.map((item, i) => (
                    <div className="legend-item" key={i}>
                      <span className="legend-dot" style={{ background: item.color }} />
                      <span className="legend-name">{item.name}</span>
                      <span className="legend-value">{item.percent}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Timeline View — flame chart */}
          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Timeline View</h3>
            <div className="flame-chart-container">
              {filteredSegments.length === 0 ? (
                <p style={{ color: 'var(--color-text-muted)', padding: 20, textAlign: 'center' }}>No activity data for this tab and date.</p>
              ) : (
                <div className="flame-tracks">
                  <div className="flame-track-row">
                    <div className="flame-track-area" style={{ height: '32px' }}>
                      {filteredSegments.map(seg => {
                        const st = new Date(seg.start_time_utc).getTime();
                        const et = new Date(seg.end_time_utc).getTime();
                        const leftPct = ((st - flameData.minTime) / (flameData.maxTime - flameData.minTime)) * 100;
                        const widthPct = Math.max(0.3, ((et - st) / (flameData.maxTime - flameData.minTime)) * 100);
                        const color = CATEGORY_COLORS[seg.correction_label || seg.predicted_category] || '#94A3B8';
                        const durMin = Math.round((et - st) / 60000);
                        const tooltip = `${seg.title || seg.app_name}\n${formatTime(seg.start_time_utc)} - ${formatTime(seg.end_time_utc)}\n${durMin}m\n${seg.predicted_category}`;
                        return (
                          <div 
                            key={seg.id}
                            className="flame-segment"
                            style={{ left: `${leftPct}%`, width: `${widthPct}%`, backgroundColor: color }}
                            title={tooltip}
                          />
                        );
                      })}
                    </div>
                  </div>
                  {/* Time axis marks */}
                  <div className="flame-axis" style={{ marginLeft: 0 }}>
                    <span style={{ position: 'absolute', left: '0%' }}>{new Date(flameData.minTime).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                    <span style={{ position: 'absolute', left: '50%', transform: 'translateX(-50%)' }}>{new Date((flameData.minTime + flameData.maxTime) / 2).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                    <span style={{ position: 'absolute', right: '0%' }}>{new Date(flameData.maxTime).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ============================================ */}
      {/* CHANGE LABEL UI — Rendered only on OS tab    */}
      {/* ============================================ */}
      {activeTab === 'OS / Apps' && (
        <div style={{ marginTop: 'var(--space-2xl)' }}>
          <ChangeLabelTable />
        </div>
      )}
    </div>
  );
};

export default Timeline;