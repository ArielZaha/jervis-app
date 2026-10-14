// The showcase: about 90 seconds, six sequences. Each sequence is one real take in which Jarvis is asked something
// out loud (or from the phone) and does several things. The edit cuts the waiting out and lets his own voice carry on
// over the pictures. 120 beats a minute: a bar is 2 s, and every sequence is a whole number of bars.
//
// Footage frame numbers come from the marks saved with each clip, so a re-recorded take stays in step.

const SPOT = { orb: [0.472, 0.322], stage: [0.472, 0.47], talk: [0.868, 0.4], sheet: [0.5, 0.49], timers: [0.118, 0.6] };
const ORB_IN_WINDOW = 0.588;
const footage = (name) => require(`../assets/footage/${name}.json`);
const markOf = (name, label) => { const m = footage(name).marks; const k = Object.keys(m).find((key) => key.startsWith(label)); if (k === undefined) throw new Error(`${name}: no mark ${label}`); return m[k]; };
// Jarvis's spoken line number n of a take: placed on the soundtrack, and returned for the subtitle.
function voice(s, take, n, at, { most = 99, gain = 1 } = {}) {
  const line = footage(take).lines[n];
  s.cue('voice', at, { file: line.file, len: Math.min(most, line.seconds), gain, text: line.text });
  return { text: line.text, at, until: at + Math.min(most, line.seconds) };
}
// What was asked, for the subtitle file and the written script.
const asked = (s, text, at, len, how = 'said') => s.cue('ask', at, { text, len, how });
const first = (text, sentences = 1) => text.split(/(?<=[.!?])\s+/).slice(0, sentences).join(' ');

