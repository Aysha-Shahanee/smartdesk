import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatHoursAsDuration,
  formatTimeSpent,
  getRemainingEstimateStatus,
} from './timeSpent.mjs';

test('formats task active seconds for the Prediction page', () => {
  assert.equal(formatTimeSpent(5400), '1 h 30 min');
  assert.equal(formatTimeSpent(3600), '1 h');
  assert.equal(formatTimeSpent(120), '2 min');
  assert.equal(formatTimeSpent(0), '< 1 min');
});

test('leaves unavailable and ambiguous backend values unformatted', () => {
  assert.equal(formatTimeSpent(null), null);
  assert.equal(formatTimeSpent(undefined), null);
});

test('formats backend Remaining Time hours without unnecessary decimals', () => {
  assert.equal(formatHoursAsDuration(0.5), '30 min');
  assert.equal(formatHoursAsDuration(1.5), '1 h 30 min');
  assert.equal(formatHoursAsDuration(16.8), '16 h 48 min');
  assert.equal(formatHoursAsDuration(0), '< 1 min');
});

test('leaves unavailable Remaining Time unformatted', () => {
  assert.equal(formatHoursAsDuration(null), null);
  assert.equal(formatHoursAsDuration(undefined), null);
});

test('describes an exceeded initial estimate without presenting zero remaining', () => {
  assert.equal(
    getRemainingEstimateStatus({
      remaining_time_status: 'estimate_exceeded',
      overrun_hours: 3,
    }),
    'Initial estimate exceeded by 3 h',
  );
});

test('describes the optional approaching-estimate warning', () => {
  assert.equal(
    getRemainingEstimateStatus({
      remaining_time_status: 'baseline_available',
      approaching_initial_estimate: true,
    }),
    'Approaching initial estimate',
  );
});
