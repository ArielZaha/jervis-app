const { app, BrowserWindow, ipcMain, session, systemPreferences, Tray, Menu, nativeImage, shell, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { Backend } = require('./backend');

let win = null;
let tray = null;
let quitting = false;
let backend = null;
let backendState = { state: 'starting', detail: '' };

// ---------- Main-process log (next to the backend's own log) ----------
function logFile() {
  const dir = app.isPackaged ? path.join(app.getPath('userData'), 'logs') : path.join(__dirname, 'logs');
  try { fs.mkdirSync(dir, { recursive: true }); } catch (_) { /* no log folder: logging below just fails quietly */ }
  return path.join(dir, 'window.log');
}
function log(message) {
  const line = `${new Date().toISOString()}  ${message}\n`;
  if (!app.isPackaged) process.stdout.write(line);
  try { fs.appendFileSync(logFile(), line); } catch (_) { /* never let logging break the app */ }
}

// ---------- One Jervis at a time ----------
if (!app.requestSingleInstanceLock()) {
  app.quit();   // a second copy would fight the first over the microphone: show the running one instead
} else {
  app.on('second-instance', () => showWindow());
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function setBackendState(state, detail = '') {
  backendState = { state, detail };
  if (state === 'port-changed' && win) { loadPage(); return; }
  if (win && !win.isDestroyed()) win.webContents.send('backend-state', backendState);
}

function loadPage() {
  win.loadFile('index.html', { query: { ws: backend.url } });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: '#05070d',
    title: 'Jervis',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    // On macOS the title bar melts into the app; the top bar of the page is the drag handle.
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 16 } } : {}),
    webPreferences: { contextIsolation: false, nodeIntegration: true },
  });
  loadPage();

  // The window only ever shows Jervis's own page: no navigating away, no pop-up windows.
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  // Closing the window hides it: Jervis keeps listening for "Hey Jervis" (quit from the tray or the menu).
  win.on('close', (event) => {
    if (quitting) return;
    event.preventDefault();
    if (win.isFullScreen()) {   // leaving full screen first avoids a black space on macOS
      win.once('leave-full-screen', () => win.hide());
      win.setFullScreen(false);
    } else {
      win.hide();
    }
  });

  win.on('enter-full-screen', () => win.webContents.send('fullscreen-state', true));
  win.on('leave-full-screen', () => win.webContents.send('fullscreen-state', false));
  win.webContents.on('did-finish-load', () => win.webContents.send('backend-state', backendState));
}

// Full screen: on wake-up Jervis asks for it; the F key toggles it, Esc leaves it.
ipcMain.on('window-fullscreen', (_event, on) => {
  if (!win) return;
  showWindow();
  win.setFullScreen(on === 'toggle' ? !win.isFullScreen() : Boolean(on));
});

// A finished timer brings the window to the front, even from behind other apps or minimized.
ipcMain.on('alert-focus', () => {
  if (!win) return;
  showWindow();
  win.setAlwaysOnTop(true);
  setTimeout(() => win && win.setAlwaysOnTop(false), 1500);
  if (process.platform === 'darwin' && app.dock) app.dock.bounce('critical');
});

// ---------- For the Settings screen ----------
ipcMain.handle('app-info', () => ({
  version: app.getVersion(),
  packaged: app.isPackaged,
  platform: process.platform,
  dataDir: app.isPackaged ? app.getPath('userData') : __dirname,
  logFile: logFile(),
  openAtLogin: app.getLoginItemSettings().openAtLogin,
}));
ipcMain.handle('open-path', (_event, which) => {
  const dataDir = app.isPackaged ? app.getPath('userData') : __dirname;
  const target = which === 'logs' ? path.dirname(logFile()) : dataDir;
  return shell.openPath(target);
});
ipcMain.handle('set-open-at-login', (_event, on) => {
  if (!app.isPackaged) return false;   // registering the development copy as a login item would start it from the repo
  app.setLoginItemSettings({ openAtLogin: Boolean(on), openAsHidden: true, args: ['--hidden'] });
  return app.getLoginItemSettings().openAtLogin;
});
ipcMain.on('restart-backend', () => backend && backend.restart());

// ---------- Tray: Jervis keeps running (and listening) with the window closed ----------
function createTray() {
  const file = process.platform === 'darwin' ? 'trayTemplate.png' : 'tray.png';
  const image = nativeImage.createFromPath(path.join(__dirname, 'assets', file));
  if (image.isEmpty()) return;
  tray = new Tray(image);
  tray.setToolTip('Jervis');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show Jervis', click: showWindow },
    { label: 'Restart Jervis’s engine', click: () => backend && backend.restart() },
    { type: 'separator' },
    { label: 'Quit Jervis', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', showWindow);
}

// Let the graphics chip do the drawing work where it can.
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('ignore-gpu-blocklist');

app.whenReady().then(async () => {
  // The window listens to the microphone only to measure how loud you are (the orb spins with your voice).
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => callback(permission === 'media'));
  if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
  backend = new Backend({ app, appDir: __dirname, log, onState: setBackendState });
  try {
    await backend.start();
  } catch (error) {
    log(`Could not start the backend: ${error.stack || error}`);
    dialog.showErrorBox('Jervis could not start', `Jervis’s engine could not be started.\n\n${error.message}`);
  }
  createWindow();
  createTray();
  if (process.argv.includes('--hidden')) win.hide();   // started at sign-in: listen quietly until "Hey Jervis"
});

app.on('activate', showWindow);   // macOS: clicking the Dock icon brings the window back
app.on('before-quit', () => { quitting = true; });
app.on('will-quit', (event) => {
  if (!backend || backend.stopping) return;
  event.preventDefault();
  backend.stop().then(() => app.quit());
});
app.on('window-all-closed', () => { /* windows only hide; quitting is explicit */ });
