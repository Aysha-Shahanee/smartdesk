import { useCallback, useEffect, useRef, useState } from 'react';
import {
  beginCalendarConnection,
  beginGitHubConnection,
  CalendarStatus,
  disconnectCalendar,
  disconnectGitHub,
  getCalendarStatus,
  getGitHubProjects,
  getRecommendations,
  getGitHubStatus,
  getGitHubStatusMapping,
  getGitHubStatusOptions,
  getEmotionConsent,
  setEmotionConsent,
  GitHubConnectionStatus,
  GitHubProject,
  GitHubStatusOption,
  saveGitHubStatusMapping,
  selectGitHubProject,
  syncCalendarNow,
} from '../services/api';
import './Settings.css';

/* calendarAccess used to live here as a local boolean that defaulted to true
   and controlled nothing. It now comes from the backend connection state, which
   is the only thing that decides whether events are actually collected. */
interface PrivacySettings {
  webcamEmotion: boolean;
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
  /* webcamEmotion starts off and is authoritative in the backend — the capture
     loop runs in the API process, so a value kept only here could never stop
     it. The other two are local display state until they gain a backend of
     their own. */
  const [privacy, setPrivacy] = useState<PrivacySettings>({
    webcamEmotion: false,
    cloudSync: false,
  });
  const [webcamBusy, setWebcamBusy] = useState(true);
  const [webcamError, setWebcamError] = useState('');

