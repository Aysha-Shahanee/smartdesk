import { useEffect, useState } from 'react';
import {
  beginGitHubConnection,
  disconnectGitHub,
  getGitHubProjects,
  getGitHubStatus,
  getGitHubStatusMapping,
  getGitHubStatusOptions,
  GitHubConnectionStatus,
  GitHubProject,
  GitHubStatusOption,
  saveGitHubStatusMapping,
  selectGitHubProject,
} from '../services/api';
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
    { name: 'Google Calendar', status: 'Connected (read-only)', icon: '📅', color: '#94A3B8' },
  ]);

  const [github, setGithub] = useState<GitHubConnectionStatus | null>(null);
  const [projects, setProjects] = useState<GitHubProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [statusOptions, setStatusOptions] = useState<GitHubStatusOption[]>([]);
  const [statusMapping, setStatusMapping] = useState<Record<string, string>>({});
  const [githubBusy, setGithubBusy] = useState(true);
  const [githubMessage, setGithubMessage] = useState('');
  const [githubStatusUnavailable, setGithubStatusUnavailable] = useState(false);

  const loadProjectConfiguration = async () => {
    const [optionsResponse, mappingResponse] = await Promise.all([
      getGitHubStatusOptions(),
      getGitHubStatusMapping(),
    ]);
    setStatusOptions(optionsResponse.options);
    setStatusMapping(Object.fromEntries(
      optionsResponse.options.map(option => [
        option.name,
        mappingResponse.mapping[option.name] || 'OTHER',
      ])
    ));
  };

  const refreshGitHub = async () => {
    setGithubBusy(true);
    setGithubMessage('');
    setGithubStatusUnavailable(false);
    try {
      const current = await getGitHubStatus();
      setGithub(current);
      if (current.connection_status === 'connected') {
        const response = await getGitHubProjects();
        setProjects(response.projects);
        setSelectedProjectId(current.selected_project_id || '');
        if (current.selected_project_id) await loadProjectConfiguration();
      } else {
        setProjects([]);
        setSelectedProjectId('');
        setStatusOptions([]);
        setStatusMapping({});
      }
    } catch (error) {
      setGithubStatusUnavailable(true);
      setGithubMessage(error instanceof Error ? error.message : 'Unable to load GitHub settings.');
    } finally {
      setGithubBusy(false);
    }
  };

  useEffect(() => { refreshGitHub(); }, []);

  const connectGitHub = async () => {
    try {
      const { installation_url } = await beginGitHubConnection();
      if (window.electronAPI) {
        await window.electronAPI.openGitHubExternal(installation_url);
      } else {
        window.location.assign(installation_url);
      }
    } catch (error) {
      setGithubMessage(error instanceof Error ? error.message : 'Unable to connect GitHub.');
    }
  };

  const chooseProject = async () => {
    const project = projects.find(item => item.project_id === selectedProjectId);
    if (!project) return;
    setGithubBusy(true);
    try {
      await selectGitHubProject(project);
      await refreshGitHub();
      setGithubMessage(`Selected ${project.title}.`);
    } catch (error) {
      setGithubMessage(error instanceof Error ? error.message : 'Unable to select project.');
      setGithubBusy(false);
    }
  };

  const saveMapping = async () => {
    setGithubBusy(true);
    try {
      await saveGitHubStatusMapping(statusMapping);
      setGithubMessage('Status mapping saved and project synchronized.');
    } catch (error) {
      setGithubMessage(error instanceof Error ? error.message : 'Unable to save status mapping.');
    } finally {
      setGithubBusy(false);
    }
  };

  const disconnect = async () => {
    setGithubBusy(true);
    try {
      await disconnectGitHub();
      await refreshGitHub();
      setGithubMessage('GitHub disconnected from this SmartDesk user.');
    } catch (error) {
      setGithubMessage(error instanceof Error ? error.message : 'Unable to disconnect GitHub.');
      setGithubBusy(false);
    }
  };

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

        <div className="github-integration">
          <div className="integration-row github-integration-header">
            <div className="integration-icon" style={{ background: '#24292F' }}>GH</div>
            <div className="integration-info">
              <strong>GitHub Projects</strong>
              <span className={`integration-status ${github?.connection_status !== 'connected' ? 'integration-status--muted' : ''}`}>
                {githubBusy && !github
                  ? 'Checking connection…'
                  : githubStatusUnavailable
                    ? 'Connection unavailable'
                    : github?.connection_status === 'connected'
                      ? `Connected to ${github.github_login}`
                      : 'Not connected'}
              </span>
              {github?.selected_project_title && (
                <span className="integration-detail">Selected project: {github.selected_project_title}</span>
              )}
            </div>
            {github?.connection_status === 'connected' ? (
              <button className="sd-btn" onClick={disconnect} disabled={githubBusy}>Disconnect</button>
            ) : (
              <button className="sd-btn sd-btn--primary" onClick={connectGitHub} disabled={githubBusy}>Connect GitHub</button>
            )}
          </div>

          {github?.connection_status === 'connected' && (
            <div className="github-configuration">
              <label className="github-field">
                <span>Project</span>
                <div className="github-field-row">
                  <select value={selectedProjectId} onChange={event => setSelectedProjectId(event.target.value)}>
                    <option value="">Choose an accessible Project</option>
                    {projects.map(project => (
                      <option key={project.project_id} value={project.project_id}>{project.title}</option>
                    ))}
                  </select>
                  <button className="sd-btn" onClick={chooseProject} disabled={!selectedProjectId || githubBusy}>Select</button>
                </div>
              </label>

              {github.selected_project_id && statusOptions.length > 0 && (
                <div className="github-mapping">
                  <strong>Status mapping</strong>
                  <p>Map each Project Status option to SmartDesk's lifecycle.</p>
                  {statusOptions.map(option => (
                    <label className="github-mapping-row" key={option.id}>
                      <span>{option.name}</span>
                      <select
                        value={statusMapping[option.name] || 'OTHER'}
                        onChange={event => setStatusMapping(current => ({
                          ...current,
                          [option.name]: event.target.value,
                        }))}
                      >
                        <option value="NOT_STARTED">Not started</option>
                        <option value="ACTIVE">Active</option>
                        <option value="DONE">Done</option>
                        <option value="OTHER">Other</option>
                      </select>
                    </label>
                  ))}
                  <button className="sd-btn sd-btn--primary" onClick={saveMapping} disabled={githubBusy}>
                    Save mapping
                  </button>
                </div>
              )}
            </div>
          )}

          {githubMessage && <p className="github-message">{githubMessage}</p>}
        </div>

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
