console.log('Starting test...');
console.log('ELECTRON_RUN_AS_NODE:', process.env.ELECTRON_RUN_AS_NODE);
try {
  const electron = require('electron');
  console.log('Require electron result type:', typeof electron);
  if (typeof electron === 'string') {
    console.log('ERROR: electron is a string:', electron);
    console.log('This indicates ELECTRON_RUN_AS_NODE is set incorrectly');
    process.exit(1);
  } else if (typeof electron === 'object' && electron.app) {
    console.log('SUCCESS: electron module loaded correctly');
    console.log('Electron version:', electron.version || 'unknown');
    const { app, BrowserWindow } = electron;
    console.log('app and BrowserWindow imported successfully');
    // Don't actually create a window, just test that we can import
    process.exit(0);
  } else {
    console.log('UNEXPECTED: electron is', typeof electron, electron);
    process.exit(1);
  }
} catch (error) {
  console.log('ERROR requiring electron:', error.message);
  process.exit(1);
}
