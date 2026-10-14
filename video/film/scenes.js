// The film, scene by scene. Each scene builds its elements once and returns draw(t): t is seconds since the scene
// began. Footage frame numbers come from the marks the recorder saved with each clip (assets/footage/*.json), so a
// re-recorded clip stays in step. s.cue() notes where the soundtrack should place a sound.

// Where things are in the Jarvis window (fractions of its width and height), for the camera.
const SPOT = {
  orb: [0.472, 0.322], stage: [0.472, 0.47], type: [0.472, 0.8], talk: [0.868, 0.4], left: [0.12, 0.5], sheet: [0.5, 0.49],
  timers: [0.13, 0.56], full: [0.5, 0.5],
};
const TALK_F0 = 79;              // where scene 2 picks the opening take up (the window has been up for a second by then)
const ORB_IN_WINDOW = 0.588;   // the orb's size in the window, relative to the orb filmed alone at the same width

// ============ 1. Opening: the orb, the name ============
scene('opening', 5, { over: 0.9, accent: 'cyan' }, (s, root) => {
  const glow = el('div', 'layer', root);
  const hero = el('div', 'hero', root);
  const orb = s.clip('orb', hero);
  const rings = [0, 1, 2].map(() => el('div', 'ring', root));
  const corners = ['tl', 'tr', 'bl', 'br'].map((k) => {
    const c = el('div', 'reticle', root);
    css(c, { [k[0] === 't' ? 'borderTopWidth' : 'borderBottomWidth']: '2px', [k[1] === 'l' ? 'borderLeftWidth' : 'borderRightWidth']: '2px' });
    return [c, k];
  });
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  title.style.top = '700px';
  const tagline = el('div', 'tagline', root, 'Your personal AI assistant.');
  tagline.style.top = '862px';
  const credit = el('div', 'credit', root, 'Created by <b>Ariel</b> and <b>Shalev</b>');
  credit.style.top = '948px';
  const win = s.win('talk');
  const first = orb.mark('idle') + 60;

  s.cue('orb', 0.9); s.cue('title', 5.0); s.cue('swell', 9.6); s.cue('whoosh', 10.7);
  FILM.backgroundLevel = (T) => seg(T, 2.5, 8, E.sine) * (1 - seg(T, FILM.duration - 4.2, FILM.duration - 2.2));
  const before = FILM.blackLevel;
  FILM.blackLevel = (T) => Math.max(1 - seg(T, 0.5, 2.0, E.sine) * 1, before(T));

  return (t) => {
    // the orb: out of the dark, a slow push toward it, then up to make room for the name, then into the window
    const dock = seg(t, 10.3, 12.0, E.ioQ);                     // 0 = alone, 1 = sitting where the window's orb is
    const lift = seg(t, 4.3, 6.2, E.ioQ);
    const z0 = lerp(lerp(0.8, 0.98, seg(t, 0.6, 5.2, E.out)), 0.74, lift);
    const y0 = lerp(540, 392, lift);
    const wz = lerp(0.86, 0.86, dock), wx = 960, wy = 548;      // where the window will stand as scene 2 opens
    const ox = wx + (SPOT.orb[0] - 0.5) * 1920 * wz, oy = wy + (SPOT.orb[1] - 0.5) * 1080 * wz;
    const z = lerp(z0, wz * ORB_IN_WINDOW, dock), x = lerp(960, ox, dock), y = lerp(y0, oy, dock);
    orb.show(first + t * FPS);
    css(hero, { transform: `translate(${px(x - 960)}, ${px(y - 540)}) scale(${z.toFixed(5)})`,
      opacity: (seg(t, 0.7, 3.2, E.sine) * (1 - seg(t, 11.3, 11.95))).toFixed(4) });
    glow.style.background = `radial-gradient(circle 520px at ${px(x)} ${px(y)}, rgb(var(--cyan) / ${(0.16 * seg(t, 0.3, 3) * (1 - dock)).toFixed(3)}), transparent 70%)`;

    // thin instrument marks around it, like the window's own
    rings.forEach((ring, i) => {
      const p = seg(t, 2.6 + i * 0.35, 4.6 + i * 0.35, E.outQ), size = (560 + i * 150) * (z / 0.9) * lerp(0.86, 1, p);
      css(ring, { left: px(x - size / 2), top: px(y - size / 2), width: px(size), height: px(size),
        opacity: (p * [0.34, 0.2, 0.1][i] * (1 - seg(t, 9.8, 10.8))).toFixed(4),
        transform: `rotate(${(t * [7, -5, 3][i]).toFixed(2)}deg)`, borderStyle: i === 1 ? 'dashed' : 'solid' });
    });
    corners.forEach(([c, k], i) => {
      const p = seg(t, 3.2 + i * 0.08, 4.4 + i * 0.08, E.outQ), half = lerp(430, 330, p) * (z / 0.9);
      css(c, { left: px(x + (k[1] === 'l' ? -half : half - 46)), top: px(y + (k[0] === 't' ? -half : half - 46)),
        opacity: (p * 0.8 * (1 - seg(t, 9.8, 10.6))).toFixed(4) });
    });

    // the name, a letter at a time
    [...title.children].forEach((letter, i) => {
      const p = seg(t, 5.0 + i * 0.11, 6.1 + i * 0.11, E.outQ), out = seg(t, 9.9, 10.7, E.in);
      css(letter, { opacity: (p * (1 - out)).toFixed(4), transform: `translateY(${px(46 * (1 - p) - 20 * out)}) scale(${lerp(1.12, 1, p).toFixed(4)})`,
        filter: `blur(${px(14 * (1 - p) + 8 * out)})` });
    });
    const tg = seg(t, 6.5, 7.6, E.outQ), tgOut = seg(t, 9.9, 10.6, E.in);
    css(tagline, { opacity: (tg * (1 - tgOut)).toFixed(4), transform: `translateY(${px(18 * (1 - tg) - 14 * tgOut)})`, letterSpacing: `${lerp(0.05, 0.01, tg).toFixed(4)}em` });
    const cr = seg(t, 8.0, 9.0, E.outQ);
    css(credit, { opacity: (cr * (1 - tgOut)).toFixed(4), transform: `translateY(${px(12 * (1 - cr))})` });

    // the real window gathers around the orb
    const w = seg(t, 10.9, 12.0, E.outQ);
    win.clip.show(TALK_F0 + (t - s.dur) * FPS);   // already running as the orb settles into it
    win.at({ cx: 0.5, cy: 0.5, z: wz * lerp(1.06, 1, w), ax: wx, ay: wy, o: w, ry: lerp(-7, -5, w), rx: 2, blur: 12 * (1 - w) });
    if (t > 12) { hero.style.opacity = 0; win.at({ o: 0 }); title.style.visibility = 'hidden'; }
  };
});