// ============ 1. "Hey Jarvis" — one sentence, two things done ============
scene('wake', 7, { over: 0.5, accent: 'teal', mix: { pad: 0.7, bass: 0.5, arp: 0.35, kick: 0, hat: 0, clap: 0, bright: 4, build: 1 } }, (s, root) => {
  const hero = el('div', 'hero', root);
  const orb = s.clip('orb', hero);
  const win = s.win('wake');
  const c = win.clip;
  const hey = spoken(root, 'Hey Jarvis', { y: 900 });
  const ask = spoken(root, 'Set a timer for twenty minutes and show me the weather in Paris', { y: 880 });
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  css(title, { top: '408px', fontSize: '168px' });
  const tagline = el('div', 'tagline', root, 'Your personal AI assistant. It listens — and it acts.');
  tagline.style.top = '640px';
  const credit = el('div', 'credit', root, 'Created by <b>Ariel</b> and <b>Shalev</b>');
  credit.style.top = '730px';
  const flash = el('div', 'flash', root);

  // the take: answer "I'm here" at 2.0 s; the rest follows at its own pace, then two cuts
  const here = markOf('wake', 'reply:Hey'), listen2 = markOf('wake', 'listening:Set'), heard2 = markOf('wake', 'heard:Set');
  const result = markOf('wake', 'result'), timer = markOf('wake', 'timer');
  const T_HERE = 2.0, T_ASK = T_HERE + (listen2 - here) / FPS, T_RESULT = T_HERE + (result - here) / FPS;
  const T_TIMER = 10.4, T_TITLE = 12.0;
  const pieces = [[0, here - T_HERE * FPS], [T_TIMER, timer + 6]];
  const l1 = voice(s, 'wake', 0, T_HERE), l2 = voice(s, 'wake', 1, T_RESULT + 0.1, { most: 6.3 });
  const sub1 = subtitle(root, l1.text), sub2 = subtitle(root, first(l2.text, 2));
  const o0 = markOf('orb', 'listening') - 12;
  asked(s, 'Hey Jarvis', 0.55, 0.8); asked(s, 'Set a timer for twenty minutes and show me the weather in Paris', T_ASK, 2.6);
  s.cue('orb', 0.15); s.cue('listen', 0.55); s.cue('listen', T_ASK); s.cue('open', T_RESULT); s.cue('whoosh', T_TIMER - 0.25); s.cue('tick', T_TIMER + 0.15);
  s.cue('swell', T_TITLE - 1.3); s.cue('title', T_TITLE);
  FILM.backgroundLevel = (T) => seg(T, 0.6, 3, E.sine) * (1 - seg(T, FILM.duration - 2.6, FILM.duration - 1.2));
  FILM.blackLevel = (T) => Math.max(1 - seg(T, 0.1, 0.5, E.out), seg(T, FILM.duration - 1.5, FILM.duration - 0.3, E.sine));

  return (t) => {
    // the orb alone, already listening; then the real window gathers around it as he answers
    const dock = seg(t, 1.25, 2.05, E.ioQ);
    const wz = 0.84, wx = 960, wy = 520;
    const ox = wx + (SPOT.orb[0] - 0.5) * 1920 * wz, oy = wy + (SPOT.orb[1] - 0.5) * 1080 * wz;
    orb.show(o0 + t * FPS);
    css(hero, { transform: `translate(${px(lerp(0, ox - 960, dock))}, ${px(lerp(-40, oy - 540, dock))}) scale(${lerp(lerp(0.86, 1.02, seg(t, 0.1, 1.4, E.outQ)), wz * ORB_IN_WINDOW, dock).toFixed(5)})`,
      opacity: (seg(t, 0.12, 0.5, E.out) * (1 - seg(t, 1.7, 2.1))).toFixed(4) });
    hey.draw(t, 0.55, 1.25, 1.75);

    c.show(cut(pieces, t));
    const arrive = seg(t, 1.45, 2.1, E.outQ);
    const toTitle = seg(t, T_TITLE - 0.35, T_TITLE + 0.25, E.in);
    const k = t < T_TIMER ? keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: wz * 1.05, ax: wx, ay: wy, ry: -4, rx: 1.5 }],
      [2.1, { cx: 0.5, cy: 0.5, z: wz, ax: wx, ay: wy, ry: -3, rx: 1.5 }, E.outQ],
      [T_ASK - 0.2, { cx: 0.5, cy: 0.5, z: wz + 0.01, ax: wx, ay: wy, ry: -2.6, rx: 1.4 }, E.lin],
      [T_ASK + 1.2, { cx: SPOT.stage[0], cy: 0.44, z: 1.3, ax: 960, ay: 470, ry: -1.5, rx: 0.8 }, E.ioQ],
      [T_RESULT - 0.1, { cx: SPOT.stage[0], cy: 0.44, z: 1.36, ax: 960, ay: 470, ry: -1, rx: 0.6 }, E.lin],
      [T_RESULT + 0.9, { cx: 0.5, cy: 0.5, z: 1.0, ax: 960, ay: 540, ry: 0, rx: 0 }, E.ioQ],
      [T_TIMER, { cx: 0.56, cy: 0.42, z: 1.16, ax: 960, ay: 540, ry: 0, rx: 0 }, E.lin],
    ]) : keys(t, [
      [T_TIMER, { cx: SPOT.timers[0], cy: SPOT.timers[1], z: 2.2, ax: 760, ay: 560, ry: 5, rx: 1 }],
      [T_TITLE + 0.3, { cx: SPOT.timers[0], cy: SPOT.timers[1], z: 2.36, ax: 760, ay: 560, ry: 4, rx: 1 }, E.out],
    ]);
    const w = whip(t, T_TIMER, 1, 0.3);
    win.at({ ...k, z: k.z * lerp(1, 1.5, toTitle), o: arrive * (1 - toTitle), blur: 12 * (1 - arrive) + (t < T_TIMER ? w.leave.blur * 0.35 : w.enter.blur * 0.35) + 30 * toTitle,
      radius: t > T_RESULT + 0.4 && t < T_TIMER ? 0 : 18 });
    ask.draw(t, T_ASK + 0.05, T_ASK + 2.5, T_RESULT + 0.9);
    sub1.draw(t, l1.at, l1.until + 0.3);
    sub2.draw(t, l2.at + 0.9, Math.min(l2.until, T_TITLE - 0.5));
    flash.style.opacity = (0.5 * pulse(t, T_TIMER - 0.07, T_TIMER + 0.2, 0.06, 0.2)).toFixed(4);

    // the name, hard on the bar
    [...title.children].forEach((letter, i) => {
      const p = seg(t, T_TITLE - 0.1 + i * 0.035, T_TITLE + 0.42 + i * 0.035, E.outQ), out = seg(t, s.dur - 0.1, s.dur + 0.4, E.in);
      css(letter, { opacity: (p * (1 - out)).toFixed(4), transform: `translateY(${px(30 * (1 - p))}) scale(${(lerp(1.5, 1, p) * lerp(1, 1.7, out) * (1 + 0.02 * clamp(t - T_TITLE, 0, 3))).toFixed(4)})`, filter: `blur(${px(18 * (1 - p) + 16 * out)})` });
    });
    const tg = seg(t, T_TITLE + 0.35, T_TITLE + 0.9, E.outQ), tgOut = seg(t, s.dur - 0.2, s.dur + 0.15, E.in);
    css(tagline, { opacity: (tg * (1 - tgOut)).toFixed(4), transform: `translateY(${px(14 * (1 - tg))})` });
    css(credit, { opacity: (seg(t, T_TITLE + 0.7, T_TITLE + 1.2) * (1 - tgOut)).toFixed(4) });
  };
});

