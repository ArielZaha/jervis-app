// The trailer: 68 seconds in five acts — mystery, awakening, power, escalation, reveal. A narrator carries it; every
// picture of Jarvis is real footage (the same takes as the showcase, plus "asleep, then called by name").
// 120 beats a minute: a bar is 2 s. The acts are 5, 5, 12, 8 and 4 bars, so every act turns on the music.
//
// Narration lines live in audio/trailer_narration.json; their real lengths (audio/trailer_voice.json) are read here,
// so a line never runs into the next one.

const SPOT = { orb: [0.472, 0.322], stage: [0.472, 0.47], talk: [0.868, 0.4], sheet: [0.5, 0.49] };
const footage = (name) => require(`../assets/footage/${name}.json`);
const markOf = (name, label) => { const m = footage(name).marks; const k = Object.keys(m).find((key) => key.startsWith(label)); if (k === undefined) throw new Error(`${name}: no mark ${label}`); return m[k]; };
const SCRIPT = Object.fromEntries(require('../audio/trailer_narration.json').lines.map((l) => [l.id, l.say]));
const LENGTH = require('../audio/trailer_voice.json').lines;
let narratedUntil = 0;
// The narrator says line `id` at `at` (seconds into the scene). Returns the line's subtitle, already timed.
function narrate(s, root, id, at, { y = 900 } = {}) {
  const start = s.start + at;
  if (start < narratedUntil - 0.02) console.error(`narration ${id} starts ${(narratedUntil - start).toFixed(2)} s before the line before it ends`);
  narratedUntil = start + LENGTH[id];
  s.cue('narrate', at, { file: id + '.wav', len: LENGTH[id], text: SCRIPT[id] });
  const line = narration(root, SCRIPT[id], { y });
  return { draw: (t) => line.draw(t, at, at + LENGTH[id] + 0.35) };
}
// One of Jarvis's own spoken replies from a take.
function jarvis(s, root, take, n, at, most, text) {
  const line = footage(take).lines[n];
  s.cue('voice', at, { file: line.file, len: Math.min(most, line.seconds), text: line.text });
  const sub = subtitle(root, text || line.text, { y: 962 });
  return { draw: (t) => sub.draw(t, at + 0.05, at + Math.min(most, line.seconds) + 0.25) };
}
const asked = (s, text, at, len, how = 'said') => s.cue('ask', at, { text, len, how });
const hit = (el_, t, at, strength = 0.5) => { el_.style.opacity = (strength * pulse(t, at - 0.04, at + 0.3, 0.05, 0.3)).toFixed(4); };