// ============ 2. Talk naturally ============
scene('talk', 4, { accent: 'teal' }, (s, root) => {
  const win = s.win('talk');
  const c = win.clip, f0 = TALK_F0;
  const dark = scrim(root, 'left', 44, 9);
  const cap = new Caption(root, { kicker: 'Talk naturally', head: 'Speak.\nType.\nAsk.', x: 118, y: 352, width: 520, size: 96 });
  const heard = said(root, '“Hey Jarvis”', { x: 118, y: 800 });
  const listenAt = (c.mark('listening:Hey') - f0) / FPS, typeAt = (c.mark('sent:Play') - f0) / FPS - 2.1;
  s.cue('listen', listenAt); s.cue('tick', (c.mark('reply:Hey') - f0) / FPS); s.cue('keys', typeAt, { len: 2.0 }); s.cue('send', typeAt + 2.1);
  return (t) => {
    c.show(f0 + t * FPS);
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 0.86, ax: 960, ay: 548, ry: -5, rx: 2 }],
      [1.5, { cx: SPOT.stage[0], cy: SPOT.stage[1], z: 0.98, ax: 1200, ay: 548, ry: -6, rx: 1.6 }, E.ioQ],
      [listenAt + 1.6, { cx: SPOT.stage[0], cy: SPOT.stage[1], z: 1.2, ax: 1210, ay: 560, ry: -4, rx: 1.2 }, E.io],
      [typeAt - 0.3, { cx: SPOT.stage[0], cy: SPOT.stage[1], z: 1.24, ax: 1210, ay: 556, ry: -3.6, rx: 1 }, E.lin],
      [typeAt + 1.0, { cx: SPOT.type[0], cy: 0.66, z: 1.2, ax: 1210, ay: 560, ry: -4.2, rx: 1.2 }, E.ioQ],
      [s.dur, { cx: SPOT.type[0], cy: 0.66, z: 1.24, ax: 1210, ay: 560, ry: -3.8, rx: 1.1 }, E.lin],
    ]);
    win.at(k);
    dark.draw(seg(t, 0.3, 1.5));
    cap.draw(t, 0.7, s.dur + 0.2);
    heard.draw(t, listenAt + 0.15, listenAt + 3.2);
  };
});

// ============ 3. Music, films, shows ============
scene('media', 5, { accent: 'blue' }, (s, root) => {
  const win = s.win('talk');
  const c = win.clip, f0 = TALK_F0 + 4 * BAR * FPS;                          // straight on from scene 2: the same take
  const dark = scrim(root, 'left', 44, 9);
  const cap = new Caption(root, { kicker: 'Entertainment', head: 'Your music.\nYour shows.\n~One ~assistant.', x: 118, y: 318, width: 620, size: 84 });
  const services = tags(root, ['Spotify', 'YouTube', 'Netflix', 'Stremio', 'Apple Music', 'YouTube Music'], { x: 118, y: 762, width: 600 });
  const typing = (c.mark('sent:Show') - f0) / FPS - 2.6, trailerReply = (c.mark('reply:Show') - f0) / FPS;
  s.cue('confirm', 0.1); s.cue('keys', typing + 0.3, { len: 2.2 }); s.cue('send', trailerReply - 0.5); s.cue('confirm', trailerReply);
  return (t) => {
    c.show(f0 + t * FPS);
    const h = handover(s, t);
    const k = keys(t, [
      [0, { cx: SPOT.type[0], cy: 0.66, z: 1.24, ax: 1210, ay: 560, ry: -3.8, rx: 1.1 }],
      [0.4, { cx: SPOT.type[0], cy: 0.66, z: 1.245, ax: 1210, ay: 560, ry: -3.8, rx: 1.1 }, E.lin],
      [1.9, { cx: SPOT.talk[0], cy: 0.37, z: 1.5, ax: 1330, ay: 530, ry: -3, rx: 0.8 }, E.ioQ],
      [typing - 0.2, { cx: SPOT.talk[0], cy: 0.38, z: 1.55, ax: 1330, ay: 530, ry: -2.6, rx: 0.8 }, E.lin],
      [typing + 1.2, { cx: SPOT.type[0], cy: 0.68, z: 1.22, ax: 1210, ay: 560, ry: -4, rx: 1 }, E.ioQ],
      [trailerReply + 0.1, { cx: SPOT.type[0], cy: 0.68, z: 1.25, ax: 1210, ay: 560, ry: -3.6, rx: 1 }, E.lin],
      [trailerReply + 1.5, { cx: SPOT.talk[0], cy: 0.6, z: 1.5, ax: 1330, ay: 540, ry: -3, rx: 0.8 }, E.ioQ],
      [s.dur + 0.7, { cx: SPOT.talk[0], cy: 0.62, z: 1.58, ax: 1330, ay: 540, ry: -2.4, rx: 0.6 }, E.lin],
    ]);
    win.at({ ...k, z: k.z * (t > s.dur ? h.z : 1), o: 1 - h.b, blur: 14 * h.b });
    dark.draw(1 - h.b);
    cap.draw(t, 0.5, s.dur + 0.1);
    services.draw(t, trailerReply + 0.6, s.dur + 0.1);
  };
});

