import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { getSegmentsSummary, getSegmentsList } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import './Dashboard.css';

const CATEGORY_COLORS: Record<string, string> = {
  work: '#3366FF',
  learn: '#22C55E',
  communication: '#F59E0B',
  entertainment: '#EC4899',
  social_media: '#8B5CF6',
  system: '#94A3B8',
  meetings: '#EF4444',
  other: '#6366F1',
  documentation: '#14B8A6',
};

function capitalize(s: string) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
}

function formatDuration(sec: number) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

const Dashboard: React.FC = () => {
  const { selectedDate, refreshCount } = useDateContext();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const sumData = await getSegmentsSummary(selectedDate).catch(() => null);
        setSummary(sumData || { total_segments: 0, total_duration_sec: 0, count_by_category: {}, duration_by_category: {} });
      } catch {
        setSummary({ total_segments: 0, total_duration_sec: 0, count_by_category: {}, duration_by_category: {} });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [selectedDate, refreshCount]);

  if (loading) return <div className="sd-loader">Loading dashboard for {selectedDate}…</div>;

  const { total_duration_sec, duration_by_category } = summary;

  // Donut chart data
  const donutData = Object.keys(duration_by_category).length > 0
    ? Object.keys(duration_by_category).map(cat => ({
        name: capitalize(cat),
        value: duration_by_category[cat],
        color: CATEGORY_COLORS[cat] || '#94A3B8',
      }))
    : [{ name: 'No Activity', value: 1, color: '#E2E8F0' }];

  const activePercent = total_duration_sec > 0 ? Math.min(100, Math.round((total_duration_sec / (8 * 3600)) * 100)) : 0;
  const deepWorkSec = duration_by_category['work'] || 0;

  return (
    <div className="dashboard sd-fade-in">
      <div className="sd-page-header">
        <h1>Dashboard</h1>
        <p className="subtitle">{selectedDate} • Activity Overview</p>
      </div>

      <div className="hub-layout">
        {/* Hub Row 1: Recommendations (Full width) */}
        <div className="sd-card hub-card interactive" onClick={() => navigate('/recommendations')}>
          <div className="card-header">
            <h3><span className="card-icon">💡</span> Recommendations & Planning</h3>
            <span className="sd-view-details">View All Insights →</span>
          </div>
          <div className="hub-rec-preview">
            <div className="rec-insight-row">
              <span className="rec-icon-small green">↗</span>
              <div>
                <strong>Focus peak observed between 9:30–11:30</strong>
                <p>Your best work happened during late morning</p>
              </div>
            </div>
            <div className="rec-insight-row">
              <span className="rec-icon-small red">!</span>
              <div>
                <strong>High context switching detected after 1 PM</strong>
                <p>Consider blocking afternoon time for focused work</p>
              </div>
            </div>
          </div>
        </div>

        {/* Hub Row 2: Grid 2 (Timeline, Insights) */}
        <div className="sd-grid-2">
          {/* Timeline Summary */}
          <div className="sd-card hub-card interactive" onClick={() => navigate('/timeline')}>
            <div className="card-header">
              <h3><span className="card-icon">🕐</span> Daily Activity (Timeline)</h3>
              <span className="sd-view-details">View Timeline →</span>
            </div>
            <div className="activity-metrics">
              <div className="activity-row">
                <span className="metric-label">Total Active Time</span>
                <span className="metric-value">{formatDuration(total_duration_sec)}</span>
              </div>
              <div className="activity-row">
                <span className="metric-label">Deep Work Time</span>
                <span className="metric-value">{formatDuration(deepWorkSec)}</span>
              </div>
              <div className="activity-row">
                <span className="metric-label">Idle Time</span>
                <span className="metric-value">{formatDuration(Math.max(0, 8 * 3600 - total_duration_sec))}</span>
              </div>
            </div>
            <div className="sd-progress" style={{ marginTop: 16 }}>
              <div
                className="sd-progress-fill"
                style={{ width: `${activePercent}%`, background: 'var(--color-primary)' }}
              />
            </div>
          </div>

          {/* Insights Summary */}
          <div className="sd-card hub-card interactive" onClick={() => navigate('/insights')}>
            <div className="card-header">
              <h3><span className="card-icon">📊</span> Usage Breakdown (Insights)</h3>
              <span className="sd-view-details">View Insights →</span>
            </div>
            <div className="donut-container" style={{ gap: 'var(--space-md)' }}>
              <ResponsiveContainer width="50%" height={140}>
                <PieChart>
                  <Pie
                    data={donutData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={30}
                    outerRadius={60}
                    paddingAngle={2}
                    strokeWidth={0}
                  >
                    {donutData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: number) => formatDuration(value)}
                    contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0', fontSize: 13 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="donut-legend" style={{ gap: 'var(--space-xs)' }}>
                {donutData.slice(0, 4).map((item, i) => (
                  <div className="legend-item" key={i}>
                    <span className="legend-dot" style={{ background: item.color }} />
                    <span className="legend-name">{item.name}</span>
                    <span className="legend-value">{formatDuration(item.value)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Hub Row 3: Grid 2 (Prediction, Reports) */}
        <div className="sd-grid-2">
          {/* Prediction Summary */}
          <div className="sd-card hub-card interactive" onClick={() => navigate('/prediction')}>
            <div className="card-header">
              <h3><span className="card-icon">🔮</span> Task Prediction</h3>
              <span className="sd-view-details">View Predictions →</span>
            </div>
            <div className="hub-prediction-preview">
              <div className="pred-task-card-header">
                <h4>User Authentication Module</h4>
                <span className="pred-status-badge ongoing">ongoing</span>
              </div>
              <div className="pred-task-context">VS Code • auth-service.ts</div>
              <div className="pred-task-progress-row">
                <div className="pred-progress-track">
                  <div className="pred-progress-fill" style={{ width: '53%' }} />
                </div>
                <span className="pred-progress-pct">53%</span>
              </div>
              <p className="pred-subtext" style={{ marginTop: 'var(--space-sm)' }}>
                Predicted Total: 4h 0m • Remaining: 1h 53m
              </p>
            </div>
          </div>

          {/* Reports Summary */}
          <div className="sd-card hub-card interactive" onClick={() => navigate('/report')}>
            <div className="card-header">
              <h3><span className="card-icon">📑</span> Weekly Reports</h3>
              <span className="sd-view-details">View Reports →</span>
            </div>
            <div className="hub-report-preview">
              <div className="report-doc-icon">📄</div>
              <div>
                <h4>Latest Auto-generated Report</h4>
                <p>Summary of Week 6 (Feb 2 - Feb 8)</p>
                <span style={{ fontSize: 12, color: 'var(--color-primary)', fontWeight: 500 }}>Ready to view</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;