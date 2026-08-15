// Preload scripts
// The preload script runs in the renderer context with access to Node.js APIs,
// but the exposed functions are limited to what we attach to `window` or via
// contextBridge.

import { contextBridge, ipcRenderer } from 'electron'
import { app } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getEnv: () => ({
    backendUrl: import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
  }),
  openGitHubExternal: (url: string) => ipcRenderer.invoke('open-github-external', url),

  /**
   * Open the break countdown overlay.
   *
   * The main process also suppresses notifications for the duration, so the
   * rule that prompted the break cannot re-fire while it is running.
   */
  startBreak: (minutes = 5): Promise<boolean> =>
    ipcRenderer.invoke('smartdesk:start-break', minutes),

  /**
   * Reopen a recorded work context — a URL in the browser, or a file path via
   * the shell. Resolves false when the detail could not be resolved, which the
   * caller should treat as "show the context instead of opening it".
   */
  resumeTask: (facts: Record<string, unknown>): Promise<boolean> =>
    ipcRenderer.invoke('smartdesk:resume-task', facts),

  /**
   * Render a report to PDF and save it. Resolves to the saved path, or null
   * when the user cancelled the dialog or the render failed.
   */
  exportReportPdf: (scope: string, date?: string): Promise<string | null> =>
    ipcRenderer.invoke('smartdesk:export-pdf', scope, date),

  /** Read or update notification throttles. Passing {} reads without changing. */
  notificationSettings: (patch: Record<string, unknown> = {}) =>
    ipcRenderer.invoke('smartdesk:notification-settings', patch),
})
