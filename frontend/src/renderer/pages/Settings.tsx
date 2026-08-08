import { useState } from 'react';
import './Settings.css';

interface PrivacySettings {
  webcamEmotion: boolean;
  calendarAccess: boolean;
  cloudSync: boolean;
}

interface Integration {
  name: string;
  status: string;
  icon: string;
  color: string;
}

const Settings: React.FC = () => {
  const [privacy, setPrivacy] = useState<PrivacySettings>({
    webcamEmotion: true,
    calendarAccess: true,
    cloudSync: false,
  });

  const [integrations] = useState<Integration[]>([
    { name: 'VS Code', status: 'Connected', icon: '💻', color: '#007ACC' },
    { name: 'GitHub', status: 'Connected (read-only)', icon: '🐙', color: '#8B5CF6' },
    { name: 'Google Calendar', status: 'Connected (read-only)', icon: '📅', color: '#94A3B8' },
  ]);

  const togglePrivacy = (key: keyof PrivacySettings) => {
    setPrivacy(prev => {
      const updated = { ...prev, [key]: !prev[key] };
      localStorage.setItem('smartdeskSettings', JSON.stringify(updated));
      return updated;
    });
  };

  return (
    <div className="settings-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Settings</h1>
      </div>

      {/* Privacy Controls */}
      <div className="sd-card settings-section">
        <div className="section-header">
          <span className="section-icon">🛡️</span>
          <div>
            <h2>Privacy Controls</h2>
            <p>SmartDesk is built with privacy first. All data processing happens locally by default.</p>
          </div>
        </div>
        <div className="settings-divider" />

        <div className="setting-row">
          <div className="setting-icon-wrap" style={{ background: '#EBF0FF' }}>📷</div>
          <div className="setting-info">
            <strong>Webcam Emotion Detection</strong>
            <p>Analyze facial expressions to detect stress patterns. No images are stored, only emotion labels.</p>
            <div className="setting-tags">
              <span>👁️ Processed locally</span>
              <span>🚫 No image storage</span>
            </div>
          </div>
          <label className="sd-toggle">
            <input type="checkbox" checked={privacy.webcamEmotion} onChange={() => togglePrivacy('webcamEmotion')} />
            <span className="sd-toggle-slider" />
          </label>
        </div>

        <div className="setting-row">
          <div className="setting-icon-wrap" style={{ background: '#ECFDF5' }}>📅</div>
          <div className="setting-info">
            <strong>Calendar Access</strong>
            <p>Read-only access to detect meeting times and provide better focus recommendations.</p>
            <div className="setting-tags">
              <span>🔓 Read-only</span>
              <span>👁️ Event times only</span>
            </div>
          </div>
          <label className="sd-toggle">
            <input type="checkbox" checked={privacy.calendarAccess} onChange={() => togglePrivacy('calendarAccess')} />
            <span className="sd-toggle-slider" />
          </label>
        </div>

        <div className="setting-row">
          <div className="setting-icon-wrap" style={{ background: '#EBF0FF' }}>☁️</div>
          <div className="setting-info">
            <strong>Cloud Sync</strong>
            <p>Enable cloud sync for long-term AI insights and cross-device access. All data is encrypted.</p>
            <div className="setting-tags">
              <span>🔒 End-to-end encrypted</span>
              <span>Optional feature</span>
            </div>
          </div>
          <label className="sd-toggle">
            <input type="checkbox" checked={privacy.cloudSync} onChange={() => togglePrivacy('cloudSync')} />
            <span className="sd-toggle-slider" />
          </label>
        </div>
      </div>

      {/* Data Control */}
      <div className="sd-card settings-section">
        <div className="section-header">
          <span className="section-icon">📋</span>
          <div>
            <h2>Data Control</h2>
            <p>You have full control over your data at all times.</p>
          </div>
        </div>
        <div className="settings-divider" />

        <div className="data-row">
          <div className="data-row-icon">👁️</div>
          <div className="data-row-info">
            <strong>View Stored Data</strong>
            <p>See all data collected by SmartDesk</p>
          </div>
          <span className="data-row-action">→</span>
        </div>

        <div className="data-row data-row--warning">
          <div className="data-row-icon" style={{ color: 'var(--color-danger)' }}>🗑️</div>
          <div className="data-row-info">
            <strong>Delete Today's Data</strong>
            <p>Remove all activity from today</p>
          </div>
          <button className="sd-btn sd-btn--danger">Delete</button>
        </div>

        <div className="data-row data-row--danger">
          <div className="data-row-icon" style={{ color: 'var(--color-danger)' }}>🗑️</div>
          <div className="data-row-info">
            <strong>Delete All Data</strong>
            <p>Permanently remove all SmartDesk data</p>
          </div>
          <button className="sd-btn sd-btn--danger">Delete All</button>
        </div>
      </div>

      {/* Integrations */}
      <div className="sd-card settings-section">
        <div className="section-header">
          <span className="section-icon">🔗</span>
          <div>
            <h2>Integrations</h2>
            <p>Connect external tools for better insights.</p>
          </div>
        </div>
        <div className="settings-divider" />

        {integrations.map((int, i) => (
          <div className="integration-row" key={i}>
            <div className="integration-icon" style={{ background: int.color }}>
              {int.icon}
            </div>
            <div className="integration-info">
              <strong>{int.name}</strong>
              <span className="integration-status">{int.status}</span>
            </div>
            <button className="sd-btn">Disconnect</button>
          </div>
        ))}
      </div>

      {/* Privacy Footer */}
      <div className="sd-alert sd-alert--success privacy-footer">
        <span className="sd-alert-icon">🛡️</span>
        <div className="sd-alert-content">
          <h4>Privacy-First Design</h4>
          <p>SmartDesk collects only metadata about your activity (app names, durations, timestamps). We never read file contents, URLs, or any sensitive information. All processing happens locally on your device unless you enable cloud sync.</p>
        </div>
      </div>
    </div>
  );
};

export default Settings;