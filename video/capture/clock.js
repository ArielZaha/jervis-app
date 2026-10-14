// A hand-driven clock for recording. Loaded before the page's own scripts, it replaces the page's sense of time
// (performance.now, Date, timers, requestAnimationFrame, CSS animations and transitions) with one that only moves
// when the recorder calls __clock.step(ms). Every recorded frame is then exactly 1/30 s after the last one, however
// long the real computer took to draw it — so the footage is perfectly smooth on any machine.
(() => {
  if (window.__clock) return;
  const real = {
    raf: window.requestAnimationFrame.bind(window),
    setTimeout: window.setTimeout.bind(window),
    now: performance.now.bind(performance),
    Date,
  };
  let now = 0;                                   // virtual milliseconds since the page started
  let epoch = Number(process?.env?.CAPTURE_EPOCH) || real.Date.now();
  let nextId = 1;
  const timers = new Map();                      // id -> {at, fn, every}
  let frames = new Map();                        // id -> callback
  const started = new WeakMap();                 // Animation -> the virtual time it was first seen

  performance.now = () => now;
  class VirtualDate extends real.Date {
    constructor(...args) { if (args.length) super(...args); else super(epoch + now); }
    static now() { return epoch + now; }
  }
  window.Date = VirtualDate;

  window.setTimeout = (fn, ms = 0, ...args) => {
    const id = nextId++;
    timers.set(id, { at: now + Math.max(0, Number(ms) || 0), fn: () => (typeof fn === 'function' ? fn(...args) : 0) });
    return id;
  };
  window.setInterval = (fn, ms = 0, ...args) => {
    const id = nextId++, every = Math.max(4, Number(ms) || 0);
    timers.set(id, { at: now + every, every, fn: () => (typeof fn === 'function' ? fn(...args) : 0) });
    return id;
  };
  window.clearTimeout = window.clearInterval = (id) => { timers.delete(id); };
  window.requestAnimationFrame = (fn) => { const id = nextId++; frames.set(id, fn); return id; };
  window.cancelAnimationFrame = (id) => { frames.delete(id); };

  function runTimersUntil(target) {
    for (let guard = 0; guard < 5000; guard++) {
      let dueId = null, due = null;
      for (const [id, t] of timers) if (t.at <= target && (!due || t.at < due.at)) { dueId = id; due = t; }
      if (!due) break;
      now = Math.max(now, due.at);
      if (due.every) due.at += due.every; else timers.delete(dueId);
      try { due.fn(); } catch (e) { console.error(e); }
    }
    now = target;
  }

  function syncAnimations() {
    for (const a of document.getAnimations()) {
      try {
        if (!started.has(a)) { started.set(a, now); a.pause(); }
        const t = now - started.get(a);
        const end = a.effect ? a.effect.getComputedTiming().endTime : Infinity;
        if (Number.isFinite(end) && t >= end) a.finish(); else a.currentTime = t;
      } catch (e) { /* an animation that was removed mid-step */ }
    }
  }

  window.__clock = {
    real,
    get now() { return now; },
    // Set the page's wall clock to the real time, now. (Filming is slower than life, so the page's clock falls behind
    // the engine's; a countdown the engine just started would otherwise show more than its full time.)
    resync() { epoch = real.Date.now() - now; },
    // Move time forward by `ms`: fire the timers that fall due, then one animation frame, then place every CSS
    // animation where it would be at that moment. Resolves after the browser has really drawn the result.
    step(ms) {
      runTimersUntil(now + ms);
      const callbacks = frames;
      frames = new Map();
      for (const fn of callbacks.values()) { try { fn(now); } catch (e) { console.error(e); } }
      syncAnimations();
      return new Promise((done) => real.raf(() => real.raf(() => { syncAnimations(); real.raf(() => done(now)); })));
    },
  };
})();