// ============ 4. The computer, working for you ============
scene('control', 6, { accent: 'violet' }, (s, root) => {
  const win = s.win('control');
  const screen = s.win('controlbar', { lights: false });
  const strip = new Crop(s, 'controlbar', root);
  const yours = corner(root, 'Your screen, while Jarvis works', { x: 108, y: 84 });
  const c = win.clip, b = screen.clip;
  const f0 = c.mark('sent') - 50;
  const asked = (c.mark('asked') - f0) / FPS, allow = (c.mark('allow') - f0) / FPS;
  const swap = allow + 0.75;                                   // the window gives way to the screen being worked on
  const b0 = b.mark('observing') - 14;
  const paused = swap + (b.mark('pause') - b0) / FPS, stopped = swap + (b.mark('stop') - b0) / FPS;
  const dark = scrim(root, 'right', 42, 7);
  const cap = new Caption(root, { kicker: 'Computer control', head: 'Let Jarvis\nhandle\nthe clicks.', sub: 'He asks first. <b>Pause</b> or <b>Stop</b> him at any moment.',
    x: 1290, y: 300, width: 540, size: 84 });
  const rule = corner(root, 'He asks before sending, buying, deleting or installing anything', { x: 96, y: 992 });
  s.cue('keys', 0.1, { len: 1.5 }); s.cue('send', 1.62); s.cue('sheet', asked); s.cue('click', allow); s.cue('whoosh', swap - 0.25);
  s.cue('tick', paused); s.cue('tick', swap + (b.mark('resume') - b0) / FPS); s.cue('stop', stopped);
  return (t) => {
    const h = handover(s, t);
    c.show(f0 + t * FPS);
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.56, z: 0.74, ax: 770, ay: 540, ry: 6, rx: 1.5 }],
      [asked - 0.1, { cx: 0.5, cy: 0.56, z: 0.76, ax: 766, ay: 540, ry: 5.6, rx: 1.5 }, E.lin],
      [asked + 1.3, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.12, ax: 690, ay: 540, ry: 3.4, rx: 0.8 }, E.ioQ],
      [allow + 0.2, { cx: SPOT.sheet[0], cy: SPOT.sheet[1], z: 1.17, ax: 686, ay: 540, ry: 3, rx: 0.8 }, E.lin],
      [swap + 0.8, { cx: 0.5, cy: 0.5, z: 0.9, ax: 640, ay: 540, ry: 9, rx: 1 }, E.io],
    ]);
    const gone = seg(t, swap - 0.1, swap + 0.55);
    win.at({ ...k, z: k.z * lerp(0.94, 1, h.a), o: h.a * (1 - gone), blur: 10 * (1 - h.a) + 16 * gone });
    // the screen Jarvis is working on, with the real bar and glowing edge over it
    b.show(b0 + (t - swap) * FPS);
    const arrive = seg(t, swap, swap + 0.9, E.outQ);
    const kb = keys(t, [
      [swap, { cx: 0.5, cy: 0.5, z: 0.5, ax: 640, ay: 440, ry: 7, rx: 1.5 }],
      [swap + 1.0, { cx: 0.5, cy: 0.5, z: 0.56, ax: 640, ay: 440, ry: 5, rx: 1.2 }, E.outQ],
      [s.dur + 0.7, { cx: 0.5, cy: 0.5, z: 0.6, ax: 640, ay: 440, ry: 3.5, rx: 1 }, E.lin],
    ]);
    screen.at({ ...kb, z: kb.z * (t > s.dur ? h.z : 1), o: arrive * (1 - h.b), blur: 12 * (1 - arrive) + 14 * h.b, glare: 0.5 });
    // the bar itself, large enough to read: the same footage, close
    strip.clip.show(b0 + (t - swap) * FPS);
    const near = seg(t, swap + 0.7, swap + 1.6, E.outQ);
    strip.at({ x: 640, y: 884 + 24 * (1 - near), w: 1090, h: 132, cx: 0.5, cy: 0.942, z: 2.02, o: near * (1 - h.b), radius: 14, blur: 12 * h.b });
    yours.draw(t, swap + 0.6, s.dur);
    dark.draw(h.a * (1 - h.b));
    cap.draw(t, 0.5, s.dur + 0.1);
    rule.draw(t, asked + 0.8, swap + 0.2);
  };
});

