import React from 'react';

/**
 * Inline "this figure is invented" marker for a single card or tile.
 *
 * The page-wide {@link SampleDataBanner} is the right tool when nothing on a
 * page is collected. The Dashboard is mixed — most cards read real activity
 * segments while a couple have no collector behind them — so a page banner
 * would either be wrong or discredit the real numbers next to it. This badge
 * marks the placeholders individually instead.
 */
const SampleBadge: React.FC<{ title?: string }> = ({ title }) => (
  <span
    className="sd-sample-badge"
    title={title ?? 'Placeholder figures — this metric is not collected yet and does not change with the selected date.'}
  >
    ⚠ Sample data
  </span>
);

export default SampleBadge;
