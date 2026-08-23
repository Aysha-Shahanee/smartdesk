export const getTimelineSecondaryPanel = (activeTab, hasBreakdown) => {
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
};
