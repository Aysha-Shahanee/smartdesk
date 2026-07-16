import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line,
} from 'recharts';
import { getSegmentsSummary } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import './Report.css';

type ReportTab = 'Daily Report' | 'Weekly Report' | 'Monthly Report';

// ---- Sample Weekly Data ----
const weeklyFocusPattern = [
  { day: 'Mon', score: 65 }, { day: 'Tue', score: 72 }, { day: 'Wed', score: 85 },
  { day: 'Thu', score: 77 }, { day: 'Fri', score: 58 },
];

// ---- Sample Monthly Data ----
const monthlyTrends = [
  { week: 'Week 1', focus: 68, deepWork: 58, stress: 42 },
  { week: 'Week 2', focus: 75, deepWork: 65, stress: 38 },
  { week: 'Week 3', focus: 72, deepWork: 61, stress: 41 },
  { week: 'Week 4', focus: 78, deepWork: 69, stress: 36 },
];

function formatDuration(sec: number) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

const Report: React.FC = () => {
  const { selectedDate } = useDateContext();
  const [activeTab, setActiveTab] = useState<ReportTab>('Daily Report');
  const [reportData, setReportData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        setLoading(true);
        const data = await getSegmentsSummary(selectedDate);
        setReportData(data);
      } catch {
        // Use sample data
        setReportData({
          total_segments: 42,
          total_duration_sec: 22320,
          count_by_category: { work: 18, learn: 6, communication: 5, entertainment: 4 },
          duration_by_category: { work: 16320, learn: 2400, communication: 1200, entertainment: 900 },
        });
      } finally {
        setLoading(false);
      }
    };
    fetchReport();
  }, []);

  const handleExport = () => {
    if (!reportData) return;
    const rows = [['Category', 'Count', 'Duration (s)', 'Hours']];
    Object.keys(reportData.count_by_category || {}).forEach(cat => {
      const count = reportData.count_by_category[cat] || 0;
      const dur = reportData.duration_by_category[cat] || 0;
      rows.push([cat, count.toString(), dur.toString(), (dur / 3600).toFixed(2)]);
    });
    rows.push(['TOTAL', (reportData.total_segments || 0).toString(), (reportData.total_duration_sec || 0).toString(), ((reportData.total_duration_sec || 0) / 3600).toFixed(2)]);
    const csv = rows.map(r => r.map(v => `"${v}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `smartdesk_report_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <div className="sd-loader">Loading reports…</div>;

  const deepWorkSec = reportData?.duration_by_category?.['work'] || 11220;
  const focusScore = 78;
  const stressLevel = 42;
  const contextSwitches = reportData?.total_segments ? reportData.total_segments - 1 : 24;

  return (
    <div className="report-page sd-fade-in">
      {/* Header */}
      <div className="report-header">
        <h1>Reports (Sample)</h1>
        <button className="sd-btn" onClick={handleExport}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
          Export Report
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

      {/* ---- Daily Report ---- */}
      {activeTab === 'Daily Report' && (
        <div className="report-content sd-fade-in">
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Focus Score</span>
              <span className="metric-card-value">{focusScore}</span>
              <span className="sd-badge sd-badge--success">+5 from yesterday</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Deep Work</span>
              <span className="metric-card-value">{formatDuration(deepWorkSec)}</span>
              <span className="sd-badge sd-badge--success">+22min from yesterday</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Stress Level</span>
              <span className="metric-card-value">{stressLevel}</span>
              <span className="sd-badge sd-badge--danger">+8 from yesterday</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Context Switches</span>
              <span className="metric-card-value">{contextSwitches}</span>
              <span className="sd-badge sd-badge--success">-3 from yesterday</span>
            </div>
          </div>

          {/* Category breakdown table */}
          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Category Breakdown</h3>
            <table className="report-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Segments</th>
                  <th>Duration</th>
                  <th>% of Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(reportData?.count_by_category || {}).map(cat => {
                  const count = reportData.count_by_category[cat] || 0;
                  const dur = reportData.duration_by_category[cat] || 0;
                  const pct = reportData.total_duration_sec > 0 ? Math.round((dur / reportData.total_duration_sec) * 100) : 0;
                  return (
                    <tr key={cat}>
                      <td style={{ textTransform: 'capitalize' }}>{cat.replace(/_/g, ' ')}</td>
                      <td>{count}</td>
                      <td>{formatDuration(dur)}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div className="sd-progress" style={{ width: 80 }}>
                            <div className="sd-progress-fill" style={{ width: `${pct}%`, background: 'var(--color-primary)' }} />
                          </div>
                          {pct}%
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ---- Weekly Report ---- */}
      {activeTab === 'Weekly Report' && (
        <div className="report-content sd-fade-in">
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Avg Focus Score</span>
              <span className="metric-card-value">72</span>
              <span className="sd-badge sd-badge--success">+12% from last week</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Total Deep Work</span>
              <span className="metric-card-value">12h</span>
              <span className="metric-card-sub">57m this week</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Avg Stress</span>
              <span className="metric-card-value">38</span>
              <span className="sd-badge sd-badge--success">-4 from last week</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Best Day</span>
              <span className="metric-card-value">Wednesday</span>
              <span className="metric-card-sub">Focus: 85/100</span>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Daily Focus Pattern (This Week)</h3>
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={weeklyFocusPattern}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                <Bar dataKey="score" fill="#3366FF" radius={[6, 6, 0, 0]} barSize={60} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
            <div className="sd-alert sd-alert--success">
              <span className="sd-alert-icon">📈</span>
              <div className="sd-alert-content">
                <h4>Positive Trend</h4>
                <p>Your focus improved by 12% this week. Wednesday was your most productive day.</p>
              </div>
            </div>
            <div className="sd-alert sd-alert--warning">
              <span className="sd-alert-icon">📅</span>
              <div className="sd-alert-content">
                <h4>Opportunity</h4>
                <p>Friday showed lower focus. Consider scheduling less demanding tasks for end of week.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ---- Monthly Report ---- */}
      {activeTab === 'Monthly Report' && (
        <div className="report-content sd-fade-in">
          <div className="sd-grid-3">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Monthly Average Focus</span>
              <span className="metric-card-value">72</span>
              <span className="sd-badge sd-badge--success">+8 from last month</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Total Deep Work Hours</span>
              <span className="metric-card-value">52h</span>
              <span className="sd-badge sd-badge--success">+6h from last month</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Productivity Trend</span>
              <span className="metric-card-value" style={{ color: 'var(--color-success)' }}>📈 Improving</span>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Monthly Trends (4 Weeks)</h3>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={monthlyTrends}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="week" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis yAxisId="left" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                <Line yAxisId="left" type="monotone" dataKey="focus" stroke="#3366FF" strokeWidth={2} dot={{ r: 4 }} name="Focus Score" />
                <Line yAxisId="left" type="monotone" dataKey="deepWork" stroke="#22C55E" strokeWidth={2} dot={{ r: 4 }} name="Deep Work (h)" />
                <Line yAxisId="left" type="monotone" dataKey="stress" stroke="#EF4444" strokeWidth={2} dot={{ r: 4 }} name="Stress Level" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Long-term Analysis</h3>
            <div className="longterm-list">
              <div className="sd-alert sd-alert--success">
                <div className="sd-alert-content">
                  <h4>Consistent Improvement</h4>
                  <p>Your focus score has increased steadily over the past month, with Week 4 showing the best performance at 76/100.</p>
                </div>
              </div>
              <div className="sd-alert sd-alert--info">
                <div className="sd-alert-content">
                  <h4>Stress Management</h4>
                  <p>Stress levels have decreased by 14% this month. Your stress management strategies appear to be working well.</p>
                </div>
              </div>
              <div className="sd-alert sd-alert--purple">
                <div className="sd-alert-content">
                  <h4>Deep Work Growth</h4>
                  <p>Deep work time increased by 17% from Week 1 to Week 4. You're successfully protecting more time for focused work.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Report;