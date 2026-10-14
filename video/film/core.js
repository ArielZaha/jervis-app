// The film's engine. Everything on screen is a pure function of time: FILM.renderAt(seconds) places every element,
// seeks every piece of footage to its exact frame, and resolves when the picture is ready to photograph.
// Scenes are added in scenes.js; lengths are counted in bars of the soundtrack (100 beats a minute: a bar is 2.4 s,
// exactly 72 frames), so every cut can land on the music.
const FPS = 30, BPM = window.FILM_BPM || 100, BAR = 240 / BPM;
const stage = document.getElementById('stage');

// ---------- small maths ----------
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  lin: (p) => p,
  in: (p) => p * p * p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  io: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  outQ: (p) => 1 - Math.pow(1 - p, 5),
  ioQ: (p) => (p < 0.5 ? 16 * p * p * p * p * p : 1 - Math.pow(-2 * p + 2, 5) / 2),
  outExpo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  inExpo: (p) => (p <= 0 ? 0 : Math.pow(2, 10 * p - 10)),
  sine: (p) => 0.5 - 0.5 * Math.cos(Math.PI * p),
};
// 0 before a, 1 after b, eased in between
const seg = (t, a, b, e = E.io) => e(clamp((t - a) / (b - a)));
// up over [a, a+d1], down over [b-d2, b]
const pulse = (t, a, b, d1 = 0.5, d2 = 0.5, e = E.io) => Math.min(seg(t, a, a + d1, e), 1 - seg(t, b - d2, b, e));
// keyframes: [[time, {x: .., y: ..}], ...]; eases between neighbours (per-key easing as a third item, for the leg ending there)
function keys(t, frames) {
  if (t <= frames[0][0]) return frames[0][1];
  for (let i = 1; i < frames.length; i++) {
    const [t1, b, e] = frames[i];
    if (t <= t1) {
      const [t0, a] = frames[i - 1];
      const p = (e || E.io)(clamp((t - t0) / (t1 - t0)));
      const out = {};
      for (const k in b) out[k] = lerp(a[k] ?? b[k], b[k], p);
      return out;
    }
  }
  return frames[frames.length - 1][1];
}
// a deterministic random number from an integer
const rnd = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

function el(tag, cls, parent, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html != null) node.innerHTML = html;
  if (parent) parent.appendChild(node);
  return node;
}
const css = (node, styles) => Object.assign(node.style, styles);
const px = (n) => `${n.toFixed(2)}px`;

// ---------- footage ----------
let pending = [];
class Clip {
  constructor(name, parent, cls = '') {
    this.name = name;
    this.meta = require(`../assets/footage/${name.replace(/\.desk$/, '')}.json`);   // x.desk.mp4 shares x.json (one recording, two windows)
    this.v = el('video', cls, parent);
    this.v.muted = true;
    this.v.playsInline = true;
    this.v.preload = 'auto';
    this.loaded = null;
    this.frame = -1;
  }
  mark(label) {
    const hit = Object.keys(this.meta.marks).find((k) => k === label || k.startsWith(label));
    if (hit === undefined) throw new Error(`${this.name}: no mark "${label}"`);
    return this.meta.marks[hit];
  }
  // Show one exact frame of the clip. Loading happens the first time a scene needs it.
  show(frame) {
    frame = Math.round(clamp(frame, 0, this.meta.frames - 1));
    if (!this.loaded) {
      this.loaded = new Promise((done, fail) => {
        this.v.addEventListener('loadeddata', done, { once: true });
        this.v.addEventListener('error', () => fail(new Error(`cannot load ${this.name}.mp4`)), { once: true });
        this.v.src = `../assets/footage/${this.name}.mp4`;
      });
    }
    if (frame === this.frame) return;
    this.frame = frame;
    pending.push(this.loaded.then(() => new Promise((done) => {
      const v = this.v, target = (frame + 0.5) / FPS;
      if (Math.abs(v.currentTime - target) < 0.001) { done(); return; }
      v.addEventListener('seeked', done, { once: true });
      v.currentTime = target;
    })));
  }
  // Free the decoder while the clip is off screen (a dozen 2880-pixel videos held open at once is a lot of memory).
  release() {
    if (!this.loaded) return;
    this.v.removeAttribute('src');
    this.v.load();
    this.loaded = null;
    this.frame = -1;
  }
}

