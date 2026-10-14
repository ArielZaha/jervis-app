// Renders the film (film/index.html) to video, one exact frame at a time.
//
//   electron video/render.js                        the whole film  -> cache.nosync/film.mp4 (picture only)
//   electron video/render.js --from 12 --to 27      part of it      -> cache.nosync/part.mp4
//   electron video/render.js --stills 3,8.5,14      single frames   -> cache.nosync/stills/film_<t>.jpg
//   electron video/render.js --cues                 writes audio/cues.json (what the soundtrack is built from)
//
// The film page draws any moment on request (FILM.renderAt(seconds)); nothing in it runs on a real clock, so a
// render is identical every time and never drops a frame however slow the computer is.
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const VIDEO = __dirname;
const CACHE = path.join(VIDEO, 'cache.nosync');
const bin = path.join(VIDEO, 'tools.nosync/py/imageio_ffmpeg/binaries');
const FFMPEG = process.env.FFMPEG || path.join(bin, fs.readdirSync(bin).find((n) => n.startsWith('ffmpeg')));
const arg = (name, fallback) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : fallback; };
const has = (name) => process.argv.includes('--' + name);
const FILM = arg('film', 'scenes');                                   // scenes = the first film, showcase = the 90-second one
const tag = FILM === 'scenes' ? '' : '.' + FILM;

app.commandLine.appendSwitch('force-color-profile', 'srgb');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('disable-renderer-backgrounding');

app.whenReady().then(async () => {
  // The stage is 1920x1080, drawn at half size in a 960x540 window on a 2x display: exactly 1920x1080 pixels.
  const win = new BrowserWindow({
    width: 960, height: 540, show: false, frame: false, useContentSize: true, backgroundColor: '#000',
    webPreferences: { offscreen: true, contextIsolation: false, nodeIntegration: true, backgroundThrottling: false, webSecurity: false },
  });
  const wc = win.webContents;
  wc.setFrameRate(60);
  wc.on('console-message', (_e, level, message) => { if (level >= 2) console.log(`[film] ${message}`); });
  wc.debugger.attach('1.3');
  await wc.loadFile(path.join(VIDEO, 'film', 'index.html'), { query: { film: FILM } });
  const js = (code) => wc.executeJavaScript(code, true);
  await js('FILM.ready');
  const { duration, fps } = await js('({ duration: FILM.duration, fps: FILM.fps })');
  fs.mkdirSync(path.join(CACHE, 'stills'), { recursive: true });

  if (has('cues')) {
    fs.writeFileSync(path.join(VIDEO, 'audio', `cues${tag}.json`), JSON.stringify(await js('FILM.cues()'), null, 1));
    console.log(`wrote audio/cues${tag}.json`);
    app.exit(0);
    return;
  }
  const grab = async (t, format, quality) => {
    await js(`FILM.renderAt(${t})`);
    return Buffer.from((await wc.debugger.sendCommand('Page.captureScreenshot', { format, quality, fromSurface: true })).data, 'base64');
  };

  if (has('stills')) {
    for (const t of arg('stills').split(',').map(Number)) {
      fs.writeFileSync(path.join(CACHE, 'stills', `film_${t.toFixed(2)}.jpg`), await grab(t, 'jpeg', 88));
    }
    app.exit(0);
    return;
  }

  const from = Number(arg('from', 0)), to = Math.min(duration, Number(arg('to', duration)));
  const out = arg('out', path.join(CACHE, has('from') || has('to') ? 'part.mp4' : `film${tag}.mp4`));
  const ffmpeg = spawn(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
    '-vf', 'scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', arg('crf', '17'),
    '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-movflags', '+faststart', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const first = Math.round(from * fps), last = Math.round(to * fps);
  const began = Date.now();
  for (let f = first; f < last; f++) {
    const jpeg = await grab(f / fps, 'jpeg', 97);
    if (!ffmpeg.stdin.write(jpeg)) await new Promise((r) => ffmpeg.stdin.once('drain', r));
    if ((f - first) % 150 === 0) console.log(`frame ${f - first}/${last - first}  (${((Date.now() - began) / 1000).toFixed(0)} s)`);
  }
  ffmpeg.stdin.end();
  await new Promise((r) => ffmpeg.on('close', r));
  console.log(`rendered ${last - first} frames -> ${path.relative(path.join(VIDEO, '..'), out)}`);
  app.exit(0);
});