  /* Google Calendar is no longer in this list: it had a hardcoded "Connected
     (read-only)" label and a Disconnect button wired to nothing, which is how a
     dead connection went unnoticed for eleven days. It has a real block below,
     driven by /api/v1/calendar/status. */
  const [integrations] = useState<Integration[]>([
    { name: 'VS Code', status: 'Connected', icon: '💻', color: '#007ACC' },
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

  /* ---------------------------------------------------------------- */
  /* Google Calendar                                                    */
  /* ---------------------------------------------------------------- */

  const [calendar, setCalendar] = useState<CalendarStatus | null>(null);
  const [calendarBusy, setCalendarBusy] = useState(true);
  const [calendarMessage, setCalendarMessage] = useState('');
  const [calendarUnavailable, setCalendarUnavailable] = useState(false);
  /* True from the moment the consent tab opens until the backend reports a
     token. Consent happens in the system browser, so the app has no callback to
     wait on — it polls, and this flag is what stops the polling. */
  const [awaitingConsent, setAwaitingConsent] = useState(false);
  /* Set only when the app could not open the browser itself, so the user can
     still complete consent by hand. Empty the rest of the time. */
  const [manualAuthUrl, setManualAuthUrl] = useState('');
  const consentPoll = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshCalendar = useCallback(async (): Promise<CalendarStatus | null> => {
    try {
      const status = await getCalendarStatus();
      setCalendar(status);
      setCalendarUnavailable(false);
      return status;
    } catch {
      // Backend down or still starting. Say so rather than showing "off",
      // which would read as "collection is disabled" and it is not.
      setCalendarUnavailable(true);
      return null;
    } finally {
      setCalendarBusy(false);
    }
  }, []);

  useEffect(() => { void refreshCalendar(); }, [refreshCalendar]);

  const stopConsentPoll = useCallback(() => {
    if (consentPoll.current !== null) {
      clearInterval(consentPoll.current);
      consentPoll.current = null;
    }
    setAwaitingConsent(false);
  }, []);

  // Never leave an interval running behind a closed page.
  useEffect(() => () => stopConsentPoll(), [stopConsentPoll]);

  /**
   * Hand the consent URL to a real browser.
   *
   * Returns false when the app could not open it itself, which happens when the
   * Electron main process is older than this renderer: `ipcMain.handle` only
   * registers at main-process startup, so a hot-reloaded renderer can call a
   * channel that does not exist yet and get "No handler registered". The URL is
   * still perfectly good, so the caller shows it instead of dead-ending.
   */
  const openConsentScreen = async (authUrl: string): Promise<boolean> => {
    if (!window.electronAPI) {
      // Plain browser (vite dev) — a normal tab is exactly right.
      window.open(authUrl, '_blank', 'noopener');
      return true;
    }
    if (!window.electronAPI.openCalendarExternal) return false;
    try {
      await window.electronAPI.openCalendarExternal(authUrl);
      return true;
    } catch {
      return false;
    }
  };

  const connectCalendar = async () => {
    setCalendarBusy(true);
    setCalendarMessage('');
    setManualAuthUrl('');
    try {
      const { auth_url } = await beginCalendarConnection();
      const opened = await openConsentScreen(auth_url);
      setAwaitingConsent(true);
      if (opened) {
        setCalendarMessage('Approve access in the browser tab that just opened, then come back here.');
      } else {
        // Polling still runs: consent completed in any browser lands on the
        // backend callback, and the next poll picks the token up.
        setManualAuthUrl(auth_url);
        setCalendarMessage(
          'Could not open the browser automatically — restart the app to fix that. '
          + 'In the meantime, open this link yourself to finish connecting:'
        );
      }

      /* Poll until the OAuth callback has stored a token. Give up after five
         minutes so an abandoned consent screen does not poll forever; the
         status still refreshes on the next visit to this page. */
      const startedAt = Date.now();
      stopConsentPoll();
      consentPoll.current = setInterval(async () => {
        const status = await refreshCalendar();
        if (status?.connected) {
          stopConsentPoll();
          setManualAuthUrl('');
          setCalendarMessage('Google Calendar connected. Events are syncing now.');
        } else if (Date.now() - startedAt > 5 * 60 * 1000) {
          stopConsentPoll();
          setCalendarMessage('Timed out waiting for approval. Click Connect to try again.');
        }
      }, 2000);
    } catch (error) {
      setCalendarMessage(
        error instanceof Error ? error.message : 'Unable to start the Google connection.'
      );
    } finally {
      setCalendarBusy(false);
    }
  };

  const turnOffCalendar = async () => {
    setCalendarBusy(true);
    setCalendarMessage('');
    setManualAuthUrl('');
    stopConsentPoll();
    try {
      const status = await disconnectCalendar();
      setCalendar(status);
      setCalendarMessage('Calendar collection is off. Events already synced are kept.');
    } catch (error) {
      setCalendarMessage(
        error instanceof Error ? error.message : 'Unable to turn calendar collection off.'
      );
    } finally {
      setCalendarBusy(false);
    }
  };

  /** One switch, both directions — connect when off, disconnect when on. */
  const toggleCalendar = () => {
    if (calendar?.connected) {
      void turnOffCalendar();
    } else {
      void connectCalendar();
    }
  };

  const syncCalendar = async () => {
    setCalendarBusy(true);
    setCalendarMessage('');
    try {
      const stats = await syncCalendarNow();
      await refreshCalendar();
      setCalendarMessage(
        `Synced: ${stats.created ?? 0} new, ${stats.updated ?? 0} updated, ${stats.unchanged ?? 0} unchanged.`
      );
    } catch (error) {
      await refreshCalendar();
      setCalendarMessage(
        error instanceof Error ? error.message : 'Sync failed. Auto-sync will retry on its own.'
      );
    } finally {
      setCalendarBusy(false);
    }
  };

  /* One phrase answering "is my calendar being collected right now?". Derived
     once so the privacy switch, the integration row and the tag line cannot
     disagree with each other. */
  const calendarSummary = (() => {
    if (calendarUnavailable) return 'Status unavailable';
    if (calendarBusy && !calendar) return 'Checking…';
    if (!calendar) return 'Status unknown';
    switch (calendar.state) {
      case 'not_configured': return 'Not set up on this machine';
      case 'disconnected': return awaitingConsent ? 'Waiting for approval…' : 'Off';
      case 'needs_reconnect': return 'Stopped — reconnect needed';
      case 'degraded': return `Retrying — ${calendar.consecutive_failures} failed attempt(s)`;
      case 'collecting': return 'Collecting';
      default: return 'Status unknown';
    }
  })();

  const calendarHealthy = calendar?.state === 'collecting';

  /** "3 minutes ago" style, from an ISO string the backend already localised. */
  const calendarLastSync = (() => {
    if (!calendar?.last_sync) return 'never';
    const hours = calendar.stale_hours;
    if (hours === null || hours === undefined) return calendar.last_sync;
    if (hours < 1 / 60) return 'just now';
    if (hours < 1) return `${Math.round(hours * 60)} min ago`;
    if (hours < 48) return `${Math.round(hours)} h ago`;
    return `${Math.round(hours / 24)} days ago`;
  })();

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

  useEffect(() => {
    let cancelled = false;
    getEmotionConsent()
      .then(({ webcam_enabled }) => {
        if (cancelled) return;
        setPrivacy(prev => ({ ...prev, webcamEmotion: webcam_enabled }));
      })
      .catch(() => {
        if (!cancelled) setWebcamError('Could not read the webcam setting from the backend.');
      })
      .finally(() => {
        if (!cancelled) setWebcamBusy(false);
      });
    return () => { cancelled = true; };
  }, []);

  const togglePrivacy = (key: keyof PrivacySettings) => {
    setPrivacy(prev => {
      const updated = { ...prev, [key]: !prev[key] };
      localStorage.setItem('smartdeskSettings', JSON.stringify(updated));
      return updated;
    });
  };

  /* Webcam consent round-trips to the backend, which is what actually gates
     capture. Only reflect the new position once the server has accepted it, so
     the switch can never show a permission the backend has not granted. */
  const toggleWebcamEmotion = async () => {
    const next = !privacy.webcamEmotion;
    setWebcamBusy(true);
    setWebcamError('');
    try {
      const { webcam_enabled } = await setEmotionConsent(next);
      setPrivacy(prev => ({ ...prev, webcamEmotion: webcam_enabled }));
    } catch (error) {
      setWebcamError(
        error instanceof Error ? error.message : 'Could not save the webcam setting.'
      );
    } finally {
      setWebcamBusy(false);
    }
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
              <span>{privacy.webcamEmotion ? '✅ Camera allowed' : '⛔ Camera blocked'}</span>
            </div>
            {webcamError && <p className="setting-error">{webcamError}</p>}
          </div>
          <label className="sd-toggle">
            <input
              type="checkbox"
              checked={privacy.webcamEmotion}
              disabled={webcamBusy}
              onChange={toggleWebcamEmotion}
            />
            <span className="sd-toggle-slider" />
          </label>
        </div>

        {/* Same switch as the one in Integrations, reading the same backend
            state. Flipping it on opens Google's consent screen; off deletes the
            stored token and stops collection immediately. */}
        <div className="setting-row">
          <div className="setting-icon-wrap" style={{ background: '#ECFDF5' }}>📅</div>
          <div className="setting-info">
            <strong>Calendar Access</strong>
            <p>Read-only access to detect meeting times and provide better focus recommendations.</p>
            <div className="setting-tags">
              <span>🔓 Read-only</span>
              <span>👁️ Event times only</span>
              <span>{calendarSummary}</span>
            </div>
          </div>
          <label className="sd-toggle">
            <input
              type="checkbox"
              checked={Boolean(calendar?.connected)}
              disabled={calendarBusy || calendarUnavailable || calendar?.configured === false}
              onChange={toggleCalendar}
            />
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

        {/* Google Calendar — the real control. One switch turns collection on
            (opens Google consent) and off (deletes the stored token). */}
        <div className="calendar-integration">
          <div className="integration-row calendar-integration-header">
            <div className="integration-icon" style={{ background: '#4285F4' }}>📅</div>
            <div className="integration-info">
              <strong>Google Calendar</strong>
              <span
                className={`integration-status ${calendarHealthy ? '' : 'integration-status--muted'}`}
              >
                {calendarSummary}
              </span>
              {calendar?.connected && (
                <span className="integration-detail">
                  {calendar.event_count} events · last sync {calendarLastSync} · auto-sync every{' '}
                  {calendar.sync_interval_min} min
                </span>
              )}
              {calendar?.state === 'not_configured' && (
                <span className="integration-detail">
                  Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to backend/.env, or drop a
                  credentials.json into backend/calendar_store/, then restart the backend.
                </span>
              )}
            </div>

            <label className="sd-toggle calendar-toggle">
              <input
                type="checkbox"
                checked={Boolean(calendar?.connected)}
                disabled={calendarBusy || calendarUnavailable || calendar?.configured === false}
                onChange={toggleCalendar}
              />
              <span className="sd-toggle-slider" />
            </label>
          </div>

          {/* Reconnect is a separate, explicit action: the switch is already on
              (a token exists) so flipping it would read as "turn off". */}
          {calendar?.needs_reconnect && (
            <div className="calendar-alert">
              <strong>Collection has stopped.</strong>
              <p>{calendar.reconnect_reason || 'Google access expired. Reconnect to resume.'}</p>
              <button className="sd-btn sd-btn--primary" onClick={connectCalendar} disabled={calendarBusy}>
                Reconnect
              </button>
            </div>
          )}

          {calendar?.connected && !calendar.needs_reconnect && (
            <div className="calendar-actions">
              <button className="sd-btn" onClick={syncCalendar} disabled={calendarBusy}>
                Sync now
              </button>
              <button className="sd-btn" onClick={turnOffCalendar} disabled={calendarBusy}>
                Turn off
              </button>
              {calendar.last_error && (
                <span className="calendar-error-note">Last error: {calendar.last_error}</span>
              )}
            </div>
          )}

          {calendarMessage && <p className="github-message">{calendarMessage}</p>}

          {/* Manual escape hatch. Selectable so it can be copied even if the
              clipboard call is unavailable. */}
          {manualAuthUrl && (
            <div className="calendar-manual-url">
              <code>{manualAuthUrl}</code>
              <button
                className="sd-btn"
                onClick={() => {
                  void navigator.clipboard?.writeText(manualAuthUrl);
                  setCalendarMessage('Link copied. Open it in your browser to finish connecting.');
                }}
              >
                Copy link
              </button>
            </div>
          )}
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