// The real Jarvis window, as footage, with a camera: `at({cx, cy, z, ...})` puts the point (cx, cy) of the window
// (0..1 across and down) at the stage point (ax, ay), z times the size at which the window exactly fills the frame.
class Win {
  constructor(name, parent, { lights = true } = {}) {
    this.cam = el('div', 'cam', parent);
    this.tilt = el('div', 'tilt', this.cam);
    this.win = el('div', 'win', this.tilt);
    this.clip = new Clip(name, this.win);
    if (lights) el('div', 'lights', this.win, '<i></i><i></i><i></i>');
    this.glare = el('div', 'glare', this.win);
  }
  at({ cx = 0.5, cy = 0.5, z = 1, ax = 960, ay = 540, ry = 0, rx = 0, rz = 0, o = 1, blur = 0, radius = 18, glare = 1, bright = 1 }) {
    css(this.tilt, { transformOrigin: `${px(ax)} ${px(ay)}`, transform: `rotateY(${ry.toFixed(3)}deg) rotateX(${rx.toFixed(3)}deg) rotateZ(${rz.toFixed(3)}deg)` });
    css(this.win, {
      transform: `translate(${px(ax - cx * 1920 * z)}, ${px(ay - cy * 1080 * z)}) scale(${z.toFixed(5)})`,
      opacity: o.toFixed(4), borderRadius: px(radius / z),
      filter: (blur > 0.05 || Math.abs(bright - 1) > 0.005) ? `blur(${px(blur / z)}) brightness(${bright.toFixed(3)})` : 'none',
    });
    this.glare.style.opacity = glare.toFixed(3);
    this.cam.style.visibility = o < 0.002 ? 'hidden' : '';
  }
}

// ---------- words ----------
// A kicker, a headline revealed word by word, and an optional line under it.
class Caption {
  constructor(parent, { kicker = '', head = '', sub = '', x = 120, y = 400, width = 760, size = 78, align = 'left' }) {
    this.root = el('div', 'cap', parent);
    css(this.root, { left: px(x), top: px(y), width: px(width), textAlign: align });
    this.kicker = kicker ? el('div', 'kicker', this.root, `<i></i><span>${kicker}</span>`) : null;
    if (this.kicker && align === 'center') this.kicker.style.justifyContent = 'center';
    this.head = el('h2', 'head', this.root);
    this.head.style.fontSize = px(size);
    this.words = [];
    for (const line of head.split('\n')) {
      for (const word of line.split(' ')) {
        const dim = word.startsWith('~');
        const w = el('span', 'w', this.head, `<span${dim ? ' class="dim"' : ''}>${dim ? word.slice(1) : word}</span>`);
        this.words.push(w.firstChild);
        this.head.appendChild(document.createTextNode(' '));
      }
      el('br', '', this.head);
    }
    this.sub = sub ? el('p', 'sub', this.root, sub) : null;
    if (this.sub && align === 'center') css(this.sub, { marginLeft: 'auto', marginRight: 'auto' });
  }
  // t: seconds; appears from `a`, leaves by `b`. `each` = delay between words.
  draw(t, a, b, { each = 0.085, out = 0.45 } = {}) {
    const leave = seg(t, b - out, b, E.in);
    const visible = t > a - 0.05 && t < b;
    this.root.style.visibility = visible ? '' : 'hidden';
    if (!visible) return;
    css(this.root, { opacity: (1 - leave).toFixed(4), transform: `translateY(${px(-18 * leave)})`, filter: leave > 0.01 ? `blur(${px(7 * leave)})` : 'none' });
    if (this.kicker) {
      const p = seg(t, a, a + 0.6, E.outQ);
      this.kicker.firstChild.style.transform = `scaleX(${p.toFixed(4)})`;
      this.kicker.lastChild.style.opacity = seg(t, a + 0.1, a + 0.7).toFixed(4);
      this.kicker.lastChild.style.transform = `translateX(${px(-14 * (1 - seg(t, a + 0.1, a + 0.8, E.outQ)))})`;
    }
    this.words.forEach((w, i) => {
      const p = seg(t, a + 0.18 + i * each, a + 0.18 + i * each + 0.7, E.outQ);
      css(w, { transform: `translateY(${(104 * (1 - p)).toFixed(2)}%)`, opacity: clamp(p * 1.6).toFixed(4) });
    });
    if (this.sub) {
      const p = seg(t, a + 0.5 + this.words.length * each, a + 1.3 + this.words.length * each, E.outQ);
      css(this.sub, { opacity: p.toFixed(4), transform: `translateY(${px(16 * (1 - p))})` });
    }
  }
}

