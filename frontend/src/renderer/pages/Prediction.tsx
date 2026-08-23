import React, { useEffect, useState } from 'react';
import { useDateContext } from '../contexts/DateContext';
import {
  getGitHubActiveTasks,
  GitHubActiveTask,
} from '../services/api';
import {
  formatHoursAsDuration,
  formatTimeSpent,
  getRemainingEstimateStatus,
} from '../utils/timeSpent.mjs';
import './Prediction.css';

const REFRESH_INTERVAL_MS = 15_000;

const formatStartedAt = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatInitialPrediction = (hours?: number) =>
  hours === undefined || hours === null ? 'Unavailable' : `${hours.toFixed(1)} hours`;

const Prediction: React.FC = () => {
  const { refreshCount } = useDateContext();
  const [tasks, setTasks] = useState<GitHubActiveTask[]>([]);
  const [selectedTaskIndex, setSelectedTaskIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const load = async (showLoading = false) => {
      if (showLoading) setLoading(true);
      try {
        const response = await getGitHubActiveTasks();
        if (!cancelled) {
          setTasks(response.tasks || []);
          setError('');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load active GitHub tasks');
        }
      } finally {
        if (!cancelled && showLoading) setLoading(false);
      }
    };

    load(true);
    const interval = window.setInterval(() => load(false), REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshCount]);

  useEffect(() => {
    if (selectedTaskIndex >= tasks.length) setSelectedTaskIndex(0);
  }, [selectedTaskIndex, tasks.length]);

  const selectedTask = tasks[selectedTaskIndex];

  if (loading) {
    return (
      <div className="prediction-page sd-fade-in">
        <div className="sd-page-header">
          <h1>Prediction</h1>
          <p className="subtitle">Loading active GitHub task prediction…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="prediction-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Prediction</h1>
        <p className="subtitle">Initial forecasting for active GitHub tasks</p>
      </div>

      {error && <div className="pred-message error">{error}</div>}

      {!selectedTask ? (
        <div className="sd-card pred-empty-state">
          <h2>No active GitHub task</h2>
          <p>
            Move an issue into the mapped ACTIVE status to create and display its initial
            prediction. Completed tasks are not shown here.
          </p>
        </div>
      ) : (
        <div className="pred-layout">
          <div className="pred-sidebar">
            <h3 className="pred-sidebar-title">Active GitHub Tasks</h3>
            <div className="pred-task-list">
              {tasks.map((task, index) => (
                <button
                  type="button"
                  key={task.project_item_id}
                  className={`pred-task-card ${selectedTaskIndex === index ? 'active' : ''}`}
                  onClick={() => setSelectedTaskIndex(index)}
                >
                  <div className="pred-task-card-header">
                    <h4>{task.title}</h4>
                    <span className="pred-status-badge ongoing">Active</span>
                  </div>
                  <div className="pred-task-context">
                    {task.repository ? `GitHub • ${task.repository}` : 'GitHub'}
                  </div>
                  <div className="pred-task-initial">
                    Initial prediction: {formatInitialPrediction(task.predicted_typical_hours)}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="pred-main">
            <div className="sd-card pred-detail-card">
              <div className="pred-detail-header">
                <h2>{selectedTask.title}</h2>
                <span className="pred-status-badge ongoing">Active</span>
              </div>

              <div className="pred-detail-meta">
                {selectedTask.repository ? `GitHub • ${selectedTask.repository} • ` : 'GitHub • '}
                Started {formatStartedAt(selectedTask.started_at)}
              </div>

              <div className="pred-detail-progress">
                <div className="pred-progress-track large unavailable" />
              </div>
            </div>

            <div className="pred-stats-grid">
              <div className="sd-card pred-stat-card">
                <span className="pred-stat-label">Time Spent</span>
                {formatTimeSpent(selectedTask.task_active_seconds) ? (
                  <>
                    <span className="pred-stat-value">{formatTimeSpent(selectedTask.task_active_seconds)}</span>
                    <span className="pred-stat-sub">
                      Active development time{selectedTask.data_status === 'partial' ? ' (partial data)' : ''}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="pred-stat-value unavailable-value">—</span>
                    <span className="pred-stat-sub">Unable to determine task activity</span>
                  </>
                )}
              </div>
              <div className="sd-card pred-stat-card">
                <span className="pred-stat-label">Initial Estimate</span>
                <span className="pred-stat-value">
                  {formatInitialPrediction(selectedTask.predicted_typical_hours)}
                </span>
                <span className="pred-stat-sub">Typical total effort at lifecycle start</span>
              </div>
              <div className="sd-card pred-stat-card">
                <span className="pred-stat-label">Remaining Estimate</span>
                {formatHoursAsDuration(selectedTask.remaining_time_hours) ? (
                  <>
                    <span className="pred-stat-value">
                      {formatHoursAsDuration(selectedTask.remaining_time_hours)}
                    </span>
                    <span className="pred-stat-sub">Baseline from the initial estimate</span>
                  </>
                ) : (
                  <>
                    <span className="pred-stat-value unavailable-value">—</span>
                    <span className="pred-stat-sub">
                      {selectedTask.remaining_time_status === 'estimate_exceeded'
                        ? getRemainingEstimateStatus(selectedTask)
                        : 'Unable to calculate'}
                    </span>
                  </>
                )}
              </div>
            </div>

            <div className="sd-card pred-trend-card">
              <span className="pred-stat-label">Prediction Status</span>
              <div className="pred-trend-content">
                <span className="trend-dash">—</span>
                <div>
                  <strong>{getRemainingEstimateStatus(selectedTask)}</strong>
                  <p>
                    Remaining Estimate is a baseline derived from the persisted initial estimate and
                    authoritative active development time. It is not a completion percentage.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Prediction;