// ============ 2. One spoken thread of mathematics ============
scene('mind', 6, { over: 0.6, accent: 'violet', mix: { pad: 0.85, bass: 0.9, arp: 0.7, kick: 0.85, hat: 0.4, clap: 0, bright: 5 } }, (s, root) => {
  const win = s.win('mind');
  const c = win.clip;
  const m = (label) => markOf('mind', label);
  const asks = [
    spoken(root, 'Solve x squared minus five x plus six equals zero, and draw the function', { y: 44 }),
    spoken(root, 'Compare x squared and x plus one', { y: 44 }),
  ];
  // two questions; of each, the last moment of listening, then the answer
  const T1 = 0.9, T2 = 7.0;
  const pieces = [[0, m('heard:Solve') - T1 * FPS - 9], [T1, m('reply:Solve')], [T2 - 0.9, m('heard:Compare') - 27], [T2, m('reply:Compare')]];
  const l1 = voice(s, 'mind', 0, T1 + 0.15, { most: 6.0 }), l2 = voice(s, 'mind', 1, T2 + 0.15, { most: 4.7 });
  const subs = [subtitle(root, first(l1.text, 2)), subtitle(root, first(l2.text, 2))];
  asked(s, 'Solve x squared minus five x plus six equals zero, and draw the function', 0, T1); asked(s, 'Compare x squared and x plus one', T2 - 0.95, 0.9);
  s.cue('whoosh', -0.25); s.cue('draw', T1); s.cue('listen', T2 - 0.9); s.cue('draw', T2);
  return (t) => {
    c.show(cut(pieces, t));
    const inn = seg(t, -0.05, 0.5, E.outQ);
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 1.0 }], [T1, { cx: 0.5, cy: 0.5, z: 1.02 }, E.lin],
      [T1 + 2.0, { cx: 0.47, cy: 0.5, z: 1.3 }, E.ioQ], [T2 - 0.2, { cx: 0.5, cy: 0.57, z: 1.46 }, E.lin],
      [T2 + 0.25, { cx: 0.5, cy: 0.5, z: 1.08 }, E.ioQ], [T2 + 2.4, { cx: 0.5, cy: 0.5, z: 1.24 }, E.io],
      [s.dur + 0.6, { cx: 0.5, cy: 0.45, z: 1.52 }, E.io],
    ]);
    win.at({ ...k, z: k.z * lerp(0.9, 1, inn), o: inn, blur: 16 * (1 - inn), radius: 0 });
    asks[0].draw(t, -0.6, T1 - 0.1, T1 + 1.3);
    asks[1].draw(t, T2 - 0.95, T2 - 0.1, T2 + 1.2);
    subs[0].draw(t, l1.at + 0.1, T2 - 1.1);
    subs[1].draw(t, l2.at + 0.1, s.dur - 0.25);
  };
});