// A soft darkness along one side of the frame, so words can sit over footage and stay clean.
function scrim(parent, side = 'left', reach = 50, soft = 9) {
  const node = el('div', 'scrim', parent);
  // fully dark from the edge to (reach - soft)% of the width, clear at reach%: nothing shows through behind the words
  node.style.background = `linear-gradient(${side === 'left' ? 90 : 270}deg, rgb(2 3 8 / .98) 0%, rgb(2 3 8 / .97) ${reach - soft}%, rgb(2 3 8 / 0) ${reach}%)`;
  node.draw = (level) => { node.style.opacity = level.toFixed(4); };
  return node;
}

// A small chip quoting what was said or typed to Jarvis.
function said(parent, text, { x, y, typed = false }) {
  const node = el('div', 'said' + (typed ? ' typed' : ''), parent, `<span>${text}</span>`);
  css(node, { left: px(x), top: px(y) });
  node.draw = (t, a, b) => {
    const p = pulse(t, a, b, 0.5, 0.35, E.outQ);
    css(node, { opacity: p.toFixed(4), transform: `translateY(${px(14 * (1 - p))})`, visibility: p > 0.002 ? '' : 'hidden' });
  };
  return node;
}

// A row of small labels (names of services, apps...), arriving one after another.
function tags(parent, names, { x, y, width = 900 }) {
  const row = el('div', 'row', parent);
  css(row, { left: px(x), top: px(y), width: px(width) });
  const items = names.map((name) => el('span', 'tag', row, name));
  row.draw = (t, a, b, each = 0.09) => {
    const leave = seg(t, b - 0.4, b, E.in);
    row.style.visibility = t > a - 0.05 && t < b ? '' : 'hidden';
    items.forEach((item, i) => {
      const p = seg(t, a + i * each, a + i * each + 0.55, E.outQ) * (1 - leave);
      css(item, { opacity: p.toFixed(4), transform: `translateY(${px(12 * (1 - p))})` });
    });
  };
  return row;
}

// ---------- the timeline ----------
const scenes = [];
const cueList = [];
let cursor = 0;
// `over`: seconds this scene keeps drawing past its end, under the next one, for the transition between them.
function scene(id, bars, { over = 0.7, accent = 'cyan', mix = null, lead = 0 } = {}, build) {
  const root = el('div', 'scene', stage);
  root.dataset.scene = id;
  root.style.display = 'none';
  const s = { id, start: cursor, dur: bars * BAR, over, accent, mix, lead, root, clips: [], live: false };   // lead: seconds it starts drawing before its start
  cursor += s.dur;
  s.end = s.start + s.dur;
  s.win = (name, opts) => { const w = new Win(name, root, opts); s.clips.push(w.clip); return w; };
  s.clip = (name, parent, cls) => { const c = new Clip(name, parent || root, cls); s.clips.push(c); return c; };
  s.cue = (kind, t, extra = {}) => cueList.push({ kind, t: +(s.start + t).toFixed(3), scene: id, ...extra });
  s.draw = build(s, root) || (() => {});
  scenes.push(s);
  return s;
}

// The standard way one scene hands over to the next: the old one drifts toward the camera and dissolves while the
// new one settles in from slightly behind. Returns {o, z, blur} for a scene's contents at local time t.
function handover(s, t, { tin = 0.7, tout = s.over } = {}) {
  const a = seg(t, 0, tin, E.outQ), b = seg(t, s.dur, s.dur + tout, E.io);
  return { o: a * (1 - b), z: lerp(0.955, 1, a) * lerp(1, 1.07, b), blur: 10 * (1 - a) + 14 * b, a, b };
}