// ============ ACT 1 — MYSTERY (0–10 s): something asleep in the dark ============
scene('mystery', 5, { over: 0, accent: 'cyan', mix: { pad: 0.6, bass: 0, arp: 0, kick: 0, hat: 0, clap: 0, bright: 2, pulse: 1 } }, (s, root) => {
  const hero = el('div', 'hero', root);
  const orb = s.clip('orbsleep', hero);
  // three glimpses of what is coming, a few frames each, under the word "act"
  const glimpses = [['mind', markOf('mind', 'reply:Solve') + 60, 0.47, 0.5, 1.3], ['world', markOf('world', 'fast') + 40, 0.5, 0.5, 1.45], ['world', markOf('world', 'reply:Tell') + 60, 0.5, 0.47, 1.2]]
    .map(([take, frame, cx, cy, z]) => ({ view: new Crop(s, take, root, 'full'), frame, cx, cy, z }));
  const lines = [narrate(s, root, 'n01', 1.0), narrate(s, root, 'n02a', 5.3), narrate(s, root, 'n02b', 7.25), narrate(s, root, 'n02c', 8.7)];
  const asleep = markOf('orbsleep', 'asleep'), wake = markOf('orbsleep', 'wake');
  s.cue('drone', 0.2); s.cue('heartbeat', 1.0); s.cue('heartbeat', 3.0); s.cue('heartbeat', 5.0); s.cue('heartbeat', 6.0); s.cue('heartbeat', 7.0); s.cue('heartbeat', 8.0);
  s.cue('tick', 9.0); s.cue('tick', 9.25); s.cue('tick', 9.5); s.cue('cutout', 9.72, { len: 0.28 });
  FILM.backgroundLevel = (T) => seg(T, 10, 13, E.sine) * (1 - seg(T, FILM.duration - 1.0, FILM.duration - 0.5));
  FILM.blackLevel = (T) => Math.max(1 - seg(T, 0.6, 2.2, E.sine), seg(T, FILM.duration - 0.95, FILM.duration - 0.6));
  return (t) => {
    // the sleeping orb, very close and very slow; each phrase of the narration moves the camera
    const shots = [
      { from: 0, to: 4.9, x: -420, y: 150, z: 2.7, drift: 0.05, light: 0.62 },
      { from: 5.2, to: 7.15, x: 520, y: -210, z: 2.0, drift: 0.07, light: 0.8 },
      { from: 7.15, to: 8.65, x: 0, y: 40, z: 1.25, drift: 0.1, light: 1 },
    ];
    const shot = shots.find((sh) => t >= sh.from && t < sh.to);
    hero.style.visibility = shot ? '' : 'hidden';
    if (shot) {
      const into = t - shot.from;
      orb.show((shot.from > 7 ? wake - 30 : asleep + 20) + t * FPS);
      css(hero, { transform: `translate(${px(shot.x * (1 - 0.03 * into))}, ${px(shot.y)}) scale(${(shot.z * (1 + shot.drift * into / 4)).toFixed(5)})`,
        opacity: (shot.light * Math.min(seg(into, 0, shot.from ? 0.12 : 2.6, E.sine), 1 - seg(t, shot.to - 0.1, shot.to))).toFixed(4) });
    }
    glimpses.forEach((g, i) => {
      const from = 9.0 + i * 0.25, on = t >= from && t < from + 0.22;
      if (on) g.view.clip.show(g.frame + (t - from) * FPS); else if (t > from + 1) g.view.clip.release();
      g.view.at({ x: 960, y: 540, w: 1920, h: 1080, cx: g.cx, cy: g.cy, z: g.z * (1 + 0.2 * (t - from)), radius: 0, o: on ? 1 : 0 });
    });
    lines.forEach((l) => l.draw(t));
  };
});

