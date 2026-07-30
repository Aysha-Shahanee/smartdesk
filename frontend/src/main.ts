import { app, BrowserWindow, screen as electronScreen } from 'electron'
import { join } from 'path'

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
}

app.whenReady().then(createWindow)

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
