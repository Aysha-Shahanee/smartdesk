import React from 'react';
import './Recommendations.css';

const planningSuggestions = [
  {
    title: 'Avoid context switching after 4 PM',
    why: 'Late-day switching reduces next-day focus by 15%',
    action: 'Use final hours for singular, contained tasks',
    basedOn: '4 weeks of activity data'
  },
  {
    title: 'Group meetings into one time block',
    why: 'Scattered meetings create 6+ context switches per day',
    action: 'Suggest clustering meetings between 2-4 PM',
    basedOn: '4 weeks of activity data'
  },
  {
    title: 'Reserve Mondays for planning',
    why: 'Monday coding sessions show 35% lower deep work time',
    action: 'Use Mondays for roadmapping, reviews, and planning',
    basedOn: '4 weeks of activity data'
  }
];

const behaviorImprovements = [
  {
    title: 'Your focus drops after long meetings',
    insight: 'Average 40% decrease in focus score in the hour following meetings',
    suggestion: 'Block 30 minutes of quiet time after meetings before starting new tasks',
    applied: true
  },
  {
    title: 'Morning deep work sessions perform best',
    insight: 'Your focus score averages 85/100 between 9:30 AM - 11:30 AM',
    suggestion: 'Schedule your most complex tasks during this window',
    applied: true
  },
  {
    title: 'Afternoon context switching increases stress',
    insight: 'Switching between apps 3x more frequently after 2 PM',
    suggestion: 'Batch similar tasks together in the afternoon',
    applied: true
  }
];

const immediateSuggestions = [
  {
    title: 'Take a 5-minute break',
    description: "You've been working for 90 minutes straight",
    actionLabel: 'Start Break'
  },
  {
    title: 'Resume last coding task',
    description: 'auth-service.ts was left open 15 minutes ago',
    actionLabel: 'Resume Task'
  }
];

const Recommendations: React.FC = () => {
  return (
    <div className="recommendations-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Recommendations</h1>
        <p className="subtitle">AI-driven insights to improve your workflow</p>
      </div>

      {/* Immediate Suggestions */}
      <div className="rec-section" style={{ marginBottom: 'var(--space-md)' }}>
        <div className="rec-section-header">
          <span className="rec-section-icon" style={{ color: 'var(--color-primary)' }}>🕒</span>
          <h2>Immediate Suggestions</h2>
        </div>
        <div className="imm-suggestions-list">
          {immediateSuggestions.map((imm, i) => (
            <div className="imm-suggestion-card" key={i}>
              <div className="imm-suggestion-content">
                <strong>{imm.title}</strong>
                <p>{imm.description}</p>
              </div>
              <div className="imm-suggestion-actions">
                <button className="sd-btn sd-btn--primary">{imm.actionLabel}</button>
                <button className="sd-btn imm-dismiss-btn">Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Key Insights Banner */}
      <div className="rec-key-insights">
        <div className="rec-key-insights-header">
          <span className="rec-icon">!</span>
          <div>
            <h3>Key Insights for Today</h3>
            <span className="rec-subtitle">Based on real-time activity analysis</span>
          </div>
        </div>
        <div className="rec-key-insights-body">
          <div className="rec-insight-row">
            <span className="rec-icon-small green">↗</span>
            <div>
              <strong>Focus peak observed between 9:30–11:30</strong>
              <p>Your best work happened during late morning</p>
            </div>
          </div>
          <div className="rec-insight-row">
            <span className="rec-icon-small red">!</span>
            <div>
              <strong>High context switching detected after 1 PM</strong>
              <p>Consider blocking afternoon time for focused work</p>
            </div>
          </div>
        </div>
      </div>

      {/* Planning Suggestions */}
      <div className="rec-section">
        <div className="rec-section-header">
          <span className="rec-section-icon">📅</span>
          <h2>Planning Suggestions</h2>
        </div>
        <div className="rec-card-list">
          {planningSuggestions.map((item, i) => (
            <div className="rec-list-card" key={i}>
              <h4>{item.title}</h4>
              <div className="rec-list-details">
                <div className="rec-detail-row">
                  <span className="rec-detail-label">Why:</span>
                  <span className="rec-detail-value">{item.why}</span>
                </div>
                <div className="rec-detail-row">
                  <span className="rec-detail-label">Action:</span>
                  <span className="rec-detail-value">{item.action}</span>
                </div>
              </div>
              <div className="rec-card-footer">
                Based on {item.basedOn}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Behavior Improvement */}
      <div className="rec-section">
        <div className="rec-section-header">
          <span className="rec-section-icon green">📈</span>
          <h2>Behavior Improvement</h2>
        </div>
        <div className="rec-card-list">
          {behaviorImprovements.map((item, i) => (
            <div className="rec-list-card" key={i}>
              <h4>{item.title}</h4>
              <div className="rec-list-details">
                <div className="rec-detail-row">
                  <span className="rec-detail-label">Insight:</span>
                  <span className="rec-detail-value">{item.insight}</span>
                </div>
                <div className="rec-detail-row">
                  <span className="rec-detail-label">Suggestion:</span>
                  <span className="rec-detail-value">{item.suggestion}</span>
                </div>
              </div>
              <div className="rec-card-actions">
                <button className="rec-action-btn applied">
                  ✓ Mark as Applied
                </button>
                <button className="rec-action-btn">
                  ⊗ Not Relevant
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Recommendations;