// ============ 5. From an idea to a document ============
scene('docs', 5, { accent: 'cyan' }, (s, root) => {
  const win = s.win('docs');
  const c = win.clip;
  const first = c.meta.notes.first, shorter = c.meta.notes.shorter;
  const paragraphs = (doc) => (doc.body || '').split(/\n\s*\n/).filter((p) => p.trim()).map((p) => `<p>${p.trim().replace(/\*([^*]+)\*/g, '<em>$1</em>')}</p>`).join('');
  const page = el('div', 'page', root);
  const long = el('div', '', page, `<h3>${first.title}</h3>${paragraphs(first)}`);
  const short = el('div', '', page, `<h3>${shorter.title}</h3>${paragraphs(shorter)}`);
  el('div', 'fade', page);
  css(short, { position: 'absolute', left: '84px', right: '84px', top: '74px' });
  const cap = new Caption(root, { kicker: 'Documents', head: 'From a simple request\nto finished work.', x: 110, y: 742, width: 1000, size: 64 });
  const apps = tags(root, ['Google Docs', 'Word', 'Pages', 'TextEdit', 'Notepad', 'Notes'], { x: 110, y: 968, width: 1100 });
  const f0 = c.mark('sent:Write') - 58, f1 = c.mark('sent:Make') - 44;
  const sent = 58 / FPS, cut = 5.9, again = cut + 44 / FPS;
  s.cue('keys', 0.1, { len: 1.8 }); s.cue('send', sent); s.cue('page', sent + 1.1); s.cue('keys', cut + 0.2, { len: 1.2 }); s.cue('send', again); s.cue('confirm', again + 0.6);
  return (t) => {
    const h = handover(s, t);
    c.show(t < cut ? f0 + t * FPS : f1 + (t - cut) * FPS);
    const k = keys(t, [
      [0, { cx: 0.5, cy: 0.64, z: 0.86, ax: 640, ay: 392, ry: 5, rx: 1.2 }],
      [sent + 0.2, { cx: 0.5, cy: 0.64, z: 0.88, ax: 640, ay: 392, ry: 5, rx: 1.2 }, E.lin],
      [sent + 1.5, { cx: 0.8, cy: 0.36, z: 1.34, ax: 610, ay: 392, ry: 4, rx: 1 }, E.ioQ],
      [cut - 0.1, { cx: 0.8, cy: 0.36, z: 1.4, ax: 610, ay: 392, ry: 3.6, rx: 1 }, E.lin],
      [cut + 0.1, { cx: 0.6, cy: 0.62, z: 0.92, ax: 640, ay: 392, ry: 5.4, rx: 1.2 }, E.io],
      [again + 0.2, { cx: 0.6, cy: 0.62, z: 0.93, ax: 640, ay: 392, ry: 5.2, rx: 1.2 }, E.lin],
      [again + 1.4, { cx: 0.8, cy: 0.5, z: 1.34, ax: 610, ay: 392, ry: 4, rx: 1 }, E.ioQ],
      [s.dur + 0.7, { cx: 0.8, cy: 0.5, z: 1.4, ax: 610, ay: 392, ry: 3.6, rx: 1 }, E.lin],
    ]);
    // the window is cropped to a panel on the left: a clipping box keeps it out of the page's and the words' way
    win.cam.style.clipPath = 'inset(72px 772px 372px 72px round 18px)';
    win.at({ ...k, z: k.z * 1.0, o: h.a * (1 - h.b), blur: 10 * (1 - h.a) + 14 * h.b, radius: 0 });
    // the page: what Jarvis wrote, set as a sheet of paper
    const arrive = seg(t, sent + 0.9, sent + 2.0, E.outQ), tight = seg(t, again + 0.5, again + 1.5, E.ioQ);
    css(page, { left: '1216px', top: px(lerp(96, 150, tight)), width: '604px', height: px(lerp(890, 640, tight)),
      opacity: (arrive * (1 - h.b)).toFixed(4),
      transform: `perspective(2400px) translate(${px(120 * (1 - arrive))}, ${px(30 * (1 - arrive))}) rotateY(${lerp(-16, -5, arrive).toFixed(3)}deg) rotateZ(${lerp(2.2, 0.6, arrive).toFixed(3)}deg) scale(${(h.z > 1 ? h.z : 1).toFixed(4)})`,
      filter: h.b > 0.01 ? `blur(${px(12 * h.b)})` : 'none', visibility: arrive > 0.002 ? '' : 'hidden' });
    long.style.opacity = (1 - tight).toFixed(4);
    short.style.opacity = tight.toFixed(4);
    cap.draw(t, 0.6, s.dur + 0.1);
    apps.draw(t, 2.6, s.dur + 0.1);
  };
});