// ============ ACT 2 — AWAKENING (10–20 s): his name, and he wakes ============
scene('awakening', 5, { over: 0.3, accent: 'cyan', mix: { pad: 0.75, bass: 0.55, arp: 0.3, kick: 0, hat: 0, clap: 0, bright: 4, build: 1 } }, (s, root) => {
  const win = s.win('awaken');
  const c = win.clip;
  const call = spoken(root, 'Hey Jarvis', { y: 884 });
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  css(title, { top: '452px', fontSize: '176px' });
  const flash = el('div', 'flash', root);
  const T_WAKE = 1.7, T_NAME = 5.0, T_BACK = 6.75;
  const awake = markOf('awaken', 'awake');
  const hello = jarvis(s, root, 'awaken', 0, T_WAKE + 0.5, 9);
  const lines = [narrate(s, root, 'n03', T_NAME + 0.05, { y: 780 }), narrate(s, root, 'n04', T_BACK + 0.25)];
  asked(s, 'Hey Jarvis', 0.35, 1.0);
  s.cue('hit', 0); s.cue('listen', 0.4); s.cue('wake', T_WAKE); s.cue('cutout', T_NAME - 0.22, { len: 0.22 }); s.cue('hit', T_NAME); s.cue('swell', 8.4);
  return (t) => {
    c.show(awake + (t - T_WAKE) * FPS);
    const name = pulse(t, T_NAME, T_BACK, 0.001, 0.2);            // the wordmark alone, for a breath
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 0.78, ry: -3, rx: 1.5 }],
      [T_WAKE, { cx: 0.5, cy: 0.5, z: 0.82, ry: -2, rx: 1.2 }, E.lin],
      [T_WAKE + 1.5, { cx: SPOT.stage[0], cy: 0.42, z: 1.36, ry: -0.6, rx: 0.4 }, E.ioQ],
      [T_NAME, { cx: SPOT.stage[0], cy: 0.42, z: 1.5, ry: 0, rx: 0 }, E.lin],
      [T_BACK, { cx: 0.5, cy: 0.5, z: 0.9, ry: 3, rx: 1 }, E.lin],
      [s.dur + 0.3, { cx: 0.5, cy: 0.5, z: 1.02, ry: 1, rx: 0.4 }, E.out],
    ]);
    win.at({ ...k, ax: 960, ay: 540, o: (1 - name) * (1 - seg(t, s.dur - 0.05, s.dur + 0.2)), bright: t < T_WAKE ? 0.9 : 1 });
    call.draw(t, 0.35, 1.3, T_WAKE + 0.2);
    hello.draw(t);
    [...title.children].forEach((letter, i) => {
      const p = seg(t, T_NAME - 0.02 + i * 0.03, T_NAME + 0.3 + i * 0.03, E.outQ), out = seg(t, T_BACK - 0.25, T_BACK, E.in);
      css(letter, { opacity: (p * (1 - out)).toFixed(4), transform: `scale(${(lerp(1.4, 1, p) * (1 + 0.03 * clamp(t - T_NAME, 0, 2)) * lerp(1, 1.5, out)).toFixed(4)})`, filter: `blur(${px(16 * (1 - p) + 14 * out)})` });
    });
    hit(flash, t, T_WAKE, 0.42);
    lines.forEach((l) => l.draw(t));
  };
});

