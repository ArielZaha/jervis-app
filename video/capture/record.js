// Records real footage of Jarvis: the actual window page (index.html), the actual phone app (phone_client.html) or
// the actual control bar (control.html), drawn off screen and filmed frame by frame on a hand-driven clock
// (clock.js), so every clip is an exact 30 frames per second.
//
//   electron video/capture/record.js <shot> [<shot> ...]
//
// Each shot is a file in shots/: { kind, size, scale, url|file, query, run(shot) }. It writes
// assets/footage/<shot>.mp4 and <shot>.json (frame count and named marks the film's timeline cuts on).
const { app, BrowserWindow, session, screen } = require('electron');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

const VIDEO = path.join(__dirname, '..');
const ROOT = path.join(VIDEO, '..');
const OUT = path.join(VIDEO, 'assets', 'footage');
const FPS = 30;
const FFMPEG = process.env.FFMPEG || fs.readdirSync(path.join(VIDEO, 'tools.nosync/py/imageio_ffmpeg/binaries'))
  .filter((n) => n.startsWith('ffmpeg')).map((n) => path.join(VIDEO, 'tools.nosync/py/imageio_ffmpeg/binaries', n))[0];
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const ANDROID = 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36';

app.commandLine.appendSwitch('force-color-profile', 'srgb');
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-background-timer-throttling');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
app.commandLine.appendSwitch('use-fake-device-for-media-stream');
if (process.env.CAPTURE_CAMERA) app.commandLine.appendSwitch('use-file-for-fake-video-capture', process.env.CAPTURE_CAMERA);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A fresh demo engine for one shot (capture/backend.py): an empty conversation, and its greeting when the window opens.
const quitBackend = () => fetch(`http://127.0.0.1:${process.env.CTRL || 18941}/quit`).catch(() => {});

async function startBackend(extraEnv = {}) {
  await quitBackend();   // one left over from an interrupted recording would answer instead of the new one
  await sleep(600);
  const log = fs.openSync(path.join(VIDEO, 'cache.nosync', 'backend.log'), 'w');
  const child = spawn(path.join(ROOT, 'venv/bin/python'), [path.join(__dirname, 'backend.py')],
    { cwd: ROOT, env: { ...process.env, PYTHONUNBUFFERED: '1', ...extraEnv }, stdio: ['ignore', log, log] });
  const port = Number(process.env.PORT || 18940);
  for (let i = 0; i < 240; i++) {
    const up = await new Promise((resolve) => {
      const socket = net.connect(port, '127.0.0.1');
      socket.once('connect', () => { socket.destroy(); resolve(true); });
      socket.once('error', () => resolve(false));
    });
    if (up) return child;
    await sleep(250);
  }
  child.kill();
  throw new Error('the demo engine did not start (see cache.nosync/backend.log)');
}

// The phone relay, put together from the same files the Dockerfile copies (so it is what runs on the real server).
async function startRelay() {
  const dir = path.join(VIDEO, 'cache.nosync', 'relay');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'brain', 'geo_data'), { recursive: true });
  const copy = (from, to = from) => fs.cpSync(path.join(ROOT, from), path.join(dir, to), { recursive: true });
  copy('relay/server.py', 'server.py');
  for (const f of ['phone_client.html', 'phone_sw.js', 'confirm.html', 'phone_manifest.webmanifest', 'phone_agent.js', 'sphere_gl.js',
    'graph.js', 'earth.js', 'planet.js', 'phone_brain_worker.js', 'phone_icons', 'vendor/earth', 'vendor/planets', 'vendor/jsqr', 'vendor/fonts']) copy(f);
  for (const f of ['typos.py', 'functions.py', 'equations.py', 'graphs.py', 'geo.py', 'earth.py', 'planets.py', 'timers.py', 'forecast.py',
    'music.py', 'phone_brain.py']) copy(f, 'brain/' + f);
  for (const f of ['countries_50m.json', 'places_10m.json']) copy('geo_data/' + f, 'brain/geo_data/' + f);
  const log = fs.openSync(path.join(VIDEO, 'cache.nosync', 'relay.log'), 'w');
  const child = spawn(path.join(ROOT, 'venv/bin/python'), ['server.py'], { cwd: dir, env: { ...process.env, PORT: String(RELAY_PORT) }, stdio: ['ignore', log, log] });
  for (let i = 0; i < 80; i++) {
    try { await fetch(`http://127.0.0.1:${RELAY_PORT}/`); return child; } catch (e) { await sleep(250); }
  }
  throw new Error('the relay did not start (see cache.nosync/relay.log)');
}
const RELAY_PORT = 18943;

