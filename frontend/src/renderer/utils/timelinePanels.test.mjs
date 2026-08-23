import assert from 'node:assert/strict';
import test from 'node:test';

import { getTimelineSecondaryPanel } from './timelinePanels.mjs';

test('shows Time by Language inside the top grid for IDE when breakdown data exists', () => {
  assert.deepEqual(getTimelineSecondaryPanel('IDE', true), {
    primaryPanel: 'breakdown',
    showBreakdownBelow: false,
  });
});

test('hides the lower breakdown card for IDE even when no language rows are present', () => {
  assert.deepEqual(getTimelineSecondaryPanel('IDE', false), {
    primaryPanel: null,
    showBreakdownBelow: false,
  });
});

test('keeps category distribution on the top row for Browser and OS / Apps', () => {
  assert.deepEqual(getTimelineSecondaryPanel('Browser', true), {
    primaryPanel: 'distribution',
    showBreakdownBelow: true,
  });
  assert.deepEqual(getTimelineSecondaryPanel('OS / Apps', false), {
    primaryPanel: 'distribution',
    showBreakdownBelow: false,
  });
});
