// Starts and looks after Jervis's backend (the Python program that listens, thinks and acts).
//
// The window is the parent: it picks a free port and a secret for the connection between the two, starts the
// backend, restarts it when it asks to (new settings) or when it crashes, and stops it when Jervis quits.
//   - Installed app: the bundled backend in resources/backend/.
//   - Running from source (npm start): venv's Python running app.py, exactly the code run.py always ran.
//   - Attach mode: a backend is already running (started by the wake listener); only connect to it.
const { spawn, execFile } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const path = require('path');

const RESTART_EXIT_CODE = 75;   // the backend applied new settings and wants a fresh start
const PORT_BUSY_EXIT_CODE = 76; // the port was taken between choosing it and using it
const CRASH_WINDOW_MS = 2 * 60 * 1000;
const MAX_CRASHES = 5;          // this many crashes within CRASH_WINDOW_MS: stop retrying and explain

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function waitForPort(port, timeoutMs) {
  const started = Date.now();
  return new Promise((resolve) => {
    const attempt = () => {
      const socket = net.connect(port, '127.0.0.1');
      socket.once('connect', () => { socket.destroy(); resolve(true); });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() - started > timeoutMs) resolve(false);
        else setTimeout(attempt, 250);
      });
    };
    attempt();
  });
}

class Backend {
  constructor({ app, appDir, log, onState }) {
    this.app = app;
    this.appDir = appDir;
    this.log = log;
    this.onState = onState;          // (state, detail) -> the window shows it
    this.child = null;
    this.port = null;
    this.token = crypto.randomBytes(24).toString('hex');
    this.crashes = [];
    this.stopping = false;
    this.attached = false;
  }

  get url() {
    return `ws://127.0.0.1:${this.port}/?token=${this.token}`;
  }

  command() {
    if (this.app.isPackaged) {
      const exe = process.platform === 'win32' ? 'jervis-backend.exe' : 'jervis-backend';
      return { file: path.join(process.resourcesPath, 'backend', exe), args: [], cwd: path.join(process.resourcesPath, 'backend') };
    }
    const venvPython = process.platform === 'win32'
      ? path.join(this.appDir, 'venv', 'Scripts', 'python.exe')
      : path.join(this.appDir, 'venv', 'bin', 'python');
    const python = process.env.JERVIS_PYTHON || (fs.existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3'));
    return { file: python, args: [path.join(this.appDir, 'app.py')], cwd: this.appDir };
  }

  async start() {
    if (process.env.JERVIS_ATTACH_PORT) {   // a backend started by the wake listener asked for this window
      this.attached = true;
      this.port = Number(process.env.JERVIS_ATTACH_PORT);
      this.token = process.env.JERVIS_WS_TOKEN || '';
      this.log(`Attaching to the running backend on port ${this.port}.`);
      this.onState('running');
      return;
    }
    this.port = this.port || await freePort();
    this.spawn();
  }

  // Opened by "Hey Jervis" (wake/jervis_wake.py): only the first engine greets, not one restarted later.
  consumeWakeGreeting() {
    const woken = process.env.JERVIS_WOKEN_BY_VOICE === '1';
    delete process.env.JERVIS_WOKEN_BY_VOICE;
    return woken ? '1' : '';
  }

  spawn() {
    const { file, args, cwd } = this.command();
    const env = {
      ...process.env,
      JERVIS_SUPERVISED: '1',
      JERVIS_PARENT_PID: String(process.pid),   // the engine stops by itself if this window is gone
      JERVIS_WOKEN_BY_VOICE: this.consumeWakeGreeting(),
      JERVIS_WS_PORT: String(this.port),
      JERVIS_WS_TOKEN: this.token,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    };
    if (this.app.isPackaged) env.JERVIS_DATA_DIR = this.app.getPath('userData');
    delete env.JERVIS_ATTACH_PORT;
    this.log(`Starting the backend: ${file} ${args.join(' ')} (port ${this.port})`);
    this.onState('starting');
    let child;
    try {
      child = spawn(file, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (error) {
      this.failed(`Jervis's engine could not start: ${error.message}`);
      return;
    }
    this.child = child;
    const forward = (stream) => stream.on('data', (chunk) => { if (!this.app.isPackaged) process.stdout.write(chunk); });
    forward(child.stdout);
    forward(child.stderr);
    child.on('error', (error) => this.failed(`Jervis's engine could not start: ${error.message}`));
    child.on('exit', (code, signal) => this.exited(child, code, signal));
    waitForPort(this.port, 120000).then((up) => {
      if (this.child === child && up) this.onState('running');
    });
  }

  exited(child, code, signal) {
    if (this.child !== child) return;
    this.child = null;
    if (this.stopping) return;
    this.log(`The backend exited (code ${code}, signal ${signal}).`);
    if (code === RESTART_EXIT_CODE) { this.spawn(); return; }
    if (code === PORT_BUSY_EXIT_CODE) {
      freePort().then((port) => { this.port = port; this.onState('port-changed'); this.spawn(); });
      return;
    }
    const now = Date.now();
    this.crashes = this.crashes.filter((t) => now - t < CRASH_WINDOW_MS).concat(now);
    if (this.crashes.length >= MAX_CRASHES) {
      this.failed('Jervis’s engine keeps stopping. The details are in the log file (Settings, Diagnostics).');
      return;
    }
    const delay = Math.min(30000, 1000 * 2 ** (this.crashes.length - 1));
    this.onState('restarting', `Jervis’s engine stopped unexpectedly; restarting in ${Math.round(delay / 1000)} s.`);
    setTimeout(() => { if (!this.stopping && !this.child) this.spawn(); }, delay);
  }

  failed(message) {
    this.log(message);
    this.onState('failed', message);
  }

  restart() {
    this.crashes = [];
    if (this.attached) return;
    if (this.child) {
      const child = this.child;
      this.child = null;
      this.kill(child).then(() => this.spawn());
    } else {
      this.spawn();
    }
  }

  kill(child) {
    return new Promise((resolve) => {
      if (!child || child.exitCode !== null) { resolve(); return; }
      const done = setTimeout(resolve, 4000);
      child.once('exit', () => { clearTimeout(done); resolve(); });
      if (process.platform === 'win32') {
        // the backend starts helper programs (voices, PowerShell); end the whole tree
        execFile('taskkill', ['/pid', String(child.pid), '/t', '/f'], () => {});
      } else {
        child.kill('SIGTERM');
        setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, 2500);
      }
    });
  }

  async stop() {
    this.stopping = true;
    if (this.child) {
      const child = this.child;
      this.child = null;
      await this.kill(child);
    }
  }
}

module.exports = { Backend, freePort, RESTART_EXIT_CODE, PORT_BUSY_EXIT_CODE };