// ============ 6. Math becomes visual ============
scene('math', 7, { accent: 'violet' }, (s, root) => {
  const one = s.win('graph'), two = s.win('graph2'), sol = s.win('solve');
  const a = one.clip, b = two.clip, c = sol.clip;
  const scrim = el('div', 'scrim', root);
  scrim.style.background = 'linear-gradient(90deg, rgb(2 3 8 / .98) 0%, rgb(2 3 8 / .97) 31%, rgb(2 3 8 / 0) 39%)';
  const deeper = el('div', 'scrim', root);
  deeper.style.background = 'linear-gradient(90deg, rgb(2 3 8 / .98) 0%, rgb(2 3 8 / .97) 44%, rgb(2 3 8 / 0) 51%)';
  const cap = new Caption(root, { kicker: 'Math becomes visual', head: 'Understand\nthe answer.\nSee why.', x: 108, y: 352, width: 560, size: 84 });
  const a0 = a.mark('sent') - 26, b0 = b.mark('sent') - 34, c0 = c.mark('reply') - 2;
  const openA = 26 / FPS + 0.5, cutB = 5.6, openB = cutB + 34 / FPS + 0.5, cutC = 12.2;
  s.cue('keys', 0, { len: 0.8 }); s.cue('send', 26 / FPS); s.cue('draw', openA); s.cue('whoosh', cutB - 0.3); s.cue('send', cutB + 34 / FPS); s.cue('draw', openB);
  s.cue('whoosh', cutC - 0.3); s.cue('steps', cutC + 0.5);
  return (t) => {
    const h = handover(s, t);
    // one function, full frame: the camera goes into the curve
    a.show(a0 + t * FPS);
    const ka = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 1.0 }], [openA, { cx: 0.5, cy: 0.5, z: 1.02 }, E.lin],
      [openA + 2.2, { cx: 0.5, cy: 0.47, z: 1.24 }, E.ioQ], [cutB + 0.6, { cx: 0.5, cy: 0.56, z: 1.42 }, E.io],
    ]);
    const outA = seg(t, cutB - 0.15, cutB + 0.45);
    one.at({ ...ka, z: ka.z * lerp(0.95, 1, h.a) * lerp(1, 1.12, outA), o: h.a * (1 - outA), blur: 10 * (1 - h.a) + 16 * outA, radius: 0 });
    // two functions: the card moves aside and the words come in
    b.show(b0 + (t - cutB) * FPS);
    const inB = seg(t, cutB - 0.05, cutB + 0.65, E.outQ), outB = seg(t, cutC - 0.15, cutC + 0.45);
    const kb = keys(t, [
      [cutB, { cx: 0.5, cy: 0.5, z: 0.94, ax: 960, ay: 540 }], [openB - 0.2, { cx: 0.5, cy: 0.5, z: 1.0, ax: 960, ay: 540 }, E.outQ],
      [openB + 1.6, { cx: 0.5, cy: 0.5, z: 0.82, ax: 1310, ay: 540 }, E.ioQ], [cutC + 0.5, { cx: 0.5, cy: 0.52, z: 0.86, ax: 1318, ay: 540 }, E.lin],
    ]);
    two.at({ ...kb, z: kb.z * lerp(1, 1.1, outB), o: inB * (1 - outB), blur: 14 * (1 - inB) + 16 * outB, radius: 0 });
    // the same equation family, solved step by step: the conversation, close
    c.show(c0 + (t - cutC) * FPS);
    const inC = seg(t, cutC - 0.05, cutC + 0.7, E.outQ);
    const kc = keys(t, [
      [cutC, { cx: 0.853, cy: 0.5, z: 1.1, ax: 1290, ay: 520 }], [cutC + 1.2, { cx: 0.853, cy: 0.5, z: 1.18, ax: 1290, ay: 520 }, E.outQ],
      [s.dur + 0.7, { cx: 0.853, cy: 0.585, z: 1.24, ax: 1290, ay: 540 }, E.io],
    ]);
    sol.at({ ...kc, z: kc.z * (t > s.dur ? h.z : 1), o: inC * (1 - h.b), blur: 14 * (1 - inC) + 14 * h.b, radius: 0 });
    const side = seg(t, openB + 0.6, openB + 1.8);
    scrim.style.opacity = (side * (1 - h.b)).toFixed(4);
    deeper.style.opacity = (seg(t, cutC - 0.1, cutC + 0.6) * (1 - h.b)).toFixed(4);
    cap.draw(t, openB + 1.0, s.dur + 0.1);
  };
});

