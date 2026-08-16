import {
  formatHoursAsDuration,
  formatTimeSpent,
  getRemainingEstimateStatus,
} from './timeSpent.mjs';

const startedAtMillis = (task) => {
  const value = Date.parse(task?.started_at || '');
  return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
};

export const selectMostRecentlyStartedTask = (tasks) => {
  if (!Array.isArray(tasks) || tasks.length === 0) return null;
  return tasks.reduce((selected, task) =>
    startedAtMillis(task) > startedAtMillis(selected) ? task : selected
  );
};

export const buildDashboardPredictionSummary = (tasks) => {
  const activeTasks = Array.isArray(tasks) ? tasks : [];
  const task = selectMostRecentlyStartedTask(activeTasks);
  if (!task) return null;

  const timeSpent = formatTimeSpent(task.task_active_seconds);
  const initialEstimate = formatHoursAsDuration(task.predicted_typical_hours);
  const remainingEstimate = formatHoursAsDuration(task.remaining_time_hours);

  return {
    task,
    activeTaskCount: activeTasks.length,
    moreTaskCount: Math.max(0, activeTasks.length - 1),
    initialEstimate: initialEstimate || '—',
    initialEstimateDetail: initialEstimate ? 'Typical total effort' : 'Unable to calculate',
    timeSpent: timeSpent || '—',
    timeSpentDetail: timeSpent
      ? `Active development time${task.data_status === 'partial' ? ' (partial data)' : ''}`
      : 'Unable to determine task activity',
    remainingEstimate: remainingEstimate || '—',
    remainingEstimateDetail: remainingEstimate
      ? 'Baseline from the initial estimate'
      : task.remaining_time_status === 'estimate_exceeded'
        ? getRemainingEstimateStatus(task)
        : 'Unable to calculate',
  };
};
