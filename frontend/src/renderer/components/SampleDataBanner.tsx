import React from 'react';

/**
 * Marks a page whose figures are placeholders.
 *
 * Focus scores, stress levels, emotion mix and task predictions have no
 * collector or endpoint behind them — the backend exposes only activity
 * segments, per-source session panels and calendar events. Without this
 * notice the charts on those pages are indistinguishable from the
 * data-backed ones on the Dashboard, Timeline and Reports.
 */
const SampleDataBanner: React.FC<{ what: string }> = ({ what }) => (
  <div className="sd-alert sd-alert--warning" style={{ marginBottom: 'var(--space-xl)' }}>
    <span className="sd-alert-icon">⚠️</span>
    <div className="sd-alert-content">
      <h4>Sample data — not from your activity</h4>
      <p>
        {what} is not collected yet, so every figure on this page is a fixed placeholder
        and does not change with the selected date. The Dashboard, Timeline and Reports
        pages show your real recorded activity.
      </p>
    </div>
  </div>
);

export default SampleDataBanner;
