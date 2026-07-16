import React, { useState } from 'react';
import './Prediction.css';

const MOCK_TASKS = [
  {
    id: 1,
    title: 'User Authentication Module',
    context: 'VS Code • auth-service.ts',
    status: 'ongoing',
    progress: 53,
    started: '2026-02-10 09:15',
    lastActive: '2 min ago',
    timeSpent: '2h 7m',
    predictedTotal: '4h 0m',
    confidence: 'high',
    remaining: '1h 53m',
    trendTitle: 'Progress is steady',
    trendSubtitle: 'Maintaining consistent pace'
  },
  {
    id: 2,
    title: 'API Integration - Payment Gateway',
    context: 'VS Code • payment-api.ts',
    status: 'paused',
    progress: 47,
    started: '2026-02-10 11:30',
    lastActive: '1 hr ago',
    timeSpent: '1h 45m',
    predictedTotal: '3h 30m',
    confidence: 'medium',
    remaining: '1h 45m',
    trendTitle: 'Slightly behind schedule',
    trendSubtitle: 'Context switching detected'
  },
  {
    id: 3,
    title: 'Database Schema Migration',
    context: 'Terminal • migrations/',
    status: 'ongoing',
    progress: 47,
    started: '2026-02-10 13:00',
    lastActive: 'Just now',
    timeSpent: '45m',
    predictedTotal: '1h 30m',
    confidence: 'high',
    remaining: '45m',
    trendTitle: 'Faster than expected',
    trendSubtitle: 'No interruptions'
  },
  {
    id: 4,
    title: 'Code Review - Feature/notifications',
    context: 'GitHub • PR #234',
    status: 'completed',
    progress: 93,
    started: '2026-02-10 08:00',
    lastActive: '3 hrs ago',
    timeSpent: '45m',
    predictedTotal: '45m',
    confidence: 'high',
    remaining: '0m',
    trendTitle: 'Completed efficiently',
    trendSubtitle: 'Done within predicted window'
  }
];

const Prediction: React.FC = () => {
  const [selectedTaskId, setSelectedTaskId] = useState(MOCK_TASKS[0].id);
  const selectedTask = MOCK_TASKS.find(t => t.id === selectedTaskId) || MOCK_TASKS[0];

  return (
    <div className="prediction-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Prediction</h1>
        <p className="subtitle">Task-level time forecasting and progress tracking</p>
      </div>

      <div className="pred-layout">
        {/* Left Sidebar */}
        <div className="pred-sidebar">
          <h3 className="pred-sidebar-title">Detected Tasks</h3>
          <div className="pred-task-list">
            {MOCK_TASKS.map(task => (
              <div 
                key={task.id} 
                className={`pred-task-card ${selectedTaskId === task.id ? 'active' : ''}`}
                onClick={() => setSelectedTaskId(task.id)}
              >
                <div className="pred-task-card-header">
                  <h4>{task.title}</h4>
                  <span className={`pred-status-badge ${task.status}`}>{task.status}</span>
                </div>
                <div className="pred-task-context">{task.context}</div>
                <div className="pred-task-progress-row">
                  <div className="pred-progress-track">
                    <div 
                      className="pred-progress-fill" 
                      style={{ width: `${task.progress}%` }} 
                    />
                  </div>
                  <span className="pred-progress-pct">{task.progress}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Main View */}
        <div className="pred-main">
          <div className="sd-card pred-detail-card">
            <div className="pred-detail-header">
              <h2>{selectedTask.title}</h2>
              <span className={`pred-status-badge ${selectedTask.status}`}>{selectedTask.status}</span>
            </div>
            
            <div className="pred-detail-meta">
              {selectedTask.context} &nbsp;•&nbsp; Started {selectedTask.started} &nbsp;•&nbsp; Last active {selectedTask.lastActive}
            </div>

            <div className="pred-detail-progress">
              <div className="pred-detail-progress-label">
                <span>Progress</span>
                <span>{selectedTask.progress}%</span>
              </div>
              <div className="pred-progress-track large">
                <div 
                  className="pred-progress-fill" 
                  style={{ width: `${selectedTask.progress}%` }} 
                />
              </div>
            </div>
          </div>

          <div className="pred-stats-grid">
            <div className="sd-card pred-stat-card">
              <span className="pred-stat-label">Time Spent</span>
              <span className="pred-stat-value">{selectedTask.timeSpent}</span>
              <span className="pred-stat-sub">Actual time invested</span>
            </div>
            <div className="sd-card pred-stat-card">
              <span className="pred-stat-label">Predicted Total</span>
              <span className="pred-stat-value">{selectedTask.predictedTotal}</span>
              <span className={`pred-stat-sub confidence ${selectedTask.confidence}`}>
                <span className="confidence-dot"></span> {selectedTask.confidence} confidence
              </span>
            </div>
            <div className="sd-card pred-stat-card">
              <span className="pred-stat-label">Remaining</span>
              <span className="pred-stat-value">{selectedTask.remaining}</span>
              <span className="pred-stat-sub">Estimated time left</span>
            </div>
          </div>

          <div className="sd-card pred-trend-card">
            <span className="pred-stat-label">Progress Trend</span>
            <div className="pred-trend-content">
              <span className="trend-dash">-</span>
              <div>
                <strong>{selectedTask.trendTitle}</strong>
                <p>{selectedTask.trendSubtitle}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Prediction;