// ============ ACT 3 — POWER (20–44 s): speak, ask, watch ============
scene('power', 12, { over: 0.3, accent: 'blue', mix: { pad: 0.9, bass: 0.92, arp: 0.8, kick: 0.9, hat: 0.5, clap: 0.3, bright: 6 } }, (s, root) => {
  const a = s.win('wake'), b = s.win('mind'), c = s.win('world');
  const flash = el('div', 'flash', root);
  const mw = (l) => markOf('wake', l), mm = (l) => markOf('mind', l), mo = (l) => markOf('world', l);
  // one sentence, two things done
  const T_W = 2.9;                                    // the weather opens
  const wakeCut = [[0, mw('heard:Set') - 2.6 * FPS], [T_W, mw('result')]];
  // a spoken thread of mathematics
  const T_M = 5.6, T_G = 5.6, T_C = 8.8;              // cut straight to the graph drawing; then two functions
  const mindCut = [[T_M, mm('reply:Solve')], [T_C, mm('reply:Compare')]];
  // the Earth, a sunrise, a planet
  const T_E = 11.4, T_S = 18.0, T_P = 20.6;
  const worldCut = [[T_E - 0.5, mo('reply:What') + 4], [T_S, mo('reply:Show') + 6], [T_P, mo('reply:Tell') + 4]];
  const asks = [
    [spoken(root, 'Set a timer for twenty minutes and show me the weather in Paris', { y: 884 }), 0.2, 2.5, T_W + 0.7],
    [spoken(root, 'Solve x squared minus five x plus six equals zero, and draw the function', { y: 44 }), T_M - 0.1, T_M + 0.9, T_M + 2.2],
    [spoken(root, 'Compare x squared and x plus one', { y: 44 }), T_C - 0.5, T_C + 0.2, T_C + 1.5],
    [spoken(root, 'What is the distance between Tokyo and New York?', { y: 44 }), T_E - 0.3, T_E + 0.5, T_E + 1.8],
    [spoken(root, 'Show sunrise over Tokyo', { y: 44 }), T_S - 0.3, T_S + 0.3, T_S + 1.5],
    [spoken(root, 'Tell me about Saturn', { y: 44 }), T_P - 0.3, T_P + 0.3, T_P + 1.5],
  ];
  asks.forEach(([node, from, until]) => asked(s, node.textContent.trim(), from, until - from));
  const voices = [jarvis(s, root, 'wake', 1, T_W + 0.15, 2.1, 'Timer set for 20 minutes.'), jarvis(s, root, 'mind', 0, T_G + 1.6, 3.1, 'The solutions are x equals 2 and x equals 3.')];
  const lines = [narrate(s, root, 'n05', 0.3, { y: 760 }), narrate(s, root, 'n06', T_M - 0.2, { y: 880 }), narrate(s, root, 'n07', T_E + 1.5)];
  s.cue('hit', 0); s.cue('listen', 0.2); s.cue('open', T_W); s.cue('whoosh', T_M - 0.2); s.cue('draw', T_G); s.cue('slide', T_C); s.cue('draw', T_C + 0.1);
  s.cue('globe', T_E); s.cue('slide', T_S); s.cue('draw', T_S + 0.1); s.cue('globe', T_P); s.cue('swell', 22.4);
  return (t) => {
    // --- the command
    const onA = t < T_M + 0.2;
    if (onA) {
      a.clip.show(cut(wakeCut, t));
      const k = keys(t, [
        [0, { cx: SPOT.stage[0], cy: 0.45, z: 1.3 }], [T_W - 0.1, { cx: SPOT.stage[0], cy: 0.45, z: 1.42 }, E.lin],
        [T_W + 0.5, { cx: 0.5, cy: 0.5, z: 1.0 }, E.ioQ], [T_M + 0.2, { cx: 0.56, cy: 0.42, z: 1.14 }, E.lin],
      ]);
      const w = whip(t, T_M, 1, 0.3);
      css(a.cam, { transform: `translateX(${px(w.leave.x)})`, filter: w.leave.blur > 0.5 ? `blur(${px(w.leave.blur * 0.5)})` : 'none' });
      a.at({ ...k, radius: 0 });
    } else { a.at({ o: 0 }); a.clip.release(); }
    // --- the mathematics
    const onB = t > T_M - 0.2 && t < T_E + 0.4;
    if (onB) {
      b.clip.show(cut(mindCut, Math.max(t, T_M)));
      const k = keys(t, [
        [T_M, { cx: 0.5, cy: 0.5, z: 1.04 }], [T_G + 1.8, { cx: 0.47, cy: 0.52, z: 1.34 }, E.ioQ],
        [T_C - 0.05, { cx: 0.5, cy: 0.58, z: 1.46 }, E.lin], [T_C + 0.05, { cx: 0.5, cy: 0.5, z: 1.12 }, E.lin], [T_E + 0.4, { cx: 0.5, cy: 0.45, z: 1.42 }, E.io],
      ]);
      const w = whip(t, T_M, 1, 0.3);
      css(b.cam, { transform: `translateX(${px(t < T_M + 0.4 ? w.enter.x : 0)})`, filter: t < T_M + 0.4 && w.enter.blur > 0.5 ? `blur(${px(w.enter.blur * 0.5)})` : 'none' });
      b.at({ ...k, radius: 0 });
    } else { b.at({ o: 0 }); if (t > T_E + 1) b.clip.release(); }
    // --- the Earth: through a circle growing out of the curves' meeting point
    const onC = t > T_E - 0.45;
    if (onC) {
      c.clip.show(cut(worldCut, t));
      iris(c.cam, t, T_E - 0.4, T_E + 0.3, 960, 500);
      const k = keys(t, [
        [T_E - 0.5, { cx: 0.5, cy: 0.5, z: 1.18 }], [T_E + 0.6, { cx: 0.5, cy: 0.5, z: 1.22 }, E.lin], [T_E + 3.2, { cx: 0.5, cy: 0.5, z: 1.5 }, E.ioQ],
        [T_S - 0.05, { cx: 0.5, cy: 0.52, z: 1.6 }, E.lin], [T_S + 0.05, { cx: 0.5, cy: 0.5, z: 1.34 }, E.lin], [T_P - 0.05, { cx: 0.5, cy: 0.5, z: 1.52 }, E.lin],
        [T_P + 0.05, { cx: 0.5, cy: 0.47, z: 1.16 }, E.lin], [s.dur + 0.3, { cx: 0.5, cy: 0.46, z: 1.4 }, E.lin],
      ]);
      c.at({ ...k, radius: 0, o: 1 - seg(t, s.dur - 0.05, s.dur + 0.15) });
    } else c.at({ o: 0 });
    asks.forEach(([node, from, until, out]) => node.draw(t, from, until, out));
    voices.forEach((v) => v.draw(t));
    lines.forEach((l) => l.draw(t));
    flash.style.opacity = (0.35 * Math.max(pulse(t, T_C - 0.03, T_C + 0.2, 0.04, 0.2), pulse(t, T_S - 0.03, T_S + 0.2, 0.04, 0.2), pulse(t, T_P - 0.03, T_P + 0.2, 0.04, 0.2))).toFixed(4);
  };
});