// ---------- the space behind everything ----------
const bg = el('div', 'bg', null);
stage.prepend(bg);
const wash1 = el('div', 'wash', bg), wash2 = el('div', 'wash', bg);
const sky = el('canvas', '', bg);
sky.width = 1920; sky.height = 1080;
const skyCtx = sky.getContext('2d');
const STARS = Array.from({ length: 300 }, (_, i) => ({
  x: rnd(i * 3 + 1) * 2100, y: rnd(i * 3 + 2) * 1080, r: 0.5 + rnd(i * 3 + 3) ** 3 * 1.7, depth: 0.25 + rnd(i * 7 + 5) * 0.9,
  pace: 0.4 + rnd(i * 11) * 1.5, phase: rnd(i * 13) * 6.283, tint: rnd(i * 17) < 0.2,
}));
const ACCENTS = { cyan: [79, 216, 255], violet: [165, 139, 255], teal: [61, 242, 192], blue: [90, 169, 255], warm: [255, 190, 120] };
function drawBackground(T, accent, level) {
  const [r, g, b] = accent;
  wash1.style.background = `radial-gradient(ellipse 46% 44% at ${(34 + 5 * Math.sin(T * 0.11)).toFixed(2)}% ${(30 + 4 * Math.cos(T * 0.09)).toFixed(2)}%, rgb(${r | 0} ${g | 0} ${b | 0} / ${(0.13 * level).toFixed(3)}), transparent 70%)`;
  wash2.style.background = `radial-gradient(ellipse 50% 48% at ${(70 + 5 * Math.cos(T * 0.08)).toFixed(2)}% ${(74 + 4 * Math.sin(T * 0.1)).toFixed(2)}%, rgb(88 70 190 / ${(0.11 * level).toFixed(3)}), transparent 72%)`;
  skyCtx.clearRect(0, 0, 1920, 1080);
  for (const s of STARS) {
    const x = ((s.x - T * 5.5 * s.depth) % 2100 + 2100) % 2100 - 90, y = (s.y + T * 2.2 * s.depth) % 1080;
    skyCtx.globalAlpha = level * (0.3 + 0.55 * s.depth) * (0.62 + 0.38 * Math.sin(T * s.pace + s.phase));
    skyCtx.fillStyle = s.tint ? `rgb(${r | 0},${g | 0},${b | 0})` : '#e6efff';
    skyCtx.beginPath();
    skyCtx.arc(x, y, s.r, 0, 6.283);
    skyCtx.fill();
  }
}

let vignette, black;
window.FILM = {
  fps: FPS,
  get duration() { return cursor + FILM.tail; },
  tail: ({ showcase: 1.6, trailer: 0.6 })[window.FILM_NAME] || 2.6,
  cues: () => ({ fps: FPS, bpm: BPM, bar: BAR, duration: cursor + FILM.tail,
    scenes: scenes.map((s) => ({ id: s.id, start: +s.start.toFixed(3), end: +s.end.toFixed(3), mix: s.mix })), cues: cueList.slice().sort((a, b) => a.t - b.t) }),
  ready: null,
  backgroundLevel: (T) => 1,   // scenes.js may replace this (the film opens and closes on black)
  blackLevel: (T) => 0,
  async renderAt(T) {
    pending = [];
    // the accent of whichever scene is on, blended across the handover
    let accent = [0, 0, 0], weight = 0;
    for (const s of scenes) {
      const t = T - s.start;
      const live = t >= -s.lead - 0.001 && t < s.dur + s.over;
      if (live !== s.live) {
        s.live = live;
        s.root.style.display = live ? '' : 'none';
        if (!live) s.clips.forEach((c) => c.release());
      }
      if (!live) continue;
      const w = t > s.dur ? 1 - seg(t, s.dur, s.dur + s.over) : 1;
      const c = ACCENTS[s.accent];
      accent = accent.map((v, i) => v + c[i] * w);
      weight += w;
      s.draw(t, T);
    }
    drawBackground(T, weight ? accent.map((v) => v / weight) : ACCENTS.cyan, FILM.backgroundLevel(T));
    black.style.opacity = FILM.blackLevel(T).toFixed(4);
    await Promise.all(pending);
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(done))));
  },
};
window.addEventListener('DOMContentLoaded', () => {});
FILM.ready = (async () => {
  await new Promise((done) => (document.readyState === 'complete' ? done() : window.addEventListener('load', done)));
  vignette = el('div', 'vignette', stage);
  black = el('div', 'black', stage);
  black.style.opacity = 0;
  await document.fonts.load('700 100px Orbitron');
  await document.fonts.ready;
})();