async function record(name) {
  const def = require(path.join(__dirname, 'shots', name + '.js'));
  spawn('pkill', ['-f', path.join(VIDEO, 'cache.nosync', 'relay')]);
  const relay = def.relay ? await startRelay() : null;
  const env = def.backend === true ? {} : { ...def.backend };
  if (relay) Object.assign(env, { DEMO_PHONE: 'on', RELAY: `ws://127.0.0.1:${RELAY_PORT}/` });
  const engine = def.backend ? await startBackend(env) : null;
  try { await film(name, def); } finally {
    if (engine) { await quitBackend(); await sleep(400); engine.kill('SIGKILL'); }
    if (relay) spawn('pkill', ['-f', path.join(VIDEO, 'cache.nosync', 'relay')]);
  }
}

async function film(name, def) {
  const [width, height] = def.size || [1440, 810];
  const scale = screen.getPrimaryDisplay().scaleFactor;   // off-screen pages are drawn at the display's own density
  const phone = def.kind === 'phone' || def.kind === 'android';
  const ses = session.fromPartition(def.partition || `shot-${name}-${Date.now()}`);
  const opened = [];   // links the page tried to open in other apps (never really opened)
  ses.setPermissionRequestHandler((contents, permission, done, details) => {
    if (permission === 'openExternal') {
      // A link into another app (spotify:, youtube://...). It is never really opened here; the page is told what a
      // phone tells it when the other app comes to the front: that it went to the background for a moment.
      opened.push(details.externalURL);
      done(false);
      contents.executeJavaScript(`(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
        setTimeout(() => { delete document.hidden; delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange')); }, 900);
      })()`, true).catch(() => {});
      return;
    }
    done(true);
  });
  const win = new BrowserWindow({
    width, height, show: false, frame: false, backgroundColor: '#05070d', useContentSize: true,
    webPreferences: {
      offscreen: true, session: ses, contextIsolation: false, sandbox: false, nodeIntegration: def.kind === 'desktop',
      preload: path.join(__dirname, def.preload || (phone ? 'preload-phone.js' : 'clock.js')), backgroundThrottling: false,
    },
  });
  const wc = win.webContents;
  wc.setFrameRate(60);
  wc.setWindowOpenHandler(({ url }) => { opened.push(url); return { action: 'deny' }; });
  if (phone) wc.setUserAgent(def.kind === 'android' ? ANDROID : IPHONE);
  wc.on('console-message', (_e, level, message) => { if (level >= 2 && process.env.CAPTURE_LOG) console.log(`[page] ${message}`); });
  wc.debugger.attach('1.3');

  const ctrl = async (pathAndQuery) => (await fetch(`http://127.0.0.1:${process.env.CTRL || 18941}${pathAndQuery}`)).json();
  if (def.file) await wc.loadFile(path.join(ROOT, def.file), { query: def.query || {} });
  else await wc.loadURL(def.url || await def.open({ ctrl, sleep }));
  if (def.kind === 'desktop') {   // what main.js tells the page once it has loaded
    wc.send('backend-state', { state: 'running', detail: '' });
    wc.send('window-visibility', true);
  }

  // A second window filmed in step with the first: the computer's own window, while a phone shot is being filmed.
  // Both pages share one clock (each frame steps both), so the two clips line up frame for frame.
  let desk = null;
  if (def.companion) {
    const second = new BrowserWindow({
      width: 1440, height: 810, show: false, frame: false, backgroundColor: '#05070d', useContentSize: true,
      webPreferences: { offscreen: true, session: session.fromPartition(`desk-${name}-${Date.now()}`), contextIsolation: false, sandbox: false,
        nodeIntegration: true, preload: path.join(__dirname, 'clock.js'), backgroundThrottling: false },
    });
    second.webContents.setFrameRate(60);
    second.webContents.debugger.attach('1.3');
    await second.webContents.loadFile(path.join(ROOT, 'index.html'), { query: { ws: `ws://127.0.0.1:${process.env.PORT || 18940}`, ui: process.env.LOOK || 'classic' } });
    second.webContents.send('backend-state', { state: 'running', detail: '' });
    second.webContents.send('window-visibility', true);
    desk = { win: second, wc: second.webContents, js: (code) => second.webContents.executeJavaScript(code, true), ffmpeg: null };
  }

  const pxW = Math.round(width * scale), pxH = Math.round(height * scale);
  let ffmpeg = null, frames = 0, recording = false;
  const marks = {}, notes = {}, lines = [];
  let rate = 1;   // how fast the page's clock runs against the film's (2 = filmed at double speed, still 30 smooth frames a second)
  const file = path.join(OUT, name + '.mp4');
  const encoder = (w, h, to) => spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-vf', `scale=${w - (w % 2)}:${h - (h % 2)}:flags=lanczos`, '-c:v', 'libx264', '-preset', 'medium',
    '-crf', String(def.crf || 17), '-pix_fmt', 'yuv420p', '-g', '15', '-movflags', '+faststart', to], { stdio: ['pipe', 'inherit', 'inherit'] });
  function startEncoder() {
    fs.mkdirSync(OUT, { recursive: true });
    ffmpeg = encoder(pxW, pxH, file);
    if (desk) desk.ffmpeg = encoder(1440 * scale, 810 * scale, path.join(OUT, name + '.desk.mp4'));
  }
  const write = async (pipe, data) => { if (!pipe.stdin.write(Buffer.from(data, 'base64'))) await new Promise((r) => pipe.stdin.once('drain', r)); };
  const js = (code) => wc.executeJavaScript(code, true);
  async function frame(count = 1) {
    for (let i = 0; i < count; i++) {
      const step = `__clock.step(${(1000 / FPS * rate).toFixed(4)})`;
      await Promise.all([js(step), desk ? desk.js(step) : null]);
      if (!recording) continue;
      const grab = (contents) => contents.debugger.sendCommand('Page.captureScreenshot', { format: 'jpeg', quality: 96, fromSurface: true });
      await write(ffmpeg, (await grab(wc)).data);
      if (desk) await write(desk.ffmpeg, (await grab(desk.wc)).data);
      frames++;
    }
  }
  const shot = {
    name, wc, opened, js, frame,
    start() { if (!ffmpeg) startEncoder(); recording = true; },
    pause() { recording = false; },
    mark(label) { marks[label] = frames; },
    hold: (ms) => frame(Math.max(1, Math.round(ms * FPS / 1000))),
    // Let real time pass (a reply from the AI, a download) while the page's clock barely moves and nothing is filmed.
    async wait(test, { timeout = 60000, every = 150 } = {}) {
      const was = recording, until = Date.now() + timeout;
      recording = false;
      while (Date.now() < until) {
        await frame(1);
        if (await js(`!!(${test})`)) { recording = was; return true; }
        await sleep(every);
      }
      recording = was;
      throw new Error(`${name}: waited ${timeout} ms for ${test}`);
    },
    // Keep filming until the page reaches a state (so the wait itself is in the footage, in the page's own time).
    async until(test, { max = 20000 } = {}) {
      for (let i = 0; i < max * FPS / 1000; i++) {
        await frame(1);
        if (await js(`!!(${test})`)) return true;
      }
      throw new Error(`${name}: filmed ${max} ms waiting for ${test}`);
    },
    // Type into a field the way a person does: a character at a time, at an uneven pace.
    async type(selector, text, { cps = 17 } = {}) {
      await js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.focus(); el.value = ''; })()`);
      let seed = 7;
      for (let i = 1; i <= text.length; i++) {
        await js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.value = ${JSON.stringify(text.slice(0, i))};
          el.dispatchEvent(new Event('input', { bubbles: true })); })()`);
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        const pause = text[i - 1] === ' ' ? 1.5 : 0.6 + (seed % 100) / 110;
        await frame(Math.max(1, Math.round(FPS / cps * pause)));
      }
    },
    // The demo engine's control door (backend.py): /say, /heard, /hush, /state, /ui, /call
    ctrl, desk,
    note(key, value) { notes[key] = value; },
    // Jarvis says his latest reply. The sound is made the way the app makes it on this Mac (the system's `say`
    // voice), saved next to the footage, and the orb stays in its speaking state for as long as the line lasts (or
    // for `most` ms: after that the film cuts away, as when someone asks the next thing).
    async speak({ most = 60000, lead = 0 } = {}) {
      const said = (await ctrl('/state')).said.pop() || '';
      const dir = path.join(VIDEO, 'assets', 'voice');
      fs.mkdirSync(dir, { recursive: true });
      const base = path.join(dir, `${name}_${String(lines.length + 1).padStart(2, '0')}`);
      execFileSync('say', [...(process.env.JARVIS_VOICE ? ['-v', process.env.JARVIS_VOICE] : []), '-o', base + '.aiff', said]);
      execFileSync('afconvert', ['-f', 'WAVE', '-d', 'LEI16@48000', '-c', '1', base + '.aiff', base + '.wav']);
      fs.rmSync(base + '.aiff');
      const seconds = (fs.statSync(base + '.wav').size - 44) / 96000;
      lines.push({ file: path.basename(base + '.wav'), frame: frames + Math.round(lead * FPS / 1000), text: said, seconds: +seconds.toFixed(2) });
      await frame(Math.max(1, Math.round(Math.min(seconds * 1000 + 150, most) * FPS / 1000)));
      await ctrl('/hush');
      return said;
    },
    // Ease the page's clock to a new speed over some frames (a time-lapse without a jolt).
    async speed(to, over = 30) {
      const from = rate;
      for (let i = 1; i <= over; i++) { const p = i / over; rate = from + (to - from) * (p * p * (3 - 2 * p)); await frame(1); }
      rate = to;
    },
    async still(fileName) {
      const image = await wc.debugger.sendCommand('Page.captureScreenshot', { format: 'jpeg', quality: 80, fromSurface: true });
      const dir = path.join(VIDEO, 'cache.nosync', 'stills');
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, fileName + '.jpg'), Buffer.from(image.data, 'base64'));
    },
    // Choose a file in a file field, as the paperclip button's file picker would.
    async attach(selector, filePath) {
      const { root } = await wc.debugger.sendCommand('DOM.getDocument', {});
      const { nodeId } = await wc.debugger.sendCommand('DOM.querySelector', { nodeId: root.nodeId, selector });
      await wc.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files: [filePath] });
    },
    click: (selector) => js(`document.querySelector(${JSON.stringify(selector)}).click()`),
    key: async (key, code) => {
      for (const type of ['keyDown', 'keyUp']) wc.sendInputEvent({ type, keyCode: key });
    },
  };

  try {
    await frame(2);
    await def.run(shot);
  } finally {
    if (ffmpeg) {
      ffmpeg.stdin.end();
      await new Promise((r) => ffmpeg.on('close', r));
      if (desk && desk.ffmpeg) { desk.ffmpeg.stdin.end(); await new Promise((r) => desk.ffmpeg.on('close', r)); }
      fs.writeFileSync(path.join(OUT, name + '.json'), JSON.stringify(
        { name, frames, fps: FPS, width: pxW - (pxW % 2), height: pxH - (pxH % 2), marks, notes, lines, opened }, null, 1));
      console.log(`${name}: ${frames} frames (${(frames / FPS).toFixed(1)} s) -> ${path.relative(ROOT, file)}`);
    }
    try { wc.debugger.detach(); } catch (e) { /* already gone */ }
    win.destroy();
    if (desk) desk.win.destroy();
  }
}

app.whenReady().then(async () => {
  let failed = false;
  for (const name of process.argv.slice(2).filter((a) => !a.startsWith('-') && !a.endsWith('record.js'))) {
    try { await record(name); } catch (e) { failed = true; console.error(`FAILED ${name}: ${e.stack || e}`); }
  }
  app.exit(failed ? 1 : 0);
});
