import { useCallback, useEffect, useState } from 'react';
import {
  beginGitHubConnection,
  disconnectGitHub,
  getGitHubProjects,
  getRecommendations,
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

interface NotifySettings {
  enabled: boolean;
  quietFrom: number;
  quietTo: number;
  muted: string[];
  shownToday: number;
}

/** Hours offered for the quiet-hours pickers. */
const HOURS = Array.from({ length: 24 }, (_, h) => h);

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
  /* Notification throttles live in the Electron main process, because it is
     the thing that actually raises a toast and it keeps running when the
     window is closed. This panel is a view onto that state, not a second copy
     of it — every change round-trips through the bridge and the response is
     what gets rendered. */
  const [notify, setNotify] = useState<NotifySettings | null>(null);
  const [mutable, setMutable] = useState<string[]>([]);

  const pushNotify = useCallback(async (patch: Record<string, unknown>) => {
    if (!window.electronAPI) return;
    try {
      setNotify(await window.electronAPI.notificationSettings(patch));
    } catch {
      /* The main process is the authority; a failed write leaves it unchanged. */
    }
  }, []);

  useEffect(() => { void pushNotify({}); }, [pushNotify]);

  /* Rule ids that have actually produced a card, so the mute list offers real
     rules rather than all 72 of them. */
  useEffect(() => {
    let cancelled = false;
    getRecommendations()
      .then(res => {
        if (cancelled) return;
        const ids = new Set<string>();
        Object.values(res.sections).flat().forEach(rec => {
          if (rec.scope === 'live' && rec.severity === 'high') ids.add(rec.rule_id);
        });
        setMutable([...ids].sort());
      })
      .catch(() => setMutable([]));
    return () => { cancelled = true; };
  }, []);

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


      {/* Notifications */}
      <div className="sd-card settings-section">
        <div className="section-header">
          <span className="section-icon">🔔</span>
          <div>
            <h2>Notifications</h2>
            <p>
              Only high-severity live findings can interrupt, at most one every 45
              minutes and four a day. {notify ? `${notify.shownToday} shown today.` : ''}
            </p>
          </div>
        </div>
        <div className="settings-divider" />

        {!window.electronAPI ? (
          <p className="dash-empty">
            Desktop notifications are available in the SmartDesk app. This is a
            browser session, so nothing here would have anywhere to appear.
          </p>
        ) : !notify ? (
          <p className="dash-empty">Reading notification settings…</p>
        ) : (
          <>
            <div className="data-row">
              <div>
                <strong>Allow desktop notifications</strong>
                <p>Turn this off to keep every finding inside the app.</p>
              </div>
              <label className="sd-toggle">
                <input
                  type="checkbox"
                  checked={notify.enabled}
                  onChange={() => void pushNotify({ enabled: !notify.enabled })}
                />
                <span className="sd-toggle-slider" />
              </label>
            </div>

            <div className="data-row">
              <div>
                <strong>Quiet hours</strong>
                <p>Nothing is raised between these times.</p>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <select
                  className="sd-select"
                  value={notify.quietFrom}
                  onChange={e => void pushNotify({ quietFrom: Number(e.target.value) })}
                >
                  {HOURS.map(h => (
                    <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>
                  ))}
                </select>
                <span style={{ color: 'var(--color-text-secondary)' }}>to</span>
                <select
                  className="sd-select"
                  value={notify.quietTo}
                  onChange={e => void pushNotify({ quietTo: Number(e.target.value) })}
                >
                  {HOURS.map(h => (
                    <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="data-row">
              <div>
                <strong>Muted rules</strong>
                <p>
                  {notify.muted.length > 0
                    ? `${notify.muted.join(', ')} will not raise a toast.`
                    : 'Nothing is muted. Rules you mute still appear on the Recommendations page.'}
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                {mutable.length === 0 && (
                  <span className="metric-card-sub">No interrupting rules have fired yet</span>
                )}
                {mutable.map(ruleId => {
                  const muted = notify.muted.includes(ruleId);
                  return (
                    <button
                      key={ruleId}
                      className="sd-btn"
                      onClick={() =>
                        void pushNotify(muted ? { unmuteRule: ruleId } : { muteRule: ruleId })
                      }
                    >
                      {muted ? `Unmute ${ruleId}` : `Mute ${ruleId}`}
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}
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