// ============ 7. The Earth, and the planets ============
scene('space', 8, { accent: 'blue' }, (s, root) => {
  const earth = s.win('globe'), saturn = s.win('saturn'), mars = s.win('mars');
  const g = earth.clip, sa = saturn.clip, ma = mars.clip;
  const scrim = el('div', 'scrim', root);
  scrim.style.background = 'linear-gradient(90deg, rgb(2 3 8 / .98) 0%, rgb(2 3 8 / .97) 31%, rgb(2 3 8 / 0) 38%)';
  const cap = new Caption(root, { kicker: 'In three dimensions', head: 'Explore\nthe world.\nDiscover\nthe universe.', x: 108, y: 310, width: 560, size: 78 });
  const g0 = g.mark('sent') - 24, s0 = sa.mark('reply') + 8, m0 = ma.mark('reply') + 8;
  const openG = 24 / FPS + 0.5, cutS = 10.4, cutM = 14.9;
  s.cue('keys', 0, { len: 0.7 }); s.cue('send', 24 / FPS); s.cue('globe', openG); s.cue('swell', cutS - 1.4); s.cue('whoosh', cutS - 0.3); s.cue('whoosh', cutM - 0.3);
  return (t) => {
    const h = handover(s, t);
    g.show(g0 + t * FPS);
    const kg = keys(t, [
      [0, { cx: 0.5, cy: 0.5, z: 1.0 }], [openG + 0.3, { cx: 0.5, cy: 0.5, z: 1.03 }, E.lin],
      [openG + 3.0, { cx: 0.5, cy: 0.5, z: 1.4 }, E.ioQ], [cutS + 0.6, { cx: 0.5, cy: 0.52, z: 1.5 }, E.lin],
    ]);
    const outG = seg(t, cutS - 0.15, cutS + 0.5);
    earth.at({ ...kg, z: kg.z * lerp(0.95, 1, h.a) * lerp(1, 1.14, outG), o: h.a * (1 - outG), blur: 10 * (1 - h.a) + 18 * outG, radius: 0 });
    // out to the planets
    const planet = (w, clip, f, from, to, last) => {
      clip.show(f + (t - from) * FPS);
      const i = seg(t, from - 0.05, from + 0.75, E.outQ), o = last ? h.b : seg(t, to - 0.15, to + 0.45);
      const k = keys(t, [[from, { z: 0.84, ax: 1250 }], [from + 1.1, { z: 0.9, ax: 1250 }, E.outQ], [to + 0.6, { z: 0.98, ax: 1250 }, E.lin]]);
      w.at({ cx: 0.5, cy: 0.47, ay: 540, ...k, z: k.z * lerp(1, 1.1, o), o: i * (1 - o), blur: 14 * (1 - i) + 16 * o, radius: 0 });
    };
    planet(saturn, sa, s0, cutS, cutM, false);
    planet(mars, ma, m0, cutM, s.dur, true);
    scrim.style.opacity = (seg(t, cutS, cutS + 0.9) * (1 - h.b)).toFixed(4);
    cap.draw(t, cutS + 0.5, s.dur + 0.1);
  };
});

// ============ 8. Every day ============
scene('everyday', 6, { accent: 'teal' }, (s, root) => {
  const meta = (name) => require(`../assets/footage/${name}.json`).marks;
  const mark = (name, label) => { const m = meta(name); return m[Object.keys(m).find((k) => k.startsWith(label))]; };
  const row = carousel(s, root, [
    { clip: 'weather', label: 'Weather and forecast', from: mark('weather', 'reply') + 60, cx: 0.5, cy: 0.5, z: 1 },
    { clip: 'plan', label: 'Timers', from: mark('plan', 'reply:Set') - 6, cx: 0.3, cy: 0.62, z: 1.62 },
    { clip: 'plan', label: 'Calendar', from: mark('plan', 'reply:1 hour') - 8, cx: 0.74, cy: 0.74, z: 1.62 },
    { clip: 'picture', label: 'Pictures from a sentence', from: mark('picture', 'picture') + 4, cx: 0.853, cy: 0.52, z: 1.9 },
    { clip: 'picture', label: 'Questions about your pictures', from: mark('picture', 'reply:What') - 6, cx: 0.74, cy: 0.66, z: 1.62 },
    { clip: 'question', label: 'Answers', from: mark('question', 'reply') - 6, cx: 0.74, cy: 0.5, z: 1.5 },
  ], { y: 470, w: 1216, h: 684, per: BAR, lead: 0.3 });
  const words = el('div', 'words', root, ['Plan.', 'Create.', 'Learn.', 'Remember.'].map((w) => `<span>${w}</span>`).join(''));
  words.style.top = '902px';
  for (let i = 0; i < 6; i++) s.cue(i ? 'slide' : 'whoosh', i * BAR - (i ? 0 : 0.2));
  return (t) => {
    const h = handover(s, t);
    css(root, { opacity: (h.a * (1 - h.b)).toFixed(4), transform: `scale(${h.z.toFixed(5)})`, filter: h.blur > 0.1 ? `blur(${px(h.blur)})` : 'none' });
    row(t);
    [...words.children].forEach((w, i) => {
      const lit = seg(t, 0.5 + i * 3.3, 1.2 + i * 3.3, E.outQ);
      css(w, { opacity: lerp(0.2, 1, lit).toFixed(4), transform: `translateY(${px(10 * (1 - seg(t, 0.2 + i * 0.1, 1 + i * 0.1, E.outQ)))})` });
    });
  };
});

