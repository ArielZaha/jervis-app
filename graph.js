// Jervis graph window: draws y = ax^2 + bx + c (or a line) as a glowing curve on a fine grid, with the vertex, the roots,
// the y-intercept and the axis of symmetry marked, a crosshair that follows the mouse, and "Save image".
// The picture is drawn by one function (render) that is used for the live canvas and for the exported PNG.
(function () {
  const $ = (id) => document.getElementById(id);
  let katex = null;
  try { katex = require('./vendor/katex/katex.min.js'); } catch (error) { /* the title falls back to plain text */ }

  const CYAN = [79, 216, 255], VIOLET = [165, 139, 255], MAGENTA = [255, 92, 214], GOLD = [255, 209, 102], GREEN = [61, 242, 192];
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const MINUS = '−';
  const REVEAL_SECONDS = 1.5;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let data = null, view = null, raf = 0, openedAt = 0, hoverX = null;
  const history = [];          // every graph drawn in this session, so any of them can be opened again as often as you like
  let current = -1;            // which of them is showing
  const MAX_HISTORY = 40;

  const num = (v) => {
    const s = String(parseFloat((Math.abs(v) < 1e-9 ? 0 : v).toPrecision(6)));
    return s.replace('-', MINUS);
  };
  // The syntax tree Python sends is evaluated here with the same rules as in functions.py (nothing is ever run as code).
  const FN = { sin: Math.sin, cos: Math.cos, tan: Math.tan, cot: (v) => 1 / Math.tan(v), sec: (v) => 1 / Math.cos(v), csc: (v) => 1 / Math.sin(v),
    asin: Math.asin, acos: Math.acos, atan: Math.atan, sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh, sqrt: Math.sqrt, cbrt: Math.cbrt,
    exp: Math.exp, ln: Math.log, log: Math.log10, log2: Math.log2, floor: Math.floor, ceil: Math.ceil };
  function power(a, b) {
    if (a < 0 && !Number.isInteger(b)) {
      const third = 1 / b;
      return Math.abs(third - Math.round(third)) < 1e-9 && Math.round(third) % 2 !== 0 ? -Math.pow(-a, b) : NaN;
    }
    return Math.pow(a, b);
  }
  function ev(n, x) {
    switch (n[0]) {
      case 'num': return n[1];
      case 'x': return x;
      case 'neg': return -ev(n[1], x);
      case 'abs': return Math.abs(ev(n[1], x));
      case 'fn': { const f = FN[n[1]]; return f ? f(ev(n[2], x)) : NaN; }
      default: {
        const a = ev(n[1], x), b = ev(n[2], x);
        if (n[0] === 'add') return a + b;
        if (n[0] === 'sub') return a - b;
        if (n[0] === 'mul') return a * b;
        if (n[0] === 'div') return b === 0 ? (a === 0 ? NaN : a > 0 ? Infinity : -Infinity) : a / b;
        return power(a, b);
      }
    }
  }
  const valueOf = (d, x) => (d.ast ? ev(d.ast, x) : d.a * x * x + d.b * x + d.c);
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  function niceStep(span, target) {
    const raw = span / Math.max(2, target);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  }

  // The part of the plane that is shown: the interesting points with room around them, and the curve cut where it shoots off.
  function computeView(d) {
    if (d.view) return d.view;   // a general function: Python already chose where to look
    const xs = [0];
    if (d.vertex) xs.push(d.vertex[0]);
    (d.roots || []).forEach((r) => xs.push(r));
    if (d.complex) xs.push(d.complex[0]);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const pad = Math.max((hi - lo) * 0.55, 2.4);
    const xmin = lo - pad, xmax = hi + pad;
    const g = (x) => d.a * x * x + d.b * x + d.c;
    const ys = [0, d.c];
    if (d.vertex) ys.push(d.vertex[1]);
    const keyLo = Math.min(...ys), keyHi = Math.max(...ys);
    const room = Math.max(keyHi - keyLo, (xmax - xmin) * 0.42);
    const ends = [g(xmin), g(xmax)];
    let ymin = Math.min(keyLo, Math.max(Math.min(...ends), keyLo - room * 1.15));
    let ymax = Math.max(keyHi, Math.min(Math.max(...ends), keyHi + room * 1.15));
    const ypad = Math.max((ymax - ymin) * 0.1, 0.4);
    ymin -= ypad; ymax += ypad;
    return { xmin, xmax, ymin, ymax };
  }

  // ---------- drawing ----------
  function render(ctx, w, h, S) {
    const d = S.data || data, v = S.view || view;
    const compact = Boolean(S.compact);           // a small preview: just the curve, the axes and the marked points
    const value = (x) => valueOf(d, x);
    const pad = compact ? { l: 10, r: 10, t: 10, b: 10 } : { l: 60, r: 30, t: 30, b: 42 };
    const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
    const px = (x) => pad.l + ((x - v.xmin) / (v.xmax - v.xmin)) * pw;
    const py = (y) => pad.t + (1 - (y - v.ymin) / (v.ymax - v.ymin)) * ph;
    const unx = (sx) => v.xmin + ((sx - pad.l) / pw) * (v.xmax - v.xmin);

    ctx.clearRect(0, 0, w, h);
    if (S.exporting) {
      const bg = ctx.createLinearGradient(0, 0, w, h);
      bg.addColorStop(0, '#050a18'); bg.addColorStop(1, '#0b0a1f');
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
    }
    // soft glow behind the plot
    const glow = ctx.createRadialGradient(w * 0.5, h * 0.55, 10, w * 0.5, h * 0.55, Math.max(w, h) * 0.6);
    glow.addColorStop(0, rgba(CYAN, 0.08)); glow.addColorStop(1, rgba(CYAN, 0));
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);

    ctx.save();
    ctx.beginPath(); ctx.rect(pad.l, pad.t - 8, pw + 10, ph + 16); ctx.clip();

    // grid: fine lines every step/5, stronger every step
    const sx = niceStep(v.xmax - v.xmin, pw / 95), sy = niceStep(v.ymax - v.ymin, ph / 62);
    const lines = (min, max, step, toScreen, vertical) => {
      for (let sub = 0; sub <= 1; sub++) {
        const s = sub ? step : step / 5;
        if (!sub && Math.abs(toScreen(s) - toScreen(0)) < 9) continue;
        ctx.strokeStyle = rgba(CYAN, sub ? 0.11 : 0.035);
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let k = Math.ceil(min / s); k * s <= max; k++) {
          if (!sub && k % 5 === 0) continue;
          const p = Math.round(toScreen(k * s)) + 0.5;
          vertical ? (ctx.moveTo(p, pad.t - 8), ctx.lineTo(p, h - pad.b + 8)) : (ctx.moveTo(pad.l, p), ctx.lineTo(w - pad.r + 10, p));
        }
        ctx.stroke();
      }
    };
    lines(v.xmin, v.xmax, sx, px, true);
    lines(v.ymin, v.ymax, sy, py, false);

    // axes with arrowheads
    const ax0 = px(0), ay0 = py(0);
    ctx.strokeStyle = rgba(CYAN, 0.75); ctx.lineWidth = 1.6;
    ctx.shadowColor = rgba(CYAN, 0.8); ctx.shadowBlur = 8;
    ctx.beginPath(); ctx.moveTo(pad.l, ay0); ctx.lineTo(w - pad.r + 6, ay0); ctx.moveTo(ax0, h - pad.b + 8); ctx.lineTo(ax0, pad.t - 6); ctx.stroke();
    ctx.shadowBlur = 0; ctx.fillStyle = rgba(CYAN, 0.9);
    ctx.beginPath(); ctx.moveTo(w - pad.r + 8, ay0); ctx.lineTo(w - pad.r - 4, ay0 - 4.5); ctx.lineTo(w - pad.r - 4, ay0 + 4.5); ctx.fill();
    ctx.beginPath(); ctx.moveTo(ax0, pad.t - 8); ctx.lineTo(ax0 - 4.5, pad.t + 4); ctx.lineTo(ax0 + 4.5, pad.t + 4); ctx.fill();

    // axis axis-of-symmetry (dashed) is drawn later, after the curve
    ctx.restore();

    // tick labels (not in a small preview)
    if (!compact) {
    ctx.font = '11px "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace';
    ctx.fillStyle = 'rgba(190,210,240,.62)';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let k = Math.ceil(v.xmin / sx); k * sx <= v.xmax; k++) {
      if (k === 0) continue;
      const x = px(k * sx);
      if (x < pad.l + 8 || x > w - pad.r - 8) continue;
      ctx.fillText(num(k * sx), x, Math.min(ay0 + 7, h - pad.b + 6));
      ctx.fillStyle = rgba(CYAN, 0.7); ctx.fillRect(Math.round(x), ay0 - 3, 1, 6); ctx.fillStyle = 'rgba(190,210,240,.62)';
    }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let k = Math.ceil(v.ymin / sy); k * sy <= v.ymax; k++) {
      if (k === 0) continue;
      const y = py(k * sy);
      if (y < pad.t + 6 || y > h - pad.b - 6) continue;
      ctx.fillText(num(k * sy), Math.max(ax0 - 9, pad.l - 6), y);
      ctx.fillStyle = rgba(CYAN, 0.7); ctx.fillRect(ax0 - 3, Math.round(y), 6, 1); ctx.fillStyle = 'rgba(190,210,240,.62)';
    }
    ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    ctx.fillText('0', ax0 - 7, ay0 + 6);
    ctx.font = 'italic 600 13px "Inter", system-ui, sans-serif'; ctx.fillStyle = rgba(CYAN, 0.95);
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText('x', w - pad.r + 12, ay0 - 1);
    ctx.textAlign = 'center'; ctx.fillText('y', ax0, pad.t - 16);
    }

    // the curve, clipped to the plot
    ctx.save();
    ctx.beginPath(); ctx.rect(pad.l, pad.t - 4, pw + 6, ph + 8); ctx.clip();
    const steps = Math.max(260, Math.round(pw / 1.5));
    const shown = Math.max(1, Math.round(steps * S.t));
    // The curve is cut into pieces wherever it is undefined or jumps across the frame (asymptotes, tan x, 1/x).
    const segments = [];
    let piece = [];
    let prev = null;
    for (let i = 0; i <= shown; i++) {
      const x = v.xmin + ((v.xmax - v.xmin) * i) / steps;
      const y = value(x);
      if (!Number.isFinite(y)) { if (piece.length) segments.push(piece); piece = []; prev = null; continue; }
      const sy = Math.max(-1e5, Math.min(1e5, py(y)));
      if (prev !== null && Math.abs(sy - prev) > ph * 1.6) { if (piece.length) segments.push(piece); piece = []; }
      piece.push([px(x), sy]);
      prev = sy;
    }
    if (piece.length) segments.push(piece);
    const all = segments.flat();
    if (!all.length) { ctx.restore(); return; }
    const stroke = ctx.createLinearGradient(pad.l, 0, w - pad.r, 0);
    stroke.addColorStop(0, rgba(CYAN, 1)); stroke.addColorStop(0.5, rgba(VIOLET, 1)); stroke.addColorStop(1, rgba(MAGENTA, 1));
    const fill = ctx.createLinearGradient(0, pad.t, 0, h - pad.b);
    fill.addColorStop(0, rgba(VIOLET, 0.26)); fill.addColorStop(1, rgba(CYAN, 0.02));
    const closeY = Math.min(Math.max(ay0, pad.t), h - pad.b);
    ctx.fillStyle = fill;
    segments.forEach((seg) => {
      if (seg.length < 2) return;
      ctx.beginPath();
      seg.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.lineTo(seg[seg.length - 1][0], closeY); ctx.lineTo(seg[0][0], closeY); ctx.closePath();
      ctx.fill();
    });
    const path = () => { ctx.beginPath(); segments.forEach((seg) => seg.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))); };
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    path(); ctx.strokeStyle = stroke; ctx.globalAlpha = 0.22; ctx.lineWidth = 12; ctx.stroke();
    ctx.globalAlpha = 1; path(); ctx.lineWidth = 3.2; ctx.shadowColor = rgba(VIOLET, 0.95); ctx.shadowBlur = 18; ctx.stroke();
    ctx.shadowBlur = 0; path(); ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(255,255,255,.75)'; ctx.stroke();
    const pts = all;
    if (S.t < 1) {   // the bright head that draws the curve
      const [hx, hy] = pts[pts.length - 1];
      const head = ctx.createRadialGradient(hx, hy, 0, hx, hy, 16);
      head.addColorStop(0, 'rgba(255,255,255,.95)'); head.addColorStop(0.3, rgba(CYAN, 0.6)); head.addColorStop(1, rgba(CYAN, 0));
      ctx.fillStyle = head; ctx.fillRect(hx - 16, hy - 16, 32, 32);
    }
    ctx.restore();

    // key points appear once the curve is complete
    const appear = Math.min(1, S.since / 0.6);
    const placed = [];
    const tag = (text, x, y, color, prefer) => {
      if (compact) return;
      ctx.font = '600 11.5px "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace';
      const tw = ctx.measureText(text).width + 16, th = 22;
      let bx = x - tw / 2, by = prefer === 'above' ? y - 34 : prefer === 'right' ? y - 11 : y + 14;
      if (prefer === 'right') bx = x + 14;
      bx = Math.max(pad.l - 4, Math.min(bx, w - pad.r - tw + 6));
      by = Math.max(pad.t - 4, Math.min(by, h - pad.b - th + 4));
      for (let guard = 0; guard < 8 && placed.some((r) => bx < r.x + r.w + 4 && bx + tw + 4 > r.x && by < r.y + r.h + 4 && by + th + 4 > r.y); guard++) by += th + 5;
      placed.push({ x: bx, y: by, w: tw, h: th });
      ctx.save(); ctx.globalAlpha = appear;
      ctx.fillStyle = 'rgba(6,12,26,.88)'; ctx.strokeStyle = rgba(color, 0.85); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(bx + 6, by); ctx.lineTo(bx + tw, by); ctx.lineTo(bx + tw, by + th - 6); ctx.lineTo(bx + tw - 6, by + th); ctx.lineTo(bx, by + th); ctx.lineTo(bx, by + 6); ctx.closePath();
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, bx + 8, by + th / 2 + 0.5);
      ctx.restore();
    };
    const dot = (x, y, color, seed) => {
      if (x < pad.l - 2 || x > w - pad.r + 2 || y < pad.t - 2 || y > h - pad.b + 2) return false;
      ctx.save(); ctx.globalAlpha = appear;
      const pulse = 0.5 + 0.5 * Math.sin(S.time * 2.4 + seed);
      const k = compact ? 0.4 : 1;   // smaller marks on the little preview
      ctx.strokeStyle = rgba(color, 0.55 * (1 - pulse)); ctx.lineWidth = 1.5;
      if (!compact) { ctx.beginPath(); ctx.arc(x, y, 8 + pulse * 9, 0, Math.PI * 2); ctx.stroke(); }
      ctx.shadowColor = rgba(color, 1); ctx.shadowBlur = 14;
      ctx.fillStyle = rgba(color, 1); ctx.beginPath(); ctx.arc(x, y, 5.2 * k * (0.6 + 0.4 * appear), 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0; ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x, y, 2 * k, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      return true;
    };
    if (S.since > 0) {
      if (d.kind === 'function') {
        // vertical and horizontal asymptotes
        ctx.save(); ctx.globalAlpha = appear * 0.7; ctx.setLineDash([3, 7]); ctx.strokeStyle = rgba(MAGENTA, 0.85); ctx.lineWidth = 1.2;
        ctx.beginPath();
        (d.poles || []).forEach((p) => { ctx.moveTo(px(p), pad.t); ctx.lineTo(px(p), h - pad.b); });
        (d.horizontal || []).forEach((yv) => { ctx.moveTo(pad.l, py(yv)); ctx.lineTo(w - pad.r, py(yv)); });
        ctx.stroke(); ctx.restore();
        // dots for every point of interest, labels for the most important few
        const items = [];
        const yIsRoot = (d.roots || []).some((r) => Math.abs(r) < 1e-9);
        const yIsExtremum = (d.extrema || []).some((e) => Math.abs(e.x) < 1e-9);
        if (d.yint !== null && d.yint !== undefined && !(yIsRoot && Math.abs(d.yint) < 1e-9) && !yIsExtremum) items.push({ x: 0, y: d.yint, color: MAGENTA, text: `(0, ${num(d.yint)})`, prefer: 'right', rank: 0 });
        (d.extrema || []).forEach((e) => items.push({ x: e.x, y: e.y, color: GOLD, text: `${e.type} (${num(e.x)}, ${num(e.y)})`, prefer: e.type === 'max' ? 'above' : 'below', rank: 1 + Math.abs(e.x) }));
        (d.roots || []).forEach((r) => items.push({ x: r, y: 0, color: GREEN, text: `x = ${num(r)}`, prefer: 'below', rank: 3 + Math.abs(r) }));
        const labelled = new Set(items.slice().sort((p, q) => p.rank - q.rank).slice(0, 7));
        items.forEach((it, i) => { if (dot(px(it.x), py(it.y), it.color, i) && labelled.has(it)) tag(it.text, px(it.x), py(it.y), it.color, it.prefer); });
      } else {
        if (d.vertex) {   // the axis of symmetry
          ctx.save(); ctx.globalAlpha = appear * 0.55; ctx.setLineDash([7, 6]); ctx.strokeStyle = rgba(GOLD, 0.9); ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.moveTo(px(d.vertex[0]), pad.t); ctx.lineTo(px(d.vertex[0]), h - pad.b); ctx.stroke(); ctx.restore();
        }
        (d.roots || []).forEach((r, i) => { if (dot(px(r), py(0), GREEN, i)) tag(`x = ${num(r)}`, px(r), py(0), GREEN, 'below'); });
        if (Math.abs(d.c) > 1e-9 || !(d.roots || []).some((r) => Math.abs(r) < 1e-9)) {
          if (dot(px(0), py(d.c), MAGENTA, 3)) tag(`(0, ${num(d.c)})`, px(0), py(d.c), MAGENTA, 'right');
        }
        if (d.vertex && dot(px(d.vertex[0]), py(d.vertex[1]), GOLD, 5)) {
          tag(`vertex (${num(d.vertex[0])}, ${num(d.vertex[1])})`, px(d.vertex[0]), py(d.vertex[1]), GOLD, d.opens === 'up' ? 'below' : 'above');
        }
      }
    }

    // crosshair that follows the mouse
    if (S.hover != null && S.since > 0) {
      const x = unx(S.hover), y = value(x);
      const cx = px(x), cy = py(y);
      if (Number.isFinite(y) && x >= v.xmin && x <= v.xmax && cy >= pad.t && cy <= h - pad.b) {
        ctx.save(); ctx.setLineDash([4, 5]); ctx.strokeStyle = rgba(CYAN, 0.6); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, ay0); ctx.moveTo(cx, cy); ctx.lineTo(ax0, cy); ctx.stroke(); ctx.restore();
        ctx.fillStyle = '#fff'; ctx.shadowColor = rgba(CYAN, 1); ctx.shadowBlur = 12;
        ctx.beginPath(); ctx.arc(cx, cy, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
        const text = `x = ${num(Math.round(x * 100) / 100)}   y = ${num(Math.round(y * 100) / 100)}`;
        ctx.font = '600 11.5px "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace';
        const tw = ctx.measureText(text).width + 18;
        const tx = Math.min(Math.max(cx + 14, pad.l), w - pad.r - tw), ty = Math.min(Math.max(cy - 36, pad.t), h - pad.b - 24);
        ctx.fillStyle = 'rgba(6,12,26,.92)'; ctx.strokeStyle = rgba(CYAN, 0.9);
        ctx.fillRect(tx, ty, tw, 24); ctx.strokeRect(tx + 0.5, ty + 0.5, tw - 1, 23);
        ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, tx + 9, ty + 12.5);
      }
    }

    if (S.exporting) {   // a title on the saved picture
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.font = '700 26px "Orbitron", "Inter", system-ui, sans-serif'; ctx.fillStyle = '#fff'; ctx.shadowColor = rgba(CYAN, 0.8); ctx.shadowBlur = 14;
      ctx.fillText(d.plain, 26, 16); ctx.shadowBlur = 0;
      ctx.font = '11px "JetBrains Mono", monospace'; ctx.fillStyle = 'rgba(160,190,230,.6)'; ctx.textAlign = 'right';
      ctx.fillText('JERVIS · GRAPH', w - 24, h - 16);
    }
  }

  // ---------- window ----------
  function sizeCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    return { w, h, dpr };
  }
  function loop(now) {
    const canvas = $('graphCanvas');
    const { w, h, dpr } = sizeCanvas(canvas);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const elapsed = reduced ? REVEAL_SECONDS + 1 : (now - openedAt) / 1000;
    render(ctx, w, h, { t: easeOut(Math.min(1, elapsed / REVEAL_SECONDS)), since: Math.max(0, elapsed - REVEAL_SECONDS), time: now / 1000, hover: hoverX });
    raf = requestAnimationFrame(loop);
  }

  function chips(d) {
    const list = [];
    const some = (values, format, limit) => values.slice(0, limit).map(format).join('  ,  ') + (values.length > limit ? `  +${values.length - limit}` : '');
    if (d.kind === 'function') {
      list.push(['Type', d.kindName]);
      if (d.yint !== null && d.yint !== undefined) list.push(['Y-intercept', `(0, ${num(d.yint)})`]);
      list.push(['X-intercepts', d.roots.length ? some(d.roots, (r) => num(r), 4) : 'none in view']);
      const maxima = d.extrema.filter((e) => e.type === 'max'), minima = d.extrema.filter((e) => e.type === 'min');
      if (maxima.length) list.push(['Local max', some(maxima, (e) => `(${num(e.x)}, ${num(e.y)})`, 2)]);
      if (minima.length) list.push(['Local min', some(minima, (e) => `(${num(e.x)}, ${num(e.y)})`, 2)]);
      if (d.poles.length) list.push(['Vertical asymptotes', some(d.poles, (p) => `x = ${num(p)}`, 3)]);
      if (d.horizontal.length) list.push(['Horizontal asymptote', some(d.horizontal, (y) => `y = ${num(y)}`, 2)]);
      if (d.domain) {
        const [lo, hi, loOpen, hiOpen] = d.domain;
        const ge = loOpen ? '>' : '\u2265', le = hiOpen ? '<' : '\u2264';
        list.push(['Domain', lo !== null && hi !== null ? `${num(lo)} ${loOpen ? '<' : '\u2264'} x ${le} ${num(hi)}` : lo !== null ? `x ${ge} ${num(lo)}` : `x ${le} ${num(hi)}`]);
      }
    } else if (d.kind === 'line') {
      list.push(['Slope', num(d.b)], ['Y-intercept', `(0, ${num(d.c)})`]);
      if (d.roots.length) list.push(['X-intercept', `(${num(d.roots[0])}, 0)`]);
    } else {
      list.push(['Vertex', `(${num(d.vertex[0])}, ${num(d.vertex[1])})`], ['Axis', `x = ${num(d.vertex[0])}`],
                ['Y-intercept', `(0, ${num(d.c)})`], ['Opens', d.opens === 'up' ? 'upward \u2191' : 'downward \u2193']);
      list.push(['Roots', d.roots.length ? d.roots.map((r) => `x = ${num(r)}`).join('  ,  ') : 'none (real)']);
      list.push(['Discriminant', `\u0394 = ${num(d.disc)}`]);
    }
    return list;
  }

  function present(index) {
    current = index;
    data = history[index];
    view = computeView(data);
    const d = data;
    $('graphKicker').textContent = d.kind === 'line' ? 'Straight line' : d.kind === 'function' ? `${d.kindName} function` : 'Parabola';
    const title = $('graphTitle');
    title.replaceChildren();
    try {
      if (!katex) throw new Error('no katex');
      katex.render(d.latex, title, { throwOnError: false, trust: false, strict: 'ignore' });
    } catch (error) {
      title.textContent = d.plain;
    }
    const facts = $('graphFacts');
    facts.replaceChildren();
    chips(d).forEach(([label, text]) => {
      const li = document.createElement('li');
      const a = document.createElement('span'); a.textContent = label;
      const b = document.createElement('b'); b.textContent = text;
      li.append(a, b);
      facts.append(li);
    });
    $('graphSave').textContent = 'Save image';
    const many = history.length > 1;
    $('graphNav').hidden = !many;
    $('graphCount').textContent = `${index + 1} / ${history.length}`;
    $('graphPrev').disabled = index === 0;
    $('graphNext').disabled = index === history.length - 1;
    $('graphLayer').hidden = false;
    document.body.classList.add('scene-paused');   // the orb and the background are covered: stop drawing them
    openedAt = performance.now();
    hoverX = null;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(loop);
  }

  // Draw a new graph (or, if the same one was drawn before, open that one again). Returns its place in the history.
  window.showGraph = function showGraph(d) {
    const key = JSON.stringify([d.plain, d.kind]);
    let index = history.findIndex((h) => JSON.stringify([h.plain, h.kind]) === key);
    if (index < 0) {
      history.push(d);
      if (history.length > MAX_HISTORY) history.shift();
      index = history.length - 1;
    }
    present(index);
    return index;
  };
  // Open one from the history again: "last", "prev", "next", "first", or a number.
  window.reopenGraph = function reopenGraph(which) {
    if (!history.length) return false;
    let index = current < 0 ? history.length - 1 : current;
    if (which === 'prev') index = Math.max(0, index - 1);
    else if (which === 'next') index = Math.min(history.length - 1, index + 1);
    else if (which === 'first') index = 0;
    else if (which === 'last') index = history.length - 1;
    else if (Number.isInteger(which)) index = Math.max(0, Math.min(history.length - 1, which));
    present(index);
    return true;
  };
  window.graphCount = () => history.length;
  window.graphHistoryAt = (index) => history[index];
  // A small picture of a graph for the chat: the curve and its marked points, drawn once.
  window.graphThumbnail = function graphThumbnail(canvas, d) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 170, h = canvas.clientHeight || 96;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    render(ctx, w, h, { t: 1, since: 2, time: 0, hover: null, data: d, view: computeView(d), compact: true });
  };
  window.hideGraph = function hideGraph() {
    $('graphLayer').hidden = true;
    document.body.classList.remove('scene-paused');
    cancelAnimationFrame(raf);
  };
  window.graphOpen = () => !$('graphLayer').hidden;

  document.addEventListener('DOMContentLoaded', () => {
    const canvas = $('graphCanvas');
    canvas.addEventListener('mousemove', (e) => { hoverX = e.clientX - canvas.getBoundingClientRect().left; });
    canvas.addEventListener('mouseleave', () => { hoverX = null; });
    $('graphClose').addEventListener('click', window.hideGraph);
    $('graphPrev').addEventListener('click', () => window.reopenGraph('prev'));
    $('graphNext').addEventListener('click', () => window.reopenGraph('next'));
    $('graphLayer').addEventListener('mousedown', (e) => { if (e.target === $('graphLayer')) window.hideGraph(); });
    document.addEventListener('keydown', (e) => {
      if (e.target && e.target.tagName === 'INPUT') return;
      if (e.key === 'Escape' && window.graphOpen()) { e.preventDefault(); window.hideGraph(); }
      else if (e.key === 'ArrowLeft' && window.graphOpen()) { e.preventDefault(); window.reopenGraph('prev'); }
      else if (e.key === 'ArrowRight' && window.graphOpen()) { e.preventDefault(); window.reopenGraph('next'); }
      else if (e.key.toLowerCase() === 'g' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.repeat) {   // G: show / hide the last graph
        e.preventDefault();
        window.graphOpen() ? window.hideGraph() : window.reopenGraph('last');
      }
    });
    $('graphSave').addEventListener('click', () => {
      if (!data) return;
      const out = document.createElement('canvas');
      out.width = 1800; out.height = 1100;
      const ctx = out.getContext('2d');
      render(ctx, 1800, 1100, { t: 1, since: 2, time: 0, hover: null, exporting: true });
      out.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `jervis-graph-${Date.now()}.png`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 4000);
        $('graphSave').textContent = 'Saved ✓';
      });
    });
  });
})();