// ============ 3. The Earth, a sunrise, a planet: one more thread ============
scene('world', 9, { over: 0.4, lead: 0.5, accent: 'blue', mix: { pad: 1.0, bass: 0.95, arp: 0.85, kick: 0.9, hat: 0.55, clap: 0.4, bright: 8 } }, (s, root) => {
  const win = s.win('world');
  const c = win.clip;
  const m = (label) => markOf('world', label);
  const asks = [
    spoken(root, 'What is the distance between Tokyo and New York?', { y: 44 }),
    spoken(root, 'Show sunrise over Tokyo', { y: 44 }),
    spoken(root, 'Tell me about Saturn', { y: 44 }),
  ];
  const T1 = 0.5, T2 = 8.5, T3 = 13.4;
  const pieces = [[-1, m('reply:What') - (T1 + 1) * FPS], [T2 - 0.8, m('heard:Show') - 24], [T2, m('reply:Show')], [T3 - 0.7, m('heard:Tell') - 21], [T3, m('reply:Tell')]];
  const l1 = voice(s, 'world', 0, T1 + 0.2, { most: 6.9 }), l2 = voice(s, 'world', 1, T2 + 0.15, { most: 4.6 }), l3 = voice(s, 'world', 2, T3 + 0.15, { most: 4.7 });
  const subs = [subtitle(root, 'The distance between Tokyo, Japan and New York, United States is about 10,849 kilometers.'),
    subtitle(root, 'The Sun rises in Tokyo at 5:45 AM local time today.'), subtitle(root, first(l3.text))];
  asked(s, 'What is the distance between Tokyo and New York?', 0, T1); asked(s, 'Show sunrise over Tokyo', T2 - 0.85, 0.8); asked(s, 'Tell me about Saturn', T3 - 0.75, 0.7);
  s.cue('globe', T1); s.cue('listen', T2 - 0.8); s.cue('draw', T2); s.cue('listen', T3 - 0.7); s.cue('globe', T3);
  return (t) => {
    // through a circle growing out of the two curves' meeting point: the graph becomes the globe
    iris(root, t, -0.45, 0.35, 960, 500);
    c.show(cut(pieces, t));
    const out = seg(t, s.dur - 0.2, s.dur + 0.2);
    const k = keys(t, [
      [-0.5, { cx: 0.5, cy: 0.5, z: 1.18 }], [T1 + 0.4, { cx: 0.5, cy: 0.5, z: 1.2 }, E.lin],
      [T1 + 3.2, { cx: 0.5, cy: 0.5, z: 1.46 }, E.ioQ], [T2 - 0.3, { cx: 0.5, cy: 0.52, z: 1.58 }, E.lin],
      [T2 + 0.4, { cx: 0.5, cy: 0.5, z: 1.3 }, E.ioQ], [T3 - 0.2, { cx: 0.5, cy: 0.5, z: 1.5 }, E.lin],
      [T3 + 0.35, { cx: 0.5, cy: 0.47, z: 1.14 }, E.ioQ], [s.dur + 0.4, { cx: 0.5, cy: 0.46, z: 1.38 }, E.lin],
    ]);
    win.at({ ...k, o: 1, radius: 0, blur: 0 });
    asks[0].draw(t, -0.7, T1 - 0.1, T1 + 1.5);
    asks[1].draw(t, T2 - 0.85, T2 - 0.1, T2 + 1.2);
    asks[2].draw(t, T3 - 0.75, T3 - 0.1, T3 + 1.2);
    subs[0].draw(t, l1.at + 0.6, T2 - 1.0);
    subs[1].draw(t, l2.at + 0.1, T3 - 0.9);
    subs[2].draw(t, l3.at + 0.1, s.dur - 0.3);
    root.style.opacity = (1 - out).toFixed(4);
  };
});

