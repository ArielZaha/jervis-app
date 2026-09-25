const { app, BrowserWindow, ipcMain, session, systemPreferences, Tray, Menu, nativeImage, shell, dialog, globalShortcut, screen } = require('electron');
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
// "Jervis --quit" closes the running copy properly (engine included): used by the install tests and scripts.
const quitRequested = process.argv.includes('--quit');
if (!app.requestSingleInstanceLock() || quitRequested) {
  app.quit();   // a second copy would fight the first over the microphone: show the running one instead
} else {
  app.on('second-instance', (_event, argv) => {
    if (argv.includes('--quit')) { log('Asked to quit by another launch.'); quitting = true; app.quit(); return; }
    showWindow();
  });
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  // Started in the background (at sign-in, or by "Hey Jervis"), Jervis isn't the active app: take the front.
  if (process.platform === 'darwin') app.focus({ steal: true });
  win.focus();
}

function setBackendState(state, detail = '') {
  backendState = { state, detail };
  if (state !== 'running' && controlActive()) {   // the engine went away mid-task: so did the task
    setControlState({ ...controlState, state: 'stopped', detail: 'Jervis’s engine stopped, so computer control stopped.' });
  }
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
    show: !process.argv.includes('--hidden'),   // started at sign-in: no window flashing up
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

  // The engine goes back to sleep while the window is closed (hidden) and greets you when a wake phrase opens it.
  const visibility = (visible) => () => { if (!win.isDestroyed()) win.webContents.send('window-visibility', visible); };
  win.on('hide', visibility(false));
  win.on('minimize', visibility(false));
  win.on('show', visibility(true));
  win.on('restore', visibility(true));
  win.on('enter-full-screen', () => win.webContents.send('fullscreen-state', true));
  win.on('leave-full-screen', () => win.webContents.send('fullscreen-state', false));
  win.webContents.on('did-finish-load', () => {
    win.webContents.send('backend-state', backendState);
    win.webContents.send('window-visibility', win.isVisible());
  });
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
  openAtLogin: startsAtLogin(),
}));
ipcMain.handle('open-path', (_event, which) => {
  const dataDir = app.isPackaged ? app.getPath('userData') : __dirname;
  const target = which === 'logs' ? path.dirname(logFile()) : dataDir;
  return shell.openPath(target);
});
ipcMain.handle('set-open-at-login', (_event, on) => {
  rememberStartChoice();
  return setStartAtLogin(Boolean(on));
});

// ---------- Starting at sign-in: hidden, listening for "Hey Jervis" ----------
// On by default for the installed app, so the wake phrase works right after signing in with nothing open. Windows
// gets a normal login item with --hidden. macOS login items can't pass --hidden any more (the window would pop up at
// every sign-in), so there it's a per-user LaunchAgent, which can; it's rewritten at every start in case the app moved.
const LAUNCH_AGENT = path.join(app.getPath('home'), 'Library', 'LaunchAgents', 'io.github.arielzaha.jervis.plist');
const START_CHOICE = path.join(app.getPath('userData'), 'start-at-login-chosen');

function startsAtLogin() {
  if (!app.isPackaged) return false;
  if (process.platform === 'darwin') return fs.existsSync(LAUNCH_AGENT);
  return app.getLoginItemSettings({ args: ['--hidden'], name: 'Jervis' }).openAtLogin;
}

