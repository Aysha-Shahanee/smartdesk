import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildDashboardPredictionSummary,
  selectMostRecentlyStartedTask,
} from './dashboardPrediction.mjs';

const task = (overrides = {}) => ({
  project_item_id: 'PVTI_42',
  issue_number: 42,
  title: 'Fix login validation',
  repository: 'owner/backend',
  logical_status: 'ACTIVE',
  started_at: '2026-08-15T10:00:00Z',
  predicted_typical_hours: 20,
  task_active_seconds: 12_000,
  time_spent_hours: 12_000 / 3600,
  time_attribution_status: 'branch_match',
  data_status: 'complete',
  remaining_time_hours: 20 - (12_000 / 3600),
  remaining_time_status: 'baseline_available',
  ...overrides,
});

test('returns an empty summary for zero active tasks', () => {
  assert.equal(buildDashboardPredictionSummary([]), null);
});

test('formats one real active task without mock progress values', () => {
  const summary = buildDashboardPredictionSummary([task()]);
  assert.equal(summary.activeTaskCount, 1);
  assert.equal(summary.moreTaskCount, 0);
  assert.equal(summary.task.title, 'Fix login validation');
  assert.equal(summary.initialEstimate, '20 h');
  assert.equal(summary.timeSpent, '3 h 20 min');
  assert.equal(summary.remainingEstimate, '16 h 40 min');
  assert.equal(JSON.stringify(summary).includes('User Authentication Module'), false);
  assert.equal(JSON.stringify(summary).includes('53%'), false);
});

test('selects the most recently started lifecycle and reports the total count', () => {
  const older = task({ project_item_id: 'old', title: 'Older', started_at: '2026-08-14T10:00:00Z' });
  const newest = task({ project_item_id: 'new', title: 'Newest', started_at: '2026-08-15T11:00:00Z' });
  const invalid = task({ project_item_id: 'invalid', started_at: 'not-a-date' });
  assert.equal(selectMostRecentlyStartedTask([older, newest, invalid]), newest);
  const summary = buildDashboardPredictionSummary([older, newest, invalid]);
  assert.equal(summary.task, newest);
  assert.equal(summary.activeTaskCount, 3);
  assert.equal(summary.moreTaskCount, 2);
});

test('shows ambiguous Time Spent as unavailable', () => {
  const summary = buildDashboardPredictionSummary([task({
    task_active_seconds: null,
    time_spent_hours: null,
    time_attribution_status: 'ambiguous',
    remaining_time_hours: null,
    remaining_time_status: 'time_spent_unavailable',
  })]);
  assert.equal(summary.timeSpent, '—');
  assert.equal(summary.timeSpentDetail, 'Unable to determine task activity');
  assert.equal(summary.remainingEstimate, '—');
  assert.equal(summary.remainingEstimateDetail, 'Unable to calculate');
});

test('shows unavailable Remaining Estimate without inventing a value', () => {
  const summary = buildDashboardPredictionSummary([task({
    remaining_time_hours: null,
    remaining_time_status: 'initial_prediction_unavailable',
  })]);
  assert.equal(summary.remainingEstimate, '—');
  assert.equal(summary.remainingEstimateDetail, 'Unable to calculate');
});

test('shows estimate-exceeded status and overrun', () => {
  const summary = buildDashboardPredictionSummary([task({
    task_active_seconds: 23 * 3600,
    time_spent_hours: 23,
    remaining_time_hours: null,
    remaining_time_status: 'estimate_exceeded',
    overrun_hours: 3,
  })]);
  assert.equal(summary.remainingEstimate, '—');
  assert.equal(summary.remainingEstimateDetail, 'Initial estimate exceeded by 3 h');
});
