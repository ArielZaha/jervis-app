// Background: a few slow drifting particles joined by faint lines (a data network), tinted with the orb's current colour.
// Cheap on purpose: 40 particles, drawn 30 times a second at one pixel per pixel, lines drawn in three batches, and no work
// at all while the window is hidden or a full-window panel (the graph) covers it.
(function () {
  window.initBackground = function initBackground(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const COUNT = 40, LINK = 140, FRAME_MS = 33;
    const dots = [];
    let w = 800, h = 600, last = performance.now(), lastDraw = 0;

    function resize() {
      w = canvas.clientWidth || 800;
      h = canvas.clientHeight || 600;
      canvas.width = w;
      canvas.height = h;
    }
    resize();
    window.addEventListener('resize', resize);
    for (let i = 0; i < COUNT; i++) {
      dots.push({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - 0.5) * 9, vy: -3 - Math.random() * 9, r: 0.6 + Math.random() * 1.4 });
    }

    function frame(now) {
      requestAnimationFrame(frame);
      if (document.hidden || document.body.classList.contains('scene-paused') || now - lastDraw < FRAME_MS) return;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = lastDraw = now;
      const [r, g, b] = (window.__orbColor || [79, 216, 255]).map(Math.round);
      ctx.clearRect(0, 0, w, h);
      for (const d of dots) {
        if (!reduced) {
          d.x += d.vx * dt;
          d.y += d.vy * dt;
        }
        if (d.y < -10) { d.y = h + 10; d.x = Math.random() * w; }
        if (d.x < -10) d.x = w + 10;
        if (d.x > w + 10) d.x = -10;
      }
      const near = [new Path2D(), new Path2D(), new Path2D()];
      for (let i = 0; i < COUNT; i++) {
        const a = dots[i];
        for (let j = i + 1; j < COUNT; j++) {
          const c = dots[j];
          const dx = a.x - c.x, dy = a.y - c.y;
          const dist2 = dx * dx + dy * dy;
          if (dist2 < LINK * LINK) {
            const k = dist2 < LINK * LINK * 0.15 ? 0 : dist2 < LINK * LINK * 0.5 ? 1 : 2;
            near[k].moveTo(a.x, a.y); near[k].lineTo(c.x, c.y);
          }
        }
      }
      ctx.lineWidth = 1;
      [0.11, 0.07, 0.035].forEach((alpha, k) => { ctx.strokeStyle = `rgba(${r},${g},${b},${alpha})`; ctx.stroke(near[k]); });
      ctx.fillStyle = `rgba(${r},${g},${b},.5)`;
      ctx.beginPath();
      for (const d of dots) { ctx.moveTo(d.x + d.r, d.y); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); }
      ctx.fill();
    }
    requestAnimationFrame(frame);
  };
})();
