export type TimelineBreakdownTab = 'IDE' | 'Browser' | 'OS / Apps';
export type TimelineSecondaryPanel = 'distribution' | 'breakdown' | null;

export function getTimelineSecondaryPanel(
  activeTab: TimelineBreakdownTab,
  hasBreakdown: boolean,
): {
  primaryPanel: TimelineSecondaryPanel;
  showBreakdownBelow: boolean;
} {
  if (activeTab === 'IDE') {
    return {
      primaryPanel: hasBreakdown ? 'breakdown' : null,
      showBreakdownBelow: false,
    };
  }

  return {
    primaryPanel: 'distribution',
    showBreakdownBelow: hasBreakdown,
  };
}
