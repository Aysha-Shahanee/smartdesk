// Preload scripts
// The preload script runs in the renderer context with access to Node.js APIs,
// but the exposed functions are limited to what we attach to `window` or via
// contextBridge.

import { contextBridge } from 'electron'
import { app } from 'electron'

// Expose some helpful variables to the renderer process.
contextBridge.exposeInMainWorld('electronAPI', {
  // Example: get the app version
  getAppVersion: () => app.getVersion(),
  // Example: get environment info
  getEnv: () => ({
    backendUrl: import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
  }),
})