// ============ 9. On your phone ============
scene('phone', 8, { accent: 'cyan' }, (s, root) => {
  const desk = s.win('talk');
  const iphone = new Phone(s, 'phone', root), android = new Phone(s, 'android', root, true);
  const p = iphone.clip, a = android.clip, d = desk.clip;
  const cap = new Caption(root, { kicker: 'iPhone · Android', head: 'Jarvis goes\nwhere you go.', x: 1160, y: 250, width: 720, size: 86 });
  const modes = el('div', 'modes', root, '<i class="glide"></i><span>On my computer</span><span>On this phone</span>');
  css(modes, { left: '1162px', top: '610px' });
  const glide = modes.firstChild;
  const line1 = el('p', 'sub', root, 'The phone sends the request. <b>Your computer does it.</b>');
  const line2 = el('p', 'sub', root, 'Or the phone answers <b>by itself</b>: graphs, the globe, timers, opening its own apps.');
  for (const l of [line1, line2]) css(l, { position: 'absolute', left: '1162px', top: '690px', margin: 0, maxWidth: '620px' });
  // the iPhone take: choose → "On my computer" → a request → switch → "On this phone" → two requests
  const p0 = p.mark('choose') + 6;
  const toComputer = (p.mark('computer') - p0) / FPS, sw = (p.mark('switch') - p0) / FPS;
  // the wait for the phone's own brain is not on film; after the switch the take simply carries on
  const droid = 13.2, a0 = a.mark('sent') - 40;
  s.cue('whoosh', -0.2); s.cue('click', toComputer - 0.2); s.cue('send', (p.mark('sent:Play') - p0) / FPS); s.cue('confirm', (p.mark('reply:Play') - p0) / FPS);
  s.cue('switch', sw); s.cue('send', (p.mark('sent:Open') - p0) / FPS); s.cue('confirm', (p.mark('reply:Open') - p0) / FPS);
  s.cue('draw', (p.mark('graph') - p0) / FPS); s.cue('whoosh', droid - 0.3);
  return (t) => {
    const h = handover(s, t);
    p.show(p0 + t * FPS);
    a.show(a0 + (t - droid) * FPS);
    d.show(d.mark('reply:Play') + 20 + t * FPS * 0.999);
    const phoneMode = seg(t, sw, sw + 0.5);
    // the computer, behind, while it is the one doing the work
    desk.at({ cx: 0.5, cy: 0.5, z: 0.62, ax: 520, ay: 470, ry: 14, rx: 2, o: 0.5 * h.a * (1 - h.b) * (1 - 0.75 * phoneMode), blur: 5 + 8 * phoneMode + 10 * h.b, bright: 0.8 });
    const two = seg(t, droid - 0.1, droid + 1.0, E.ioQ);
    iphone.at({ x: lerp(650, 380, two), y: 544 + 6 * Math.sin(t * 0.7), scale: lerp(0.9, 1.0, seg(t, 0, 1.2, E.outQ)) * lerp(1, 0.88, two) * (t > s.dur ? h.z : 1),
      ry: lerp(16, 9, seg(t, 0, 1.4, E.outQ)), rz: -1.2, o: h.a * (1 - h.b), blur: 10 * (1 - h.a) + 12 * h.b });
    android.at({ x: lerp(1060, 840, two), y: 556 - 6 * Math.sin(t * 0.7), scale: 0.82 * (t > s.dur ? h.z : 1), ry: lerp(-4, 5, two), rz: 1,
      o: two * (1 - h.b), blur: 12 * (1 - two) + 12 * h.b });
    cap.draw(t, 0.7, s.dur + 0.1);
    const m = pulse(t, toComputer + 0.2, droid - 0.2, 0.6, 0.5, E.outQ);
    css(modes, { opacity: m.toFixed(4), transform: `translateY(${px(14 * (1 - m))})`, visibility: m > 0.002 ? '' : 'hidden' });
    const first = modes.children[1], second = modes.children[2];
    css(glide, { left: px(lerp(0, first.offsetWidth, E.ioQ(phoneMode))), width: px(lerp(first.offsetWidth, second.offsetWidth, phoneMode)) });
    first.style.color = phoneMode < 0.5 ? '#fff' : '';
    second.style.color = phoneMode >= 0.5 ? '#fff' : '';
    const l1 = pulse(t, toComputer + 0.6, sw + 0.1, 0.6, 0.4, E.outQ), l2 = pulse(t, sw + 0.5, droid - 0.2, 0.6, 0.4, E.outQ);
    css(line1, { opacity: l1.toFixed(4), transform: `translateY(${px(12 * (1 - l1))})` });
    css(line2, { opacity: l2.toFixed(4), transform: `translateY(${px(12 * (1 - l2))})` });
  };
});

// ============ 10. Privacy and control ============
scene('trust', 5, { accent: 'teal' }, (s, root) => {
  const meta = (name) => require(`../assets/footage/${name}.json`).marks;
  const per = (5 * BAR) / 3;
  const row = carousel(s, root, [
    { clip: 'settings', label: 'A local AI, on your own computer', from: meta('settings').open + 30, cx: 0.5, cy: 0.285, z: 1.95 },
    { clip: 'pairing', label: 'Phones pair with a one-time code', from: meta('pairing').code + 14, cx: 0.5, cy: 0.42, z: 1.9 },
    { clip: 'control', label: 'He asks before taking the mouse', from: meta('control').asked + 20, cx: 0.5, cy: 0.5, z: 1.9, until: meta('control').allow - 3 },
  ], { y: 404, w: 1090, h: 613, per, lead: 0.4, gap: 60 });
  const cap = new Caption(root, { head: 'Powerful. Personal.\nDesigned with control in mind.', x: 260, y: 772, width: 1400, size: 60, align: 'center' });
  const fine = el('div', 'fine soft', root, 'The local AI is a choice in Settings. Online features (Groq, Spotify, Google and others) use those services and need their own accounts.');
  fine.style.top = '966px';
  for (let i = 0; i < 3; i++) s.cue(i ? 'slide' : 'whoosh', i * per - (i ? 0 : 0.2));
  return (t) => {
    const h = handover(s, t);
    css(root, { opacity: (h.a * (1 - h.b)).toFixed(4), transform: `scale(${h.z.toFixed(5)})`, filter: h.blur > 0.1 ? `blur(${px(h.blur)})` : 'none' });
    row(t);
    cap.draw(t, 0.5, s.dur + 0.3);
    fine.style.opacity = (pulse(t, 2.2, s.dur, 0.8, 0.4) * 0.95).toFixed(4);
  };
});

