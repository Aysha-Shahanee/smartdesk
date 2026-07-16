import { useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell,
} from 'recharts';
import { useDateContext } from '../contexts/DateContext';
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

const emotionDistribution = [
  { name: 'Calm', value: 45, color: '#22C55E' },
  { name: 'Focused', value: 18, color: '#3366FF' },
  { name: 'Neutral', value: 32, color: '#94A3B8' },
  { name: 'Stressed', value: 5, color: '#EF4444' },
];

// ---- Patterns ----
const patterns = [
  { type: 'negative', title: 'High context switching after meetings', description: 'You tend to switch between apps 3x more in the hour following meetings.' },
  { type: 'positive', title: 'Peak productivity mid-week', description: 'Your focus score is consistently 20% higher on Wednesday and Thursday.' },
  { type: 'negative', title: 'Low focus on Mondays', description: 'Monday mornings show 35% lower deep work time compared to other weekdays.' },
  { type: 'positive', title: 'Best focus window: 10 AM - 12 PM', description: 'Your highest quality work happens in late morning hours.' },
];

const Insights: React.FC = () => {
  const { selectedDate } = useDateContext();
  const [activeTab, setActiveTab] = useState<InsightTab>('Focus Insights');

  return (
    <div className="insights-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Insights (Sample)</h1>
        <p className="subtitle">Actionable analysis of your activity for {selectedDate}</p>
      </div>

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
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                <Line type="monotone" dataKey="score" stroke="#3366FF" strokeWidth={2.5} dot={{ r: 4, fill: '#3366FF' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Deep Work vs Shallow Work (Minutes)</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={deepVsShallow} barGap={4}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                <Bar dataKey="deep" fill="#22C55E" radius={[4, 4, 0, 0]} name="Deep Work" />
                <Bar dataKey="shallow" fill="#F59E0B" radius={[4, 4, 0, 0]} name="Shallow Work" />
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
            <h3>Stress Level Throughout Day</h3>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={stressThroughDay}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
                <XAxis dataKey="time" tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: '#94A3B8' }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                <Line type="monotone" dataKey="level" stroke="#EF4444" strokeWidth={2.5} dot={{ r: 4, fill: '#EF4444' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
            <div className="sd-card">
              <h3>Emotion Distribution</h3>
              <div className="donut-container" style={{ justifyContent: 'center' }}>
                <ResponsiveContainer width="55%" height={220}>
                  <PieChart>
                    <Pie data={emotionDistribution} dataKey="value" cx="50%" cy="50%" outerRadius={85} strokeWidth={0} label={({ name, value }) => `${name}: ${value}%`}>
                      {emotionDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E2E8F0' }} />
                  </PieChart>
                </ResponsiveContainer>
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