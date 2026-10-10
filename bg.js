// Background: deep space behind the whole window. Three layers of stars that drift slowly at different speeds (the far
// ones barely move), each twinkling at its own pace, a soft halo on the brightest few, and now and then a shooting
// star: a thin streak that fades in, crosses part of the sky and burns out. The stars lean a little away from the
// mouse, so the sky has depth. Tinted lightly with the orb's current colour, so it follows Jarvis's state.
// Kept cheap: one canvas, small fills, halos stamped from one prepared sprite, and no work at all while the window
// is hidden or a full-window panel (a graph, the globe) covers it. With reduced motion the sky stands still.
(function () {
  window.initBackground = function initBackground(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // far, middle, near: [share of the stars, drift in px/s, size range, brightness range, how far they lean from the mouse]
    const LAYERS = [
      { share: 0.56, drift: 1.6, size: [0.4, 0.85], glow: [0.35, 0.7], lean: 3 },
      { share: 0.30, drift: 4.2, size: [0.7, 1.25], glow: [0.55, 0.9], lean: 8 },
      { share: 0.14, drift: 8.5, size: [1.05, 1.9], glow: [0.75, 1], lean: 16 },
    ];
    const DRIFT = [-0.82, 0.57];        // which way the whole sky slides (left and gently down), as a unit vector
    const DENSITY = 1 / 2900;           // stars per square pixel of window
    const stars = [], shooting = [];
    let w = 800, h = 600, dpr = 1, last = performance.now(), nextShot = last + 2600;
    let mouseX = 0, mouseY = 0, leanX = 0, leanY = 0;

    // one soft round glow, drawn once and stamped wherever a halo is needed
    const halo = document.createElement('canvas');
    halo.width = halo.height = 64;
    (function () {
      const g = halo.getContext('2d'), fade = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      fade.addColorStop(0, 'rgba(255,255,255,1)');
      fade.addColorStop(0.18, 'rgba(255,255,255,.55)');
      fade.addColorStop(0.5, 'rgba(255,255,255,.12)');
      fade.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = fade;
      g.fillRect(0, 0, 64, 64);
    })();

    const between = (range) => range[0] + Math.random() * (range[1] - range[0]);
    function star(layer, anywhere) {
      const size = between(layer.size);
      return {
        layer, size, x: Math.random() * w, y: anywhere ? Math.random() * h : -4,
        glow: between(layer.glow), pace: 0.4 + Math.random() * 1.5, phase: Math.random() * 6.283,
        tint: Math.random() < 0.22,                       // some take the orb's colour, the rest stay starlight
        halo: layer === LAYERS[2] && Math.random() < 0.45, // the brightest ones
      };
    }
    function scatter() {
      stars.length = 0;
      const count = Math.round(Math.min(720, Math.max(180, w * h * DENSITY)));
      for (const layer of LAYERS) for (let i = 0; i < count * layer.share; i++) stars.push(star(layer, true));
    }
    function resize() {
      const width = canvas.clientWidth || 800, height = canvas.clientHeight || 600;
      const grew = Math.abs(width * height - w * h) > w * h * 0.2;
      w = width; h = height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      if (grew || !stars.length) scatter();   // a much bigger or smaller window gets a sky of its own size
    }
    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', (e) => { mouseX = e.clientX / w - 0.5; mouseY = e.clientY / h - 0.5; }, { passive: true });

    function shoot() {
      // In from beyond the top or the right edge, down and to the left, at its own angle, length and pace. It never
      // burns out on the way: it crosses the whole window and is only gone once it has left through the other side.
      const angle = Math.PI * (0.70 + Math.random() * 0.16);
      const fromTop = Math.random() < 0.6;
      shooting.push({
        x: fromTop ? w * (0.3 + Math.random() * 0.85) : w + 20, y: fromTop ? -20 : h * (Math.random() * 0.5 - 0.05),
        dx: Math.cos(angle), dy: Math.sin(angle), speed: 520 + Math.random() * 420, tail: 240 + Math.random() * 300,
        travelled: 0, width: 1.1 + Math.random() * 0.7,
      });
    }

    function frame(now) {
      requestAnimationFrame(frame);
      if (document.hidden || document.body.classList.contains('scene-paused')) { last = now; return; }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const [r, g, b] = (window.__orbColor || [79, 216, 255]).map(Math.round);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      leanX += (mouseX - leanX) * Math.min(1, dt * 2.2);   // eased, so the sky follows the mouse like something heavy
      leanY += (mouseY - leanY) * Math.min(1, dt * 2.2);

      for (const s of stars) {
        if (!reduced) {
          s.x += DRIFT[0] * s.layer.drift * dt;
          s.y += DRIFT[1] * s.layer.drift * dt;
          if (s.x < -6) s.x += w + 12; else if (s.x > w + 6) s.x -= w + 12;
          if (s.y > h + 6) s.y -= h + 12; else if (s.y < -6) s.y += h + 12;
        }
        const twinkle = reduced ? 0.85 : 0.62 + 0.38 * Math.sin(t * s.pace + s.phase);
        const x = s.x - leanX * s.layer.lean, y = s.y - leanY * s.layer.lean;
        ctx.globalAlpha = s.glow * twinkle;
        if (s.halo) ctx.drawImage(halo, x - s.size * 6, y - s.size * 6, s.size * 12, s.size * 12);
        ctx.fillStyle = s.tint ? `rgb(${r},${g},${b})` : '#eaf2ff';
        if (s.size < 0.8) ctx.fillRect(x - s.size, y - s.size, s.size * 2, s.size * 2);   // a point: no need for a circle
        else { ctx.beginPath(); ctx.arc(x, y, s.size, 0, 6.283); ctx.fill(); }
      }

      if (!reduced) {
        if (now >= nextShot) {
          shoot();
          nextShot = now + 1600 + Math.random() * 2000;      // a new one every two or three seconds: one or two in the sky at a time
          if (Math.random() < 0.15) nextShot = now + 380;    // once in a while, two in a row
        }
        for (let i = shooting.length - 1; i >= 0; i--) {
          const s = shooting[i];
          s.travelled += s.speed * dt;                                         // a steady pace, all the way across
          const headX = s.x + s.dx * s.travelled, headY = s.y + s.dy * s.travelled;
          const tail = Math.min(s.tail, s.travelled);
          const tailX = headX - s.dx * tail, tailY = headY - s.dy * tail;
          if (tailX < -30 || tailY > h + 30) { shooting.splice(i, 1); continue; }   // its whole trail has left the window
          const fade = Math.min(1, s.travelled / 90);                          // full brightness by the time it's in view
          const trail = ctx.createLinearGradient(headX, headY, tailX, tailY);
          trail.addColorStop(0, `rgba(255,255,255,${fade})`);
          trail.addColorStop(0.1, `rgba(${(r + 510) / 3 | 0},${(g + 510) / 3 | 0},${(b + 510) / 3 | 0},${0.72 * fade})`);
          trail.addColorStop(0.45, `rgba(${r},${g},${b},${0.22 * fade})`);
          trail.addColorStop(1, `rgba(${r},${g},${b},0)`);
          // the trail tapers: as wide as the head where it leaves it, down to nothing at its far end
          const px = -s.dy * s.width, py = s.dx * s.width;
          ctx.globalAlpha = 1;
          ctx.fillStyle = trail;
          ctx.beginPath();
          ctx.moveTo(headX + px, headY + py);
          ctx.lineTo(tailX, tailY);
          ctx.lineTo(headX - px, headY - py);
          ctx.closePath();
          ctx.fill();
          ctx.globalAlpha = fade;                                              // the burning head: a glow and a hard white core
          ctx.drawImage(halo, headX - 16, headY - 16, 32, 32);
          ctx.fillStyle = '#fff';
          ctx.beginPath();
          ctx.arc(headX, headY, s.width * 1.15, 0, 6.283);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    }
    requestAnimationFrame(frame);
  };
})();
