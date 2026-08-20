import {
  app,
  BrowserWindow,
  Notification,
  dialog,
  ipcMain,
  shell,
  screen as electronScreen,
} from 'electron'
import { writeFile } from 'fs/promises'
import { join } from 'path'

const BACKEND = process.env['VITE_BACKEND_URL'] || 'http://127.0.0.1:8000'

let mainWindow: BrowserWindow | null = null
let breakWindow: BrowserWindow | null = null

function createWindow() {
  const { width, height } = electronScreen.getPrimaryDisplay().workAreaSize
  const win = new BrowserWindow({
    width: Math.min(1200, width),
    height: Math.min(800, height),
    webPreferences: {
      // Built output is out/main/main.js and out/preload/preload.js, so the
      // preload sits in a sibling directory. '../preload.js' resolved to
      // out/preload.js, which does not exist — the preload never loaded and
      // `electronAPI` was silently missing from the renderer.
      preload: join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (app.isPackaged) {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  } else if (process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadURL('http://localhost:5173')
  }

  mainWindow = win
  win.on('closed', () => { mainWindow = null })
  return win
}

/* ------------------------------------------------------------------ */
/* Notification throttling                                             */
/*                                                                     */
/* The risk with a live rule engine is not being wrong, it is being     */
/* annoying — an interruption to tell you that you are being            */
/* interrupted. Every limit below exists to make that structurally      */
/* impossible rather than a matter of tuning.                           */
/* ------------------------------------------------------------------ */

/** No two toasts closer together than this, whatever fires. */
const MIN_GAP_MS = 45 * 60 * 1000
/** Hard ceiling per calendar day. */
const MAX_PER_DAY = 4
/** How often the main process asks the backend what is active. */
const POLL_MS = 60 * 1000

interface NotifyState {
  lastShownAt: number
  shownToday: number
  today: string
  /** Recommendation ids already surfaced, so a card is never shown twice. */
  seen: Set<string>
  /** Rule ids the user has muted from a toast. */
  muted: Set<string>
  /** Suppressed until this timestamp — set while a break is running. */
  suppressedUntil: number
  enabled: boolean
  quietFrom: number
  quietTo: number
}

const state: NotifyState = {
  lastShownAt: 0,
  shownToday: 0,
  today: new Date().toDateString(),
  seen: new Set(),
  muted: new Set(),
  suppressedUntil: 0,
  enabled: true,
  // Defaults chosen to be uncontroversial rather than clever; the Settings
  // page overrides them, and the backend's own stop-hour percentile is a
  // better source once there is enough history to trust it.
  quietFrom: 23,
  quietTo: 7,
}

function inQuietHours(now: Date): boolean {
  const hour = now.getHours()
  return state.quietFrom > state.quietTo
    ? hour >= state.quietFrom || hour < state.quietTo
    : hour >= state.quietFrom && hour < state.quietTo
}

function mayNotify(now: Date): boolean {
  if (!state.enabled) return false
  if (Date.now() < state.suppressedUntil) return false
  if (inQuietHours(now)) return false

  const today = now.toDateString()
  if (today !== state.today) {
    state.today = today
    state.shownToday = 0
    state.seen.clear()
  }
  if (state.shownToday >= MAX_PER_DAY) return false
  return Date.now() - state.lastShownAt >= MIN_GAP_MS
}

async function sendFeedback(id: string, action: string): Promise<void> {
  try {
    await fetch(`${BACKEND}/api/v1/recommendations/${id}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
  } catch {
    // Feedback is a preference, not a transaction. Losing one costs the
    // ranker a training row and the user nothing.
  }
}

async function pollRecommendations(): Promise<void> {
  const now = new Date()
  if (!mayNotify(now)) return

  let payload: any
  try {
    const res = await fetch(`${BACKEND}/api/v1/recommendations?user_id=local_user`)
    if (!res.ok) return
    payload = await res.json()
  } catch {
    // Backend down or still starting. Nothing to report and nothing to fix
    // from here; the next tick will try again.
    return
  }

  const candidates: any[] = (payload?.sections?.immediate ?? []).filter(
    (rec: any) =>
      rec.severity === 'high' &&
      rec.scope === 'live' &&
      rec.status === 'active' &&
      !state.seen.has(rec.id) &&
      !state.muted.has(rec.rule_id),
  )
  if (candidates.length === 0) return

  // One at a time, highest scoring. Showing two at once would defeat the gap.
  const rec = candidates.sort((a, b) => b.score - a.score)[0]
  state.seen.add(rec.id)
  state.lastShownAt = Date.now()
  state.shownToday += 1

  const notification = new Notification({
    title: rec.title,
    body: rec.why,
    actions: [{ type: 'button', text: rec.action_label ?? 'Got it' }],
    closeButtonText: 'Dismiss',
    silent: false,
  })

  notification.on('action', () => {
    void sendFeedback(rec.id, 'applied')
    if (rec.action_label === 'Start Break') openBreakOverlay(5)
    if (rec.action_label === 'Resume Task') void resumeContext(rec.facts)
  })
  notification.on('click', () => {
    mainWindow?.show()
    mainWindow?.focus()
    void sendFeedback(rec.id, 'shown')
  })
  notification.on('close', () => { void sendFeedback(rec.id, 'dismissed') })

  notification.show()
  void sendFeedback(rec.id, 'shown')
}

/* ------------------------------------------------------------------ */
/* Start Break                                                         */
/* ------------------------------------------------------------------ */

/**
 * A frameless countdown that stays above other windows.
 *
 * Built as a data URL rather than a second renderer entry point: it is forty
 * lines of markup with no imports, and adding a build target for it would cost
 * more than it saves.
 */
function breakMarkup(minutes: number): string {
  return `<!doctype html><meta charset="utf-8"><style>
    :root { color-scheme: dark; }
    body { margin:0; height:100vh; display:flex; flex-direction:column;
           align-items:center; justify-content:center; gap:18px;
           background:#12161d; color:#e6eaf2;
           font-family:"Segoe UI",system-ui,sans-serif; -webkit-app-region:drag; }
    #t { font-size:64px; font-weight:600; font-variant-numeric:tabular-nums;
         letter-spacing:-0.02em; }
    p { margin:0; color:#98a1ae; font-size:14px; }
    button { -webkit-app-region:no-drag; margin-top:8px; padding:8px 20px;
             border:1px solid #39414e; background:transparent; color:#e6eaf2;
             border-radius:4px; font-size:13px; cursor:pointer; }
    button:hover { background:#1c222b; }
  </style>
  <div id="t">${minutes}:00</div>
  <p>Step away from the screen. This closes itself.</p>
  <button onclick="window.close()">End break early</button>
  <script>
    let left = ${minutes} * 60;
    const el = document.getElementById('t');
    setInterval(() => {
      left -= 1;
      if (left <= 0) { window.close(); return; }
      const m = Math.floor(left / 60), s = left % 60;
      el.textContent = m + ':' + String(s).padStart(2, '0');
    }, 1000);
  </script>`
}

function openBreakOverlay(minutes: number): void {
  if (breakWindow) { breakWindow.focus(); return }

  breakWindow = new BrowserWindow({
    width: 420,
    height: 280,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    center: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })
  breakWindow.loadURL(
    'data:text/html;charset=utf-8,' + encodeURIComponent(breakMarkup(minutes)),
  )

  // Suppress notifications for the break plus a short tail. Without this the
  // next tick fires the very rule the break was taken in response to.
  state.suppressedUntil = Date.now() + (minutes + 5) * 60 * 1000
  breakWindow.on('closed', () => { breakWindow = null })
}

/* ------------------------------------------------------------------ */
/* Resume Task                                                         */
/* ------------------------------------------------------------------ */

/**
 * Reopen the context recorded before an interruption.
 *
 * The last work segment already carries everything needed: the app name, the
 * window title, and a detail holding either a URL or a file path. Where none
 * of it resolves the caller still has the title to show, which is most of the
 * value — knowing what you were doing beats reopening it.
 */
async function resumeContext(facts: Record<string, unknown> | undefined): Promise<boolean> {
  const detail = typeof facts?.detail === 'string' ? facts.detail : null
  if (detail && /^https?:\/\//i.test(detail)) {
    await shell.openExternal(detail)
    return true
  }
  if (detail) {
    const error = await shell.openPath(detail)
    return error === ''
  }
  return false
}

/* ------------------------------------------------------------------ */
/* IPC                                                                 */
/* ------------------------------------------------------------------ */

ipcMain.handle('smartdesk:start-break', (_event, minutes: number) => {
  openBreakOverlay(Math.max(1, Math.min(60, Math.round(minutes || 5))))
  return true
})

ipcMain.handle('smartdesk:resume-task', async (_event, facts) => resumeContext(facts))

ipcMain.handle('smartdesk:notification-settings', (_event, patch) => {
  if (typeof patch?.enabled === 'boolean') state.enabled = patch.enabled
  if (typeof patch?.quietFrom === 'number') state.quietFrom = patch.quietFrom
  if (typeof patch?.quietTo === 'number') state.quietTo = patch.quietTo
  if (typeof patch?.muteRule === 'string') state.muted.add(patch.muteRule)
  if (typeof patch?.unmuteRule === 'string') state.muted.delete(patch.unmuteRule)
  return {
    enabled: state.enabled,
    quietFrom: state.quietFrom,
    quietTo: state.quietTo,
    muted: [...state.muted],
    shownToday: state.shownToday,
  }
})


/* ------------------------------------------------------------------ */
/* PDF export                                                          */
/* ------------------------------------------------------------------ */

/**
 * Print a report to PDF.
 *
 * The page is fetched from the backend rather than scraped from the visible
 * window: the on-screen report is styled for the app's theme and laid out for
 * a viewport, while `/reports/{scope}/html` is styled for paper. Printing what
 * is on screen would produce a dark-background PDF with a navigation bar in it.
 *
 * Rendered in an offscreen window that is always destroyed, including on the
 * failure paths — a leaked BrowserWindow keeps the process alive after the
 * last visible window closes.
 */
async function exportReportPdf(scope: string, date?: string): Promise<string | null> {
  const params = new URLSearchParams({ user_id: 'local_user' })
  if (date) params.append('date', date)
  const url = `${BACKEND}/api/v1/reports/${scope}/html?${params.toString()}`

  const target = await dialog.showSaveDialog({
    title: 'Export report',
    defaultPath: `smartdesk_${scope}_${date ?? 'latest'}.pdf`,
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  })
  if (target.canceled || !target.filePath) return null

  const offscreen = new BrowserWindow({
    show: false,
    webPreferences: { offscreen: true, contextIsolation: true, nodeIntegration: false },
  })
  try {
    await offscreen.loadURL(url)
    const pdf = await offscreen.webContents.printToPDF({
      printBackground: true,
      pageSize: 'A4',
    })
    await writeFile(target.filePath, pdf)
    return target.filePath
  } catch {
    return null
  } finally {
    offscreen.destroy()
  }
}

ipcMain.handle('smartdesk:export-pdf', async (_event, scope: string, date?: string) =>
  exportReportPdf(scope, date),
)

app.whenReady().then(() => {
  ipcMain.handle('open-github-external', async (_event, rawUrl: string) => {
    const url = new URL(rawUrl)
    if (url.protocol !== 'https:' || url.hostname !== 'github.com') {
      throw new Error('Only HTTPS GitHub links may be opened externally')
    }
    await shell.openExternal(url.toString())
  })

  /* Google spreads the consent flow across two hosts depending on the account
     state, so both are allowed — and nothing else is. The URL comes from our
     own backend, but this handler is reachable from any renderer code, so it
     validates rather than trusts. */
  ipcMain.handle('open-calendar-external', async (_event, rawUrl: string) => {
    const url = new URL(rawUrl)
    const allowed = ['accounts.google.com', 'accounts.youtube.com']
    if (url.protocol !== 'https:' || !allowed.includes(url.hostname)) {
      throw new Error('Only the Google consent screen may be opened externally')
    }
    await shell.openExternal(url.toString())
  })
  createWindow()
  if (Notification.isSupported()) {
    setInterval(() => { void pollRecommendations() }, POLL_MS)
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})