// ============ 4. From the phone: the same Jarvis, on the computer ============
scene('link', 8, { over: 0.4, lead: 0.3, accent: 'cyan', mix: { pad: 0.85, bass: 0.9, arp: 0.75, kick: 0.85, hat: 0.4, clap: 0, bright: 6 } }, (s, root) => {
  const desk = s.win('link.desk');
  const phone = new Phone(s, 'link', root);
  const d = desk.clip, p = phone.clip;
  const m = (label) => markOf('link', label);
  const beam = el('div', 'beam', root);
  const cap = new Caption(root, { kicker: 'Phone + computer', head: 'Ask on your phone.\nIt happens here.', x: 1040, y: 96, width: 820, size: 58 });
  const alone = new Caption(root, { kicker: 'On this phone', head: 'Or let the phone\nanswer by itself.', x: 1040, y: 96, width: 820, size: 58 });
  // the phone's take and the computer's are one recording (same frames): cut both together
  const T1 = 2.3, T2 = 7.6, T3 = 12.2;                                   // Mars arrives; the journey arrives; the phone alone
  const typing = (label, len) => m('sent:' + label) - Math.round(len * FPS * 2);   // typing is shown at double speed
  const pieces = [[-0.4, typing('Show', 1.0) - 12], [0.2, typing('Show', 1.0), 2], [1.2, m('sent:Show')], [T1 - 0.25, m('reply:Show') - 8],
    [5.6, typing('Distance', 1.4), 2], [7.0, m('sent:Distance')], [T2 - 0.25, m('reply:Distance') - 8],
    [10.8, m('switch') - 4], [11.6, typing('Graph', 0.9), 2], [12.5, m('sent:Graph')], [T3 + 0.55, m('reply:Graph') - 6]];
  asked(s, 'Show me Mars', 0.2, 1.0, 'typed on the phone'); asked(s, 'Distance between Paris and Rome', 5.6, 1.4, 'typed on the phone'); asked(s, 'Graph sine of x over x', 11.6, 0.9, 'typed on the phone, answered by the phone itself');
  s.cue('whoosh', -0.2); s.cue('keys', 0.2, { len: 1.0 }); s.cue('send', 1.25); s.cue('globe', T1); s.cue('keys', 5.6, { len: 1.4 }); s.cue('send', 7.05); s.cue('globe', T2);
  s.cue('switch', 10.95); s.cue('keys', 11.6, { len: 0.9 }); s.cue('send', 12.55); s.cue('draw', T3 + 0.6);
  return (t) => {
    const w = whip(t, 0, -1, 0.36), out = whip(t, s.dur, -1, 0.34);
    const f = cut(pieces, t);
    p.show(f); d.show(f);
    const solo = seg(t, 10.7, 11.5, E.ioQ);                              // the computer steps back when the phone works alone
    const x = (t < 1 ? w.enter.x : 0) + (t > s.dur - 1 ? out.leave.x : 0), smear = (t < 1 ? w.enter.blur : 0) + (t > s.dur - 1 ? out.leave.blur : 0);
    root.style.transform = `translateX(${px(x)})`;
    root.style.filter = smear > 0.5 ? `blur(${px(smear * 0.5)})` : 'none';
    phone.at({ x: lerp(330, 420, solo), y: 548 + 7 * Math.sin(t * 0.9), scale: lerp(0.94, 1.0, solo) * (1 + 0.0025 * t), ry: lerp(10, 6, solo) + 1.2 * Math.sin(t * 0.5), rz: -0.8 });
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 0.62, ax: 1290, ay: 620, ry: -7, rx: 1.5 }],
      [T1, { cx: 0.5, cy: 0.5, z: 0.63, ax: 1290, ay: 620, ry: -6.5, rx: 1.5 }, E.lin],
      [T1 + 1.3, { cx: 0.5, cy: 0.5, z: 0.7, ax: 1262, ay: 630, ry: -5, rx: 1.2 }, E.ioQ],
      [10.6, { cx: 0.5, cy: 0.5, z: 0.72, ax: 1262, ay: 630, ry: -4.5, rx: 1.2 }, E.lin],
      [11.6, { cx: 0.5, cy: 0.5, z: 0.6, ax: 1340, ay: 640, ry: -10, rx: 1.5 }, E.ioQ],
    ]);
    desk.at({ ...k, o: 1 - 0.72 * solo, blur: 7 * solo, bright: 1 - 0.3 * solo });
    // the request crossing from the phone to the computer
    [[1.2, T1], [7.0, T2]].forEach(([from, to], i) => {
      if (t < from - 0.05 || t > to + 0.5) return;
      const go = seg(t, from, to + 0.1, E.io);
      css(beam, { left: '520px', top: px(lerp(840, 560, go)), width: '420px', opacity: pulse(t, from, to + 0.4, 0.15, 0.4).toFixed(4),
        transform: `rotate(-14deg) translateX(${px(lerp(-160, 260, go))}) scaleX(${(0.5 + 0.5 * Math.sin(Math.PI * go)).toFixed(3)})` });
    });
    if (t < 1.1 || (t > T1 + 0.6 && t < 6.9) || t > T2 + 0.6) beam.style.opacity = 0;
    cap.draw(t, 0.35, 10.9);
    alone.draw(t, 11.3, s.dur + 0.1);
  };
});