// ============ ACT 4 — ESCALATION (44–60 s): control, the phone, everything ============
scene('escalation', 8, { over: 0, accent: 'warm', mix: { pad: 1.0, bass: 1.0, arp: 0.95, kick: 1.0, hat: 0.85, clap: 0.6, bright: 8, build: 1 } }, (s, root) => {
  // --- control
  const ctl = el('div', 'layer', root);
  const win = new Win('control', ctl); s.clips.push(win.clip);
  const screen = new Win('controlbar', ctl, { lights: false }); s.clips.push(screen.clip);
  const strip = new Crop(s, 'controlbar', ctl);
  const mc = (l) => markOf('control', l), mb = (l) => markOf('controlbar', l);
  const T_ALLOW = 3.2, T_BAR = 3.6, T_LINK = 6.2;
  const ctlCut = [[0, mc('asked') + 5], [T_ALLOW - 0.4, mc('allow') - 12]];
  const barCut = [[T_BAR, mb('observing') - 4], [T_BAR + 1.0, mb('thinking') + 8], [T_BAR + 1.8, mb('pause') - 6]];
  // --- the phone and the computer, one recording
  const lnk = el('div', 'layer', root);
  const desk = new Win('link.desk', lnk); s.clips.push(desk.clip);
  const phone = new Phone(s, 'link', lnk);
  const ml = (l) => markOf('link', l);
  const T_MARS = T_LINK + 1.3, T_TRIP = T_LINK + 3.5, T_ALL = 11.8;
  const linkCut = [[T_LINK - 0.3, ml('sent:Show') - 2 * 30], [T_LINK, ml('sent:Show') - 2 * 30, 2], [T_LINK + 1.0, ml('sent:Show')], [T_MARS - 0.2, ml('reply:Show') - 6], [T_TRIP, ml('reply:Distance') + 20]];
  // --- everything else: half a second each
  const shots = [
    { take: 'talk', at: markOf('talk', 'reply:Play') + 24, cx: 0.853, cy: 0.5, z: 1.7, word: 'Music.' },
    { take: 'talk', at: markOf('talk', 'reply:Show') + 24, cx: 0.853, cy: 0.66, z: 1.7, word: 'Trailers.' },
    { take: 'docs', at: markOf('docs', 'reply:Write') + 30, cx: 0.6, cy: 0.4, z: 1.7, word: 'Documents.', page: true },
    { take: 'picture', at: markOf('picture', 'picture') + 20, cx: 0.853, cy: 0.52, z: 1.86, word: 'Pictures.' },
    { take: 'plan', at: markOf('plan', 'reply:1 hour') + 24, cx: 0.853, cy: 0.72, z: 1.7, word: 'Calendar.' },
    { take: 'solve', at: markOf('solve', 'reply') + 40, cx: 0.853, cy: 0.55, z: 1.26, word: 'Answers.' },
    { take: 'android', at: markOf('android', 'globe') + 90, phone: true, word: 'Android.' },
    { take: 'pairing', at: markOf('pairing', 'code') + 30, cx: 0.5, cy: 0.42, z: 1.9, word: 'Your phone.' },
  ];
  const per = 0.5;
  const story = footage('docs').notes.first;
  const views = shots.map((shot, i) => {
    const layer = el('div', 'layer', root);
    const view = shot.phone ? new Phone(s, shot.take, layer, true) : new Crop(s, shot.take, layer, 'full');
    let page = null;
    if (shot.page) {
      page = el('div', 'page', layer, `<h3>${story.title}</h3>${(story.body || '').split(/\n\s*\n/).slice(0, 4).map((p) => `<p>${p.trim().replace(/\*([^*]+)\*/g, '<em>$1</em>')}</p>`).join('')}<div class="fade"></div>`);
      css(page, { left: '1170px', top: '110px', width: '600px', height: '860px' });
    }
    el('div', 'wordscrim', layer);
    const word = el('div', 'word', layer, shot.word);
    css(word, { left: '110px', top: '820px' });
    s.cue('slide', T_ALL + i * per - 0.02);
    return { shot, layer, view, page, word };
  });
  const flash = el('div', 'flash', root);
  const dark = scrim(ctl, 'right', 40, 7);
  const cap = new Caption(ctl, { kicker: 'With your permission', head: 'He takes\nthe mouse.', x: 1300, y: 360, width: 560, size: 84 });
  const lines = [narrate(s, root, 'n08', 0.5, { y: 40 }), narrate(s, root, 'n09', T_LINK + 0.35, { y: 40 }), narrate(s, root, 'n10', T_ALL + 0.15, { y: 40 })];
  asked(s, 'Use my computer to turn on dark mode in Chrome', 0, 0.4, 'typed'); asked(s, 'Show me Mars', T_LINK, 1.0, 'typed on the phone'); asked(s, 'Distance between Paris and Rome', T_TRIP - 0.4, 0.4, 'typed on the phone');
  s.cue('hit', 0); s.cue('sheet', 0.35); s.cue('click', T_ALLOW); s.cue('whoosh', T_BAR - 0.2); s.cue('tick', T_BAR + 1.0); s.cue('tick', T_BAR + 2.0);
  s.cue('whoosh', T_LINK - 0.2); s.cue('keys', T_LINK, { len: 1.0 }); s.cue('send', T_LINK + 1.02); s.cue('globe', T_MARS); s.cue('globe', T_TRIP); s.cue('hit', T_ALL);
  s.cue('cutout', s.dur - 0.3, { len: 0.3 });
  return (t) => {
    // control: the question, the click, the bar
    const onCtl = t < T_LINK + 0.25;
    ctl.style.visibility = onCtl ? '' : 'hidden';
    if (onCtl) {
      const out = whip(t, T_LINK, -1, 0.3);
      css(ctl, { transform: `translateX(${px(out.leave.x)})`, filter: out.leave.blur > 0.5 ? `blur(${px(out.leave.blur * 0.5)})` : 'none' });
      win.clip.show(cut(ctlCut, t));
      const k = keys(t, [[0, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.02 }], [0.9, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.2 }, E.outQ], [T_BAR + 0.2, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.3 }, E.lin]]);
      const gone = seg(t, T_BAR - 0.18, T_BAR + 0.2);
      win.at({ ...k, ax: 640, ay: 540, ry: 3, rx: 0.8, z: k.z * lerp(1, 1.3, gone), o: 1 - gone, blur: 22 * gone });
      screen.clip.show(cut(barCut, Math.max(t, T_BAR)));
      strip.clip.show(cut(barCut, Math.max(t, T_BAR)));
      const arrive = seg(t, T_BAR - 0.1, T_BAR + 0.4, E.outQ);
      screen.at({ cx: 0.5, cy: 0.5, z: lerp(0.5, 0.57, arrive) + 0.006 * t, ax: 640, ay: 430, ry: lerp(8, 4, arrive), rx: 1.2, o: arrive, blur: 14 * (1 - arrive), glare: 0.5 });
      strip.at({ x: 640, y: 878 + 20 * (1 - arrive), w: 1090, h: 132, cx: 0.5, cy: 0.942, z: 2.02, o: seg(t, T_BAR + 0.1, T_BAR + 0.5, E.outQ), radius: 14 });
      dark.draw(1);
      cap.draw(t, 0.4, T_LINK + 0.1, { each: 0.05 });
    } else { win.clip.release(); screen.clip.release(); strip.clip.release(); }
    // the phone and the computer
    const onLink = t > T_LINK - 0.2 && t < T_ALL + 0.05;
    lnk.style.visibility = onLink ? '' : 'hidden';
    if (onLink) {
      const inn = whip(t, T_LINK, -1, 0.3);
      css(lnk, { transform: `translateX(${px(t < T_LINK + 0.4 ? inn.enter.x : 0)})`, filter: t < T_LINK + 0.4 && inn.enter.blur > 0.5 ? `blur(${px(inn.enter.blur * 0.5)})` : 'none' });
      const f = cut(linkCut, t);
      phone.clip.show(f); desk.clip.show(f);
      phone.at({ x: 330, y: 560 + 6 * Math.sin(t), scale: 0.92 + 0.004 * (t - T_LINK), ry: 10, rz: -0.8 });
      const k = keys(t, [[T_LINK, { z: 0.62, ry: -7 }], [T_MARS, { z: 0.63, ry: -6.5 }, E.lin], [T_MARS + 0.9, { z: 0.72, ry: -4.5 }, E.ioQ], [T_ALL, { z: 0.76, ry: -3.5 }, E.lin]]);
      desk.at({ cx: 0.5, cy: 0.5, ax: 1262, ay: 600, rx: 1.4, ...k });
    } else if (t > T_ALL + 0.5) { phone.clip.release(); desk.clip.release(); }
    // everything else
    const i = Math.floor((t - T_ALL) / per), into = t - T_ALL - i * per;
    views.forEach((v, n) => {
      const on = n === i && t >= T_ALL && t < s.dur - 0.28;
      v.layer.style.visibility = on ? '' : 'hidden';
      if (!on) { if (Math.abs(n - i) > 1) v.view.clip.release(); return; }
      v.view.clip.show(v.shot.at + into * FPS);
      const push = 1 + 0.08 * (into / per);
      if (v.shot.phone) v.view.at({ x: 1380, y: 548, scale: 0.96 * push, ry: -8, rz: 0.8 });
      else v.view.at({ x: 960, y: 540, w: 1920, h: 1080, cx: v.shot.cx, cy: v.shot.cy, z: v.shot.z * push, radius: 0, bright: 0.92 });
      css(v.word, { opacity: seg(into, 0, 0.1).toFixed(3), transform: `translateX(${px(-30 * (1 - seg(into, 0, 0.18, E.outQ)))})` });
    });
    flash.style.opacity = (t >= T_ALL && t < s.dur - 0.28 ? 0.3 * pulse(into, -0.02, 0.14, 0.03, 0.12) : 0).toFixed(4);
    lines.forEach((l) => l.draw(t));
  };
});