function setStartAtLogin(on) {
  if (!app.isPackaged) return false;   // registering the development copy would start it from the repo
  try {
    if (process.platform === 'darwin') {
      if (on) {
        const xml = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        fs.mkdirSync(path.dirname(LAUNCH_AGENT), { recursive: true });
        fs.writeFileSync(LAUNCH_AGENT, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.github.arielzaha.jervis</string>
  <key>ProgramArguments</key><array><string>${xml(process.execPath)}</string><string>--hidden</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict>
</plist>
`);
      } else if (fs.existsSync(LAUNCH_AGENT)) {
        fs.unlinkSync(LAUNCH_AGENT);
      }
      app.setLoginItemSettings({ openAtLogin: false });   // the older kind of login item, from earlier versions
    } else {
      app.setLoginItemSettings({ openAtLogin: on, args: ['--hidden'], name: 'Jervis' });   // (the uninstaller removes "Jervis")
    }
  } catch (error) {
    log(`Could not change starting at sign-in: ${error}`);
  }
  return startsAtLogin();
}

function rememberStartChoice() {
  try { fs.writeFileSync(START_CHOICE, new Date().toISOString()); } catch (_) { /* asked again next time */ }
}

function applyStartAtLogin() {
  if (!app.isPackaged) return;
  if (!fs.existsSync(START_CHOICE)) {        // first start: on, until the user turns it off in Settings
    rememberStartChoice();
    const on = setStartAtLogin(true);
    log(`Starting at sign-in: ${on ? 'on' : 'could not be turned on'} (first start).`);
  } else if (process.platform === 'darwin' && startsAtLogin()) {
    setStartAtLogin(true);                   // refresh the app's location
  }
}
ipcMain.on('restart-backend', () => backend && backend.restart());

// ---------- Computer control: the overlay, the emergency shortcut, and getting the window out of the way ----------
// While Jervis uses the mouse and keyboard, a glowing edge and a bar with Pause and Stop sit on top of everything.
// The overlay never takes focus and lets clicks through (except on its bar), is left out of screenshots, and goes
// away a few seconds after the task ends. The backend decides everything; this only shows it and relays buttons.
const CONTROL_ACTIVE = new Set(['starting', 'observing', 'thinking', 'acting', 'waiting', 'paused']);
const STOP_ACCELERATOR = 'Control+Alt+Q';
const STOP_LABEL = process.platform === 'darwin' ? '⌃⌥Q' : 'Ctrl+Alt+Q';
let overlay = null;
let overlayReady = false;
let controlState = null;
let controlQuestion = null;   // a yes/no question asked while the window is out of the way
let hideOverlayTimer = null;
let windowSteppedAside = false;

function controlActive() { return Boolean(controlState && CONTROL_ACTIVE.has(controlState.state)); }

function createOverlay() {
  const area = screen.getPrimaryDisplay().workArea;   // the screen Jervis works on
  overlay = new BrowserWindow({
    ...area,
    transparent: true, frame: false, hasShadow: false, resizable: false, movable: false, minimizable: false,
    maximizable: false, fullscreenable: false, focusable: false, skipTaskbar: true, show: false, alwaysOnTop: true,
    backgroundColor: '#00000000',
    webPreferences: { preload: path.join(__dirname, 'control-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlay.setIgnoreMouseEvents(true, { forward: true });
  overlay.setContentProtection(true);   // not in screenshots, so Jervis's own vision never sees it
  overlay.webContents.on('will-navigate', (event) => event.preventDefault());
  overlay.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  overlay.webContents.on('did-finish-load', () => {
    overlayReady = true;
    if (controlState) overlay.webContents.send('control-event', { type: 'control', data: controlState });
    if (controlQuestion) overlay.webContents.send('control-event', controlQuestion);
  });
  overlay.on('closed', () => { overlay = null; overlayReady = false; });
  overlay.loadFile('control.html', { query: { shortcut: STOP_LABEL } });
}

function toOverlay(message) {
  if (overlay && overlayReady) overlay.webContents.send('control-event', message);
}

function stepAside() {
  // The window would cover the app Jervis is working in, and catch his clicks.
  if (!win || windowSteppedAside || !win.isVisible()) return;
  windowSteppedAside = true;
  if (win.isFullScreen()) {
    win.once('leave-full-screen', () => stepAsideNow());
    win.setFullScreen(false);
  } else {
    stepAsideNow();
  }
}
function stepAsideNow() {
  if (!win) return;
  log('Computer control: the window stepped aside.');
  // Only this window: app.hide() on a Mac would hide the overlay too. Before each click or key press the engine puts
  // the app being worked in first (screen_mac.py / screen_windows.py).
  if (process.platform === 'darwin') win.hide(); else win.minimize();
}

function setControlState(data) {
  controlState = data;
  clearTimeout(hideOverlayTimer);
  if (controlActive()) {
    if (!overlay) createOverlay();
    if (!overlay.isVisible()) {
      overlay.setBounds(screen.getPrimaryDisplay().workArea);   // the display may have changed since last time
      overlay.showInactive();
      log('Computer control: overlay shown.');
    }
    if (!globalShortcut.isRegistered(STOP_ACCELERATOR)) {
      const ok = globalShortcut.register(STOP_ACCELERATOR, () => relayControl('control_command', { action: 'stop' }));
      if (!ok) log(`Could not register the ${STOP_LABEL} stop shortcut (another app has it).`);
    }
    stepAside();
  } else {
    globalShortcut.unregister(STOP_ACCELERATOR);
    windowSteppedAside = false;
    controlQuestion = null;
    hideOverlayTimer = setTimeout(() => overlay && overlay.hide(), 3600);   // after the "Done" / "Stopped" note
    log(`Computer control ended (${data.state}).`);
  }
  toOverlay({ type: 'control', data });
}

function relayControl(type, fields) {
  // Button presses reach the backend through the main window's connection.
  if (win && !win.isDestroyed()) win.webContents.send('control-relay', { type, ...fields });
}

ipcMain.on('control-event', (_event, message) => {
  if (!message || typeof message !== 'object') return;
  if (message.type === 'control') {
    setControlState(message.data || {});
  } else if (message.type === 'control_confirm') {
    if (controlActive()) { controlQuestion = message; toOverlay(message); }
    else showWindow();   // asking before starting: the question is in the window
  } else if (message.type === 'control_confirm_done') {
    if (controlQuestion && controlQuestion.id === message.id) controlQuestion = null;
    toOverlay(message);
  }
});
ipcMain.on('control-overlay-action', (_event, action) => {
  if (['stop', 'pause', 'resume'].includes(action)) relayControl('control_command', { action });
});
ipcMain.on('control-overlay-answer', (_event, answer) => {
  if (answer && typeof answer.id === 'string') relayControl('control_answer', { id: answer.id, allow: answer.allow === true });
});
ipcMain.on('control-overlay-hover', (_event, over) => {
  if (!overlay) return;
  if (over) overlay.setIgnoreMouseEvents(false); else overlay.setIgnoreMouseEvents(true, { forward: true });
});

// ---------- Tray: Jervis keeps running (and listening) with the window closed ----------
function createTray() {
  const file = process.platform === 'darwin' ? 'trayTemplate.png' : 'tray.png';
  const image = nativeImage.createFromPath(path.join(__dirname, 'assets', file));
  if (image.isEmpty()) return;
  tray = new Tray(image);
  tray.setToolTip('Jervis: say “Hey Jervis”');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show Jervis', click: showWindow },
    { label: 'Restart Jervis’s engine', click: () => backend && backend.restart() },
    { type: 'separator' },
    { label: 'Quit Jervis (stops listening for “Hey Jervis”)', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', showWindow);
}

// Let the graphics chip do the drawing work where it can.
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
app.commandLine.appendSwitch('ignore-gpu-blocklist');

app.whenReady().then(async () => {
  if (quitRequested) return;   // nothing was running: nothing to do
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
  applyStartAtLogin();
  // (started with --hidden, at sign-in: the window stays hidden and Jervis listens quietly until "Hey Jervis")
});

app.on('activate', showWindow);   // macOS: clicking the Dock icon brings the window back
app.on('before-quit', () => { quitting = true; });
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('will-quit', (event) => {
  if (!backend || backend.stopping) return;
  event.preventDefault();
  backend.stop().then(() => app.quit());
});
app.on('window-all-closed', () => { /* windows only hide; quitting is explicit */ });