// ============ 5. With your permission, the mouse and keyboard ============
scene('control', 5, { over: 0.4, lead: 0.3, accent: 'warm', mix: { pad: 0.8, bass: 0.7, arp: 0.3, kick: 0, hat: 0.3, clap: 0, bright: 4, build: 1 } }, (s, root) => {
  const win = s.win('control');
  const screen = s.win('controlbar', { lights: false });
  const strip = new Crop(s, 'controlbar', root);
  const c = win.clip, b = screen.clip;
  const mc = (label) => markOf('control', label), mb = (label) => markOf('controlbar', label);
  const dark = scrim(root, 'right', 40, 7);
  const cap = new Caption(root, { kicker: 'Computer control', head: 'He can take\nthe mouse.\n~He ~asks ~first.', x: 1300, y: 320, width: 560, size: 74 });
  const yours = corner(root, 'Your screen, while Jarvis works', { x: 108, y: 84 });
  const T_ASK = 0.9, T_ALLOW = 3.6, T_BAR = 4.1;
  const pieces = [[-0.5, mc('sent') - 42], [T_ASK, mc('asked')], [T_ALLOW - 0.45, mc('allow') - 14]];
  // the bar: looking, deciding, paused, stopped: a second of each
  const bar = [[T_BAR, mb('observing') - 6], [T_BAR + 1.5, mb('thinking') + 6], [T_BAR + 2.7, mb('pause') - 8], [T_BAR + 4.2, mb('stop') - 10]];
  asked(s, 'Use my computer to turn on dark mode in Chrome', 0, T_ASK, 'typed');
  s.cue('whoosh', -0.2); s.cue('keys', -0.4, { len: 1.1 }); s.cue('sheet', T_ASK); s.cue('click', T_ALLOW); s.cue('whoosh', T_BAR - 0.2);
  s.cue('tick', T_BAR + 1.5); s.cue('tick', T_BAR + 3.0); s.cue('stop', T_BAR + 4.55);
  return (t) => {
    const w = whip(t, 0, -1, 0.34), out = seg(t, s.dur - 0.12, s.dur + 0.1);
    root.style.transform = `translateX(${px(t < 1 ? w.enter.x : 0)})`;
    root.style.filter = t < 1 && w.enter.blur > 0.5 ? `blur(${px(w.enter.blur * 0.5)})` : 'none';
    root.style.opacity = (1 - out).toFixed(4);
    c.show(cut(pieces, t));
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.58, z: 0.8, ax: 640, ay: 540, ry: 5, rx: 1.2 }],
      [T_ASK, { cx: 0.5, cy: 0.56, z: 0.82, ax: 640, ay: 540, ry: 5, rx: 1.2 }, E.lin],
      [T_ASK + 0.9, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.2, ax: 640, ay: 540, ry: 3, rx: 0.8 }, E.ioQ],
      [T_BAR + 0.2, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.27, ax: 640, ay: 540, ry: 2.6, rx: 0.8 }, E.lin],
    ]);
    const gone = seg(t, T_BAR - 0.2, T_BAR + 0.25);
    win.at({ ...k, z: k.z * lerp(1, 1.3, gone), o: 1 - gone, blur: 22 * gone });
    b.show(cut(bar, t));
    const arrive = seg(t, T_BAR - 0.1, T_BAR + 0.5, E.outQ);
    screen.at({ cx: 0.5, cy: 0.5, z: lerp(0.5, 0.57, arrive) + 0.004 * t, ax: 640, ay: 430, ry: lerp(8, 4, arrive), rx: 1.2, o: arrive, blur: 14 * (1 - arrive), glare: 0.5 });
    strip.clip.show(cut(bar, t));
    const near = seg(t, T_BAR + 0.2, T_BAR + 0.8, E.outQ);
    strip.at({ x: 640, y: 878 + 20 * (1 - near), w: 1090, h: 132, cx: 0.5, cy: 0.942, z: 2.02, o: near, radius: 14 });
    yours.draw(t, T_BAR + 0.3, s.dur);
    dark.draw(1);
    cap.draw(t, 0.3, s.dur + 0.1, { each: 0.06 });
  };
});