// ---------- more building blocks ----------
// A framed crop of footage anywhere on the stage: the point (cx, cy) of the clip sits at the middle of the box.
class Crop {
  constructor(s, name, parent, cls = '') {
    this.box = el('div', 'plain crop ' + cls, parent);
    this.clip = s.clip(name, this.box);
  }
  at({ x, y, w, h, cx = 0.5, cy = 0.5, z = 1, o = 1, radius = 16, ry = 0, scale = 1, blur = 0, bright = 1 }) {
    const fit = w / 1920;   // z = 1: the whole clip is exactly as wide as the box
    css(this.box, { left: px(x - w / 2), top: px(y - h / 2), width: px(w), height: px(h), opacity: o.toFixed(4), borderRadius: px(radius),
      transform: `perspective(2400px) rotateY(${ry.toFixed(3)}deg) scale(${scale.toFixed(5)})`, visibility: o < 0.002 ? 'hidden' : '',
      filter: (blur > 0.05 || Math.abs(bright - 1) > 0.005) ? `blur(${px(blur)}) brightness(${bright.toFixed(3)})` : 'none' });
    const vw = 1920 * fit * z, vh = 1080 * fit * z;
    css(this.clip.v, { width: px(vw), height: px(vh), left: px(clamp(w / 2 - cx * vw, w - vw, 0)), top: px(clamp(h / 2 - cy * vh, h - vh, 0)) });
  }
}

// A row of framed crops that steps along one place at a time; the one in the middle is lit, its neighbours wait dimmed.
// items: [{ clip, from (frame shown when its turn starts), cx, cy, z, label }]
function carousel(s, root, items, { y = 486, w = 1240, h = 698, per = BAR, gap = 70, lead = 0.8 }) {
  const cards = items.map((item) => {
    const crop = new Crop(s, item.clip, root, 'card');
    const label = el('div', 'card-label', root, `<b>${item.label}</b>`);
    return { item, crop, label };
  });
  return (t) => {
    const k = Math.max(0, Math.floor(t / per)), into = t - k * per;
    const at = clamp(k === 0 ? 0 : k - 1 + seg(into, 0, 0.6, E.outQ), 0, items.length - 1);   // steps on the bar line
    cards.forEach(({ item, crop, label }, i) => {
      const d = i - at, far = Math.min(1, Math.abs(d));
      const near = Math.abs(d) < 1.6;
      if (near) crop.clip.show(Math.min(item.until || 1e9, item.from + (t - i * per + lead) * FPS));
      else crop.clip.release();
      const drift = 1 + 0.035 * clamp((t - i * per) / per, -0.2, 1.2) * (1 - far);   // a slow push while it is the one on show
      crop.at({ x: 960 + d * (w + gap), y, w, h, cx: item.cx, cy: item.cy, z: (item.z || 1) * drift, o: near ? lerp(1, 0.34, far) : 0,
        ry: -7 * clamp(d, -1, 1), scale: lerp(1, 0.9, far), bright: lerp(1, 0.7, far) });
      const on = (1 - far) ** 3;
      css(label, { left: px(960 + d * (w + gap) - 500), top: px(y - h / 2 - 62), opacity: on.toFixed(4), visibility: on > 0.002 ? '' : 'hidden' });
    });
  };
}

// A phone with the real phone app's footage as its screen. The app starts below the status bar, as it does on a
// phone (the strip above it is left empty: no made-up clock or battery).
class Phone {
  constructor(s, name, parent, android = false) {
    this.root = el('div', 'phone' + (android ? ' android' : ''), parent);
    this.screen = el('div', 'screen', this.root);
    this.clip = s.clip(name, this.screen);
    el('div', 'island', this.root);
    const bar = android ? 40 : 56;
    this.w = (android ? 412 : 394) + 30;
    this.h = (android ? 916 : 852) + 30 + bar;
    css(this.clip.v, { top: px(bar), height: `calc(100% - ${bar}px)` });
    css(this.root, { width: px(this.w), height: px(this.h), left: 0, top: 0, transformOrigin: '50% 50%' });
  }
  at({ x, y, scale = 1, o = 1, ry = 0, rz = 0, blur = 0 }) {
    css(this.root, { transform: `translate(${px(x - this.w / 2)}, ${px(y - this.h / 2)}) perspective(2600px) rotateY(${ry.toFixed(3)}deg) rotateZ(${rz.toFixed(3)}deg) scale(${scale.toFixed(5)})`,
      opacity: o.toFixed(4), visibility: o < 0.002 ? 'hidden' : '', filter: blur > 0.05 ? `blur(${px(blur)})` : 'none' });
  }
}

