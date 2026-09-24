const { app, BrowserWindow, ipcMain, session, systemPreferences } = require('electron');

function createWindow() {
  const win = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: '#05070d',
    title: 'Jervis',
    // On macOS the title bar melts into the app; the top bar of the page is the drag handle.
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 16 } } : {}),
    webPreferences: { contextIsolation: false, nodeIntegration: true },
  });
  win.loadFile('index.html');

  // Full screen: on wake-up Jervis asks for it; the F key toggles it, Esc leaves it.
  ipcMain.on('window-fullscreen', (_event, on) => {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    win.setFullScreen(on === 'toggle' ? !win.isFullScreen() : Boolean(on));
  });
  win.on('enter-full-screen', () => win.webContents.send('fullscreen-state', true));
  win.on('leave-full-screen', () => win.webContents.send('fullscreen-state', false));

  // A finished timer brings the window to the front, even from behind other apps or minimized.
  ipcMain.on('alert-focus', () => {
    if (win.isMinimized()) win.restore();
    win.show();
    win.setAlwaysOnTop(true);
    win.focus();
    setTimeout(() => win.setAlwaysOnTop(false), 1500);
    if (process.platform === 'darwin' && app.dock) app.dock.bounce('critical');
  });
}

// Let the graphics chip do the drawing work where it can.
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('ignore-gpu-blocklist');

app.whenReady().then(() => {
  // The window listens to the microphone only to measure how loud you are (the orb spins with your voice).
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => callback(permission === 'media'));
  if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
  createWindow();
});
app.on('window-all-closed', () => app.quit());