// ============ ACT 5 — THE REVEAL (60–70 s) ============
scene('reveal', 4, { over: FILM.tail, accent: 'cyan', mix: { pad: 1.0, bass: 0.8, arp: 0.4, kick: 0, hat: 0, clap: 0, bright: 8 } }, (s, root) => {
  const computer = s.win('awaken');
  const voiceShot = s.win('wake');
  const hero = el('div', 'hero', root);
  const orb = s.clip('orb', hero);
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  css(title, { top: '470px', fontSize: '186px' });
  const tag = el('div', 'tagword', root, 'Your computer. Your command.');
  tag.style.top = '716px';
  const credit = el('div', 'credit', root, 'Created by <b>Ariel</b> and <b>Shalev</b>');
  credit.style.top = '812px';
  const flash = el('div', 'flash', root);
  const T2 = 1.9, T3 = 4.0, T_END = 7.6;
  const lines = [narrate(s, root, 'n11', 0.35), narrate(s, root, 'n12', T2 + 0.2), narrate(s, root, 'n13', T3 + 0.6, { y: 884 })];
  const o0 = markOf('orb', 'speaking') - 10;
  s.cue('hit', 0); s.cue('hit', T2); s.cue('cutout', T3 - 0.22, { len: 0.22 }); s.cue('final', T3); s.cue('end', T_END);
  const before = FILM.blackLevel;
  FILM.blackLevel = (T) => Math.max(before(T), T >= s.start + T_END ? 1 : 0);
  return (t) => {
    // "Your computer." — the whole window, awake
    computer.clip.show(markOf('awaken', 'awake') + 150 + t * FPS);
    computer.at({ cx: 0.5, cy: 0.5, z: 0.9 + 0.035 * t, ax: 960, ay: 520, ry: -2 + 0.6 * t, rx: 1, o: t < T2 ? 1 : 0 });
    // "Your commands." — close on him listening
    voiceShot.clip.show(markOf('wake', 'listening:Set') + 14 + (t - T2) * FPS);
    voiceShot.at({ cx: SPOT.stage[0], cy: 0.42, z: 1.5 + 0.05 * (t - T2), ax: 960, ay: 500, o: t >= T2 && t < T3 ? 1 : 0, radius: 0 });
    // "Your Jarvis." — the name
    const on = t >= T3;
    orb.show(o0 + (t - T3) * FPS);
    css(hero, { transform: `translate(0, ${px(-232)}) scale(${(0.5 + 0.004 * (t - T3)).toFixed(5)})`, opacity: on ? seg(t, T3, T3 + 0.25, E.out).toFixed(4) : 0 });
    [...title.children].forEach((letter, i) => {
      const p = seg(t, T3 - 0.02 + i * 0.03, T3 + 0.34 + i * 0.03, E.outQ);
      css(letter, { opacity: p.toFixed(4), transform: `scale(${(lerp(1.5, 1, p) * (1 + 0.012 * clamp(t - T3, 0, 6))).toFixed(4)})`, filter: `blur(${px(18 * (1 - p))})` });
    });
    const tg = seg(t, T3 + 2.0, T3 + 2.6, E.outQ), cr = seg(t, T3 + 2.5, T3 + 3.0, E.outQ);
    css(tag, { opacity: tg.toFixed(4), letterSpacing: `${lerp(0.9, 0.5, tg).toFixed(3)}em`, textIndent: `${lerp(0.9, 0.5, tg).toFixed(3)}em` });
    css(credit, { opacity: (cr * 0.92).toFixed(4), transform: `translateY(${px(10 * (1 - cr))})` });
    flash.style.opacity = (0.5 * Math.max(pulse(t, -0.03, 0.25, 0.04, 0.25), pulse(t, T2 - 0.03, T2 + 0.25, 0.04, 0.25), pulse(t, T3 - 0.03, T3 + 0.4, 0.04, 0.4))).toFixed(4);
    lines.forEach((l) => l.draw(t));
  };
});