// A small label in a corner, in the window's own lettering.
function corner(parent, text, { x = 96, y = 986 } = {}) {
  const node = el('div', 'corner', parent, `<i></i>${text}`);
  css(node, { left: px(x), top: px(y) });
  node.draw = (t, a, b) => {
    const p = pulse(t, a, b, 0.6, 0.4, E.outQ);
    css(node, { opacity: p.toFixed(4), transform: `translateX(${px(-16 * (1 - p))})`, visibility: p > 0.002 ? '' : 'hidden' });
  };
  return node;
}


// ---------- for the showcase: cutting inside one take, spoken words, subtitles, harder transitions ----------
// A take, cut into pieces: [[filmTime, clipFrame, rate?], ...]. From each filmTime the clip plays on from clipFrame
// (rate 2 = every second frame: twice as fast, still even). Returns the clip frame to show at time t.
function cut(pieces, t) {
  let piece = pieces[0];
  for (const p of pieces) if (t >= p[0]) piece = p;
  return piece[1] + (t - piece[0]) * FPS * (piece[2] || 1);
}

// What was said to Jarvis, appearing word by word as it is spoken. A small moving level beside it stands for the voice.
function spoken(parent, text, { x = 960, y = 920, center = true } = {}) {
  const node = el('div', 'spoken', parent, `<div><i></i><i></i><i></i><i></i><span>${text.split(' ').map((w) => `<b>${w}</b>`).join(' ')}</span></div>`);
  css(node, center ? { left: '0', right: '0', top: px(y) } : { left: px(x), top: px(y) });
  if (center) node.classList.add('center');
  const words = [...node.querySelectorAll('b')], bars = [...node.querySelectorAll('i')];
  // from..until: while it is being said; gone by `out`
  node.draw = (t, from, until, out) => {
    const p = pulse(t, from - 0.15, out, 0.3, 0.3, E.outQ);
    css(node, { opacity: p.toFixed(4), visibility: p > 0.002 ? '' : 'hidden', transform: `translateY(${px(10 * (1 - seg(t, from - 0.15, from + 0.25, E.outQ)))})` });
    if (p <= 0.002) return;
    words.forEach((w, i) => { w.style.opacity = lerp(0.16, 1, seg(t, from + (until - from) * (i / words.length) - 0.05, from + (until - from) * (i / words.length) + 0.14)).toFixed(3); });
    const talking = t > from && t < until + 0.1 ? 1 : 0.12;
    bars.forEach((bar, i) => { bar.style.transform = `scaleY(${(0.25 + 0.75 * talking * Math.abs(Math.sin(t * (9 + i * 2.3) + i * 1.7))).toFixed(3)})`; });
  };
  return node;
}

// What Jarvis says, as a line of subtitle (his own words, from the take).
function subtitle(parent, text, { y = 968 } = {}) {
  const node = el('div', 'subtitle', parent, `<div><em>Jarvis</em><span>${text}</span></div>`);
  node.style.top = px(y);
  node.draw = (t, from, out) => {
    const p = pulse(t, from, out, 0.25, 0.25, E.outQ);
    css(node, { opacity: p.toFixed(4), visibility: p > 0.002 ? '' : 'hidden' });
  };
  return node;
}

// A scene arriving through a growing circle (the orb's shape), from the point (x, y).
function iris(root, t, from, to, x = 960, y = 540) {
  const p = seg(t, from, to, E.io);
  root.style.clipPath = p >= 1 ? 'none' : `circle(${px(p * 2300)} at ${px(x)} ${px(y)})`;
}
// A scene arriving sideways, fast: where it is and how smeared, for time t.
function whip(t, at, dir = 1, len = 0.34) {
  const p = seg(t, at - len / 2, at + len / 2, E.ioQ);
  return { enter: { x: dir * 1920 * (1 - p), blur: 60 * Math.sin(Math.PI * p) }, leave: { x: -dir * 1920 * p, blur: 60 * Math.sin(Math.PI * p) }, p };
}


// ---------- for the trailer: the narrator's words ----------
// A line of narration as it is spoken: large, centred, low in the frame, over a soft shadow so it reads on anything.
function narration(parent, text, { y = 900 } = {}) {
  const node = el('div', 'narration', parent, `<span>${text}</span>`);
  node.style.top = px(y);
  node.draw = (t, from, out) => {
    const p = pulse(t, from - 0.05, out, 0.3, 0.3, E.outQ);
    css(node, { opacity: p.toFixed(4), visibility: p > 0.002 ? '' : 'hidden', letterSpacing: `${lerp(0.09, 0.05, seg(t, from, out)).toFixed(4)}em` });
  };
  return node;
}