// ============ 6. And everything else, one beat each ============
scene('more', 5, { over: 0.3, accent: 'teal', mix: { pad: 0.9, bass: 0.95, arp: 0.9, kick: 0.95, hat: 0.6, clap: 0.5, bright: 7 } }, (s, root) => {
  // each: a take, where in it, what part of the window, one word
  const shots = [
    { take: 'talk', at: markOf('talk', 'reply:Play') + 24, cx: 0.853, cy: 0.5, z: 1.7, word: 'Music.' },
    { take: 'talk', at: markOf('talk', 'reply:Show') + 24, cx: 0.853, cy: 0.66, z: 1.7, word: 'Trailers.' },
    { take: 'docs', at: markOf('docs', 'reply:Write') + 30, cx: 0.6, cy: 0.4, z: 1.7, word: 'Documents.', page: true },
    { take: 'picture', at: markOf('picture', 'picture') + 20, cx: 0.853, cy: 0.52, z: 1.86, word: 'Pictures.' },
    { take: 'picture', at: markOf('picture', 'reply:What') + 30, cx: 0.853, cy: 0.55, z: 1.7, word: 'Vision.' },
    { take: 'plan', at: markOf('plan', 'reply:1 hour') + 24, cx: 0.853, cy: 0.72, z: 1.7, word: 'Calendar.' },
    { take: 'solve', at: markOf('solve', 'reply') + 40, cx: 0.853, cy: 0.55, z: 1.26, word: 'Step by step.' },
    { take: 'android', at: markOf('android', 'globe') + 90, phone: true, word: 'Android.' },
    { take: 'settings', at: markOf('settings', 'open') + 40, cx: 0.5, cy: 0.285, z: 1.9, word: 'Local AI.' },
    { take: 'pairing', at: markOf('pairing', 'code') + 30, cx: 0.5, cy: 0.42, z: 1.9, word: 'Paired by code.' },
  ];
  const per = s.dur / shots.length;                                        // one beat... two beats at 120: 1 s each
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
    s.cue(i ? 'slide' : 'whoosh', i * per - (i ? 0.02 : 0.2));
    return { shot, layer, view, page, word };
  });
  const flash = el('div', 'flash', root);
  return (t) => {
    const i = clamp(Math.floor(t / per), 0, shots.length - 1), into = t - i * per;
    views.forEach((v, n) => {
      const on = n === i;
      v.layer.style.visibility = on ? '' : 'hidden';
      if (!on) { v.view.clip.release(); return; }
      v.view.clip.show(v.shot.at + into * FPS);
      const push = 1 + 0.05 * (into / per), slide = (1 - seg(into, 0, 0.3, E.outQ)) * 70;
      if (v.shot.phone) v.view.at({ x: 1380 - slide, y: 548, scale: 0.96 * push, ry: -8, rz: 0.8 });
      else v.view.at({ x: 960, y: 540, w: 1920, h: 1080, cx: v.shot.cx, cy: v.shot.cy, z: v.shot.z * push, radius: 0, bright: 0.92 });
      if (v.page) css(v.page, { transform: `perspective(2400px) translateX(${px(slide * 1.6)}) rotateY(-6deg) rotateZ(0.8deg)`, opacity: seg(into, 0, 0.25).toFixed(3) });
      const p = seg(into, 0.02, 0.32, E.outQ);
      css(v.word, { opacity: p.toFixed(4), transform: `translateX(${px(-50 * (1 - p))})` });
    });
    flash.style.opacity = (0.3 * pulse(into, -0.02, 0.16, 0.03, 0.14)).toFixed(4);
    root.style.opacity = (1 - seg(t, s.dur - 0.08, s.dur + 0.12)).toFixed(4);
  };
});

