const electron = require('electron')
console.log('electron type:', typeof electron)
console.log('electron value:', electron)
if (electron && typeof electron === 'object') {
  console.log('electron keys:', Object.keys(electron))
}
const { app, BrowserWindow, screen } = electron
console.log('app:', app)
console.log('BrowserWindow:', BrowserWindow)
console.log('screen:', screen)
const { join } = require('path')

function createWindow() {
  console.log('Creating window...')
  const { width, height } = screen.getPrimaryDisplay().workAreaSize
  const win = new BrowserWindow({
    width: Math.min(1200, width),
    height: Math.min(800, height),
    webPreferences: {
      preload: join(__dirname, '../preload.js'),
      // Enable context isolation for security
      contextIsolation: true,
      // Disable nodeIntegration for security
      nodeIntegration: false,
    },
  })

  if (app.isPackaged) {
    // Production mode: load index.html from built files
    win.loadFile(join(__dirname, '../renderer/index.html'))
  } else {
    // Development mode: load via Vite dev server
    if (process.env['ELECTRON_RENDERER_URL']) {
      win.loadURL(process.env['ELECTRON_RENDERER_URL'])
    } else {
      win.loadURL('http://localhost:5173')
    }
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