// ============ 11. Closing ============
scene('closing', 6, { over: FILM.tail, accent: 'cyan' }, (s, root) => {
  const desk = s.win('talk');
  const iphone = new Phone(s, 'phone', root);
  const hero = el('div', 'hero', root);
  const orb = s.clip('orb', hero);
  const orbit = el('div', 'orbit', root);
  const title = el('div', 'title', root, [...'JARVIS'].map((ch) => `<span>${ch}</span>`).join(''));
  css(title, { top: '418px', fontSize: '150px' });
  const tagline = el('div', 'tagline', root, 'One assistant. Your computer. Your phone.');
  tagline.style.top = '634px';
  const credit = el('div', 'credit', root, 'Created by <b>Ariel</b> and <b>Shalev</b>');
  credit.style.top = '742px';
  const platforms = el('div', 'fine soft', root, 'macOS · Windows 10 and 11 · iPhone · Android');
  css(platforms, { top: '812px', letterSpacing: '.04em' });
  const d = desk.clip, p = iphone.clip;
  const o0 = orb.mark('speaking') - 24;
  s.cue('whoosh', -0.2); s.cue('orb', 0.3); s.cue('link', 2.3); s.cue('final', 3 * BAR); s.cue('end', s.dur);
  return (t) => {
    const inn = seg(t, 0, 1.1, E.outQ);
    // the orb in the middle; the computer and the phone, the two halves of one assistant, either side of it
    const gather = seg(t, 5.9, 7.5, E.ioQ);                    // everything draws into the name
    d.show(d.mark('listening:Hey') + t * FPS);
    p.show(p.mark('reply:Play') + 10 + t * FPS);
    orb.show(o0 + t * FPS);
    desk.at({ cx: 0.5, cy: 0.5, z: lerp(0.37, 0.3, gather) * lerp(0.92, 1, inn), ax: lerp(lerp(300, 410, inn), 760, gather), ay: 540, ry: 14, rx: 2,
      o: inn * (1 - seg(t, 6.1, 7.2)), blur: 12 * (1 - inn) + 18 * gather });
    iphone.at({ x: lerp(lerp(1660, 1570, inn), 1160, gather), y: 540, scale: lerp(0.66, 0.5, gather) * lerp(0.92, 1, inn), ry: -14, rz: 1.2,
      o: inn * (1 - seg(t, 6.1, 7.2)), blur: 12 * (1 - inn) + 18 * gather });
    const oz = lerp(lerp(0.4, 0.5, inn), 0.5, gather), oy = lerp(540, 300, gather);
    css(hero, { transform: `translate(0, ${px(oy - 540)}) scale(${oz.toFixed(5)})`, opacity: (inn * (1 - seg(t, s.dur + 0.2, s.dur + 1.9, E.sine))).toFixed(4) });
    // one ring through both: two halves of the same assistant
    const ring = seg(t, 1.8, 3.6, E.ioQ) * (1 - seg(t, 5.6, 6.6));
    css(orbit, { opacity: ring.toFixed(4), transform: `rotate(-4deg) scale(${lerp(0.55, 1, seg(t, 1.8, 3.8, E.outQ)).toFixed(4)}, ${lerp(0.3, 1, seg(t, 1.8, 3.8, E.outQ)).toFixed(4)})` });
    const out = seg(t, s.dur + 0.3, s.dur + 1.7, E.sine);
    [...title.children].forEach((letter, i) => {
      const q = seg(t, 7.12 + i * 0.09, 8.2 + i * 0.09, E.outQ);
      css(letter, { opacity: (q * (1 - out)).toFixed(4), transform: `translateY(${px(40 * (1 - q))}) scale(${lerp(1.1, 1, q).toFixed(4)})`, filter: `blur(${px(14 * (1 - q))})` });
    });
    const tg = seg(t, 8.5, 9.6, E.outQ), cr = seg(t, 10.0, 11.0, E.outQ), pl = seg(t, 11.0, 12.0, E.outQ);
    css(tagline, { opacity: (tg * (1 - out)).toFixed(4), transform: `translateY(${px(16 * (1 - tg))})` });
    css(credit, { opacity: (cr * (1 - out)).toFixed(4), transform: `translateY(${px(12 * (1 - cr))})` });
    css(platforms, { opacity: (pl * 0.9 * (1 - out)).toFixed(4) });
  };
});

// The film ends on black.
{
  const before = FILM.blackLevel;
  FILM.blackLevel = (T) => Math.max(before(T), seg(T, FILM.duration - 2.3, FILM.duration - 0.5, E.sine));
}