// ============ 7. Close ============
scene('close', 4, { over: FILM.tail, accent: 'cyan', mix: { pad: 1.0, bass: 0.7, arp: 0.45, kick: 0, hat: 0, clap: 0, bright: 7, final: 1 } }, (s, root) => {
  const hero = el('div', 'hero', root);
  const orb = s.clip('orb', hero);
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  css(title, { top: '448px', fontSize: '150px' });
  const tagline = el('div', 'tagline', root, 'One assistant. Your computer. Your phone.');
  tagline.style.top = '660px';
  const credit = el('div', 'credit', root, 'Created by <b>Ariel</b> and <b>Shalev</b>');
  credit.style.top = '766px';
  const platforms = el('div', 'fine soft', root, 'macOS · Windows 10 and 11 · iPhone · Android');
  css(platforms, { top: '834px', letterSpacing: '.04em' });
  const o0 = markOf('orb', 'speaking') - 10;
  s.cue('final', 0.0); s.cue('end', s.dur);
  return (t) => {
    orb.show(o0 + t * FPS);
    const out = seg(t, s.dur + 0.1, s.dur + 1.1, E.sine);
    css(hero, { transform: `translate(0, ${px(-210)}) scale(${lerp(0.62, 0.5, seg(t, 0, 1.6, E.outQ)).toFixed(5)})`, opacity: (seg(t, 0, 0.3, E.out) * (1 - out)).toFixed(4) });
    [...title.children].forEach((letter, i) => {
      const q = seg(t, 0.05 + i * 0.05, 0.75 + i * 0.05, E.outQ);
      css(letter, { opacity: (q * (1 - out)).toFixed(4), transform: `translateY(${px(36 * (1 - q))}) scale(${(lerp(1.25, 1, q) * (1 + 0.004 * t)).toFixed(4)})`, filter: `blur(${px(14 * (1 - q))})` });
    });
    const tg = seg(t, 1.0, 1.7, E.outQ), cr = seg(t, 2.2, 2.9, E.outQ), pl = seg(t, 3.0, 3.7, E.outQ);
    css(tagline, { opacity: (tg * (1 - out)).toFixed(4), transform: `translateY(${px(14 * (1 - tg))})` });
    css(credit, { opacity: (cr * (1 - out)).toFixed(4), transform: `translateY(${px(10 * (1 - cr))})` });
    css(platforms, { opacity: (pl * 0.9 * (1 - out)).toFixed(4) });
  };
});
