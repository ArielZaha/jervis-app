// Jervis holographic core: a wireframe sphere of points held inside three tilting gimbal rings, orbiting satellites,
// an equalizer ring and a rotating HUD dial. Each assistant state maps to a target look; the current look eases toward it.
//
// Smoothness rules this file follows:
//  - Every animated phase is INTEGRATED (phase += dt * rate) instead of computed as time * rate. When the rate
//    changes between states, an integrated phase just changes speed; time * rate would make the phase jump.
//  - Every value that changes with the state (speed, amplitude, colour, ...) eases with a time constant.
//  - Nothing is drawn from a raw waveform: the ring bars are eased too, and use squared sines (no sharp abs() corners).
//  - The mouse tilt and the voice level are eased too, so moving the pointer or speaking never makes the core jump.
// Speed rules (this runs 60 times a second, so it is kept cheap):
//  - Lines and dots are collected and drawn in a few batches (one path per brightness step), not one draw call each.
//  - The canvas is square and only as big as the core needs, at most 1.5 device pixels per pixel.
//  - The glow behind the core is CSS (see .orb-wrap::before), not a full-canvas gradient.
//  - A quality governor watches how long a frame takes. If the machine struggles it draws fewer dots and skips the fine
//    wireframe (and, as a last resort, draws every other frame), and it goes back up when there is time to spare.
(function () {
  const STATES = {
    idle:      { speed: 0.14, amp: 0.035, energy: 0.22, halo: 0.55, pulse: 0.7, scan: 0, color: [79, 216, 255] },
    sleeping:  { speed: 0.05, amp: 0.014, energy: 0.06, halo: 0.22, pulse: 0.3, scan: 0, color: [120, 135, 172] },
    listening: { speed: 0.32, amp: 0.075, energy: 0.62, halo: 0.9,  pulse: 1.6, scan: 0, color: [61, 242, 192] },
    thinking:  { speed: 1.15, amp: 0.05,  energy: 0.38, halo: 0.8,  pulse: 2.2, scan: 1, color: [165, 139, 255] },
    speaking:  { speed: 0.28, amp: 0.115, energy: 1.0,  halo: 1.0,  pulse: 3.1, scan: 0, color: [90, 169, 255] },
    muted:     { speed: 0.02, amp: 0,     energy: 0,    halo: 0.18, pulse: 0.3, scan: 0, color: [255, 107, 129] },
    generating:{ speed: 0.9,  amp: 0.06,  energy: 0.5,  halo: 0.85, pulse: 1.8, scan: 1, color: [165, 139, 255] },
  };
  const NUM_POINTS = 820;
  const NUM_BARS = 96;
  const NUM_TICKS = 120;
  const RING_STEPS = 60;
  const WIRE_STEPS = 32;
  const NUMERIC = ['speed', 'amp', 'energy', 'halo', 'pulse', 'scan'];
  const STATE_TAU = 0.6;   // seconds for a state change to settle (about 63% of the way)
  const BAR_TAU = 0.11;    // seconds for a ring bar to follow its wave
  const VOICE_ATTACK = 0.05, VOICE_RELEASE = 0.28;   // seconds: the core reacts to a voice fast and relaxes slowly
  const TILT_TAU = 0.35;   // seconds for the mouse tilt to settle
  const ACCENT2 = [255, 92, 214];   // the magenta counter-colour used sparingly on the outer rings
  const MAX_DPR = 1.5;
  // Quality levels: dots stride (1 = all), fine wireframe on/off, satellite trail length, draw every other frame.
  const QUALITY = [
    { stride: 1, wire: true,  trail: 12, half: false },
    { stride: 2, wire: true,  trail: 8,  half: false },
    { stride: 3, wire: false, trail: 4,  half: true },
  ];

  let target = STATES.idle;
  window.setOrbState = (state) => { target = STATES[state] || STATES.idle; };
  window.setOrbSpeed = () => {};
  let voiceTarget = 0;   // how loud the user is right now, 0..1 (fed from the microphone level meter in renderer.js)
  window.setOrbLevel = (level) => { voiceTarget = Math.max(0, Math.min(1, Number(level) || 0)); };
  window.__orbColor = STATES.idle.color.slice();   // read by the background so the whole scene shares the colour

  // Collects line segments by brightness so each brightness is stroked once.
  class LineBatch {
    constructor(steps) { this.steps = steps; this.lists = Array.from({ length: steps }, () => []); }
    add(alpha, maxAlpha, x1, y1, x2, y2) {
      const k = Math.max(0, Math.min(this.steps - 1, Math.floor((alpha / maxAlpha) * this.steps)));
      this.lists[k].push(x1, y1, x2, y2);
    }
    flush(ctx, style, maxAlpha, width) {
      ctx.lineWidth = width;
      for (let k = 0; k < this.steps; k++) {
        const list = this.lists[k];
        if (!list.length) continue;
        ctx.strokeStyle = style(maxAlpha * (k + 0.5) / this.steps);
        ctx.beginPath();
        for (let i = 0; i < list.length; i += 4) { ctx.moveTo(list[i], list[i + 1]); ctx.lineTo(list[i + 2], list[i + 3]); }
        ctx.stroke();
        list.length = 0;
      }
    }
  }

  window.initOrb = function initOrb(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const motion = reduced ? 0.3 : 1;

    // Fibonacci sphere: evenly spread points on a unit sphere.
    const pts = [];
    for (let i = 0; i < NUM_POINTS; i++) {
      const y = 1 - (i / (NUM_POINTS - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const a = i * 2.399963229728653;
      pts.push({ x: Math.cos(a) * r, y, z: Math.sin(a) * r });
    }

    const cur = { ...STATES.idle, color: [...STATES.idle.color] };
    const bars = new Float32Array(NUM_BARS).fill(0.025);
    // Integrated phases (see the note at the top of the file).
    const phase = { pulse: 0, noise: 0, bars: 0, arc: 0, scan: 0, rotY: 0, rotX: 0, ring1: 0, ring2: 0, ring3: 0, orbit: 0, dial: 0 };
    const tilt = { x: 0, y: 0, tx: 0, ty: 0 };
    const dotBuckets = Array.from({ length: 8 }, () => []);   // x, y, radius triples by brightness
    const lineBatch = new LineBatch(6);
    let voice = 0;
    let size = 400, R = 100, dpr = 1;
    let last = performance.now();
    let quality = 0, avgMs = 4, slow = 0, fast = 0, frameCount = 0;
    const parent = canvas.parentElement;

    window.addEventListener('mousemove', (e) => {
      tilt.tx = (e.clientY / window.innerHeight - 0.5) * 0.5;
      tilt.ty = (e.clientX / window.innerWidth - 0.5) * 0.7;
    });
    document.addEventListener('mouseleave', () => { tilt.tx = 0; tilt.ty = 0; });

    function resize() {
      dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
      size = Math.max(200, Math.floor(Math.min(parent.clientWidth || 400, parent.clientHeight || 400)));
      canvas.style.width = canvas.style.height = `${size}px`;
      const px = Math.round(size * dpr);
      if (canvas.width !== px || canvas.height !== px) {   // resizing clears the canvas, so only when it really changed
        canvas.width = px;
        canvas.height = px;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      R = size * 0.245;
    }

    function govern(ms) {
      avgMs += (ms - avgMs) * 0.08;
      if (avgMs > 9 && quality < QUALITY.length - 1) { if (++slow > 40) { quality++; slow = 0; avgMs = 5; } } else slow = 0;
      if (avgMs < 3.5 && quality > 0) { if (++fast > 600) { quality--; fast = 0; avgMs = 6; } } else fast = 0;
    }

    function frame(now) {
      if (document.hidden || document.body.classList.contains('scene-paused')) {   // nothing to see: do no work
        last = now;
        requestAnimationFrame(frame);
        return;
      }
      const q = QUALITY[quality];
      if (q.half && (frameCount++ & 1)) { requestAnimationFrame(frame); return; }   // every other frame on a slow machine
      const started = performance.now();
      // A long hitch (tab switch, heavy frame) is treated as a normal-length frame so the motion never leaps.
      const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
      last = now;

      const ease = 1 - Math.exp(-dt / STATE_TAU);
      NUMERIC.forEach((k) => { cur[k] += (target[k] - cur[k]) * ease; });
      for (let i = 0; i < 3; i++) cur.color[i] += (target.color[i] - cur.color[i]) * ease;
      window.__orbColor = cur.color;
      const [cr, cg, cb] = cur.color.map(Math.round);
      const rgba = (a) => `rgba(${cr},${cg},${cb},${a.toFixed(3)})`;
      const rgba2 = (a) => `rgba(${ACCENT2[0]},${ACCENT2[1]},${ACCENT2[2]},${a.toFixed(3)})`;

      const tiltEase = 1 - Math.exp(-dt / TILT_TAU);
      tilt.x += (tilt.tx - tilt.x) * tiltEase;
      tilt.y += (tilt.ty - tilt.y) * tiltEase;

      // The voice level is eased (quick up, slow down) and only ever changes the SPEED of the integrated phases, so
      // the core spins up and winds down smoothly instead of jerking with every syllable.
      voice += (voiceTarget - voice) * (1 - Math.exp(-dt / (voiceTarget > voice ? VOICE_ATTACK : VOICE_RELEASE)));
      const lively = 0.5 + 0.5 * cur.energy;
      phase.pulse += dt * (cur.pulse + voice * 2.0) * motion;
      phase.noise += dt * (0.55 + 0.5 * cur.energy) * motion;
      phase.bars += dt * 1.6 * motion;
      phase.arc += dt * (0.4 + cur.scan * 3) * motion;
      phase.scan += dt * 4 * motion;
      phase.rotY += dt * (cur.speed + voice * 2.6) * motion;   // the sphere spins faster the louder you speak
      phase.ring1 += dt * (0.22 + 0.5 * cur.speed + voice * 1.4) * motion;
      phase.ring2 += dt * (0.17 + 0.4 * cur.speed + voice * 1.1) * motion;
      phase.ring3 += dt * (0.12 + 0.35 * cur.speed + voice * 0.9) * motion;
      phase.orbit += dt * (0.35 + 0.9 * cur.speed + voice * 2.2) * motion;
      phase.dial += dt * (0.05 + 0.1 * lively + cur.scan * 0.5 + voice * 0.35) * motion;
      phase.rotX = 0.35 + 0.1 * Math.sin(phase.noise * 0.2);

      const w = size, h = size;
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h / 2;
      ctx.globalCompositeOperation = 'lighter';

      // ----- HUD dial: fine tick marks that turn slowly (three strokes: major, medium, minor), with a pointer on top -----
      const dialR = R * 1.9;
      const glowK = 0.5 + 0.5 * cur.halo;
      const tickPaths = [new Path2D(), new Path2D(), new Path2D()];
      for (let i = 0; i < NUM_TICKS; i++) {
        const ang = (i / NUM_TICKS) * Math.PI * 2 + phase.dial;
        const kind = i % 10 === 0 ? 0 : i % 5 === 0 ? 1 : 2;
        const len = kind === 0 ? R * 0.12 : kind === 1 ? R * 0.07 : R * 0.035;
        const c = Math.cos(ang), s = Math.sin(ang);
        tickPaths[kind].moveTo(cx + c * dialR, cy + s * dialR);
        tickPaths[kind].lineTo(cx + c * (dialR - len), cy + s * (dialR - len));
      }
      [[0, 0.55, 1.6], [1, 0.32, 1], [2, 0.16, 1]].forEach(([kind, a, width]) => {
        ctx.lineWidth = width; ctx.strokeStyle = rgba(a * glowK); ctx.stroke(tickPaths[kind]);
      });
      ctx.fillStyle = rgba(0.85);
      ctx.beginPath();
      ctx.moveTo(cx, cy - dialR - R * 0.02);
      ctx.lineTo(cx - R * 0.045, cy - dialR - R * 0.13);
      ctx.lineTo(cx + R * 0.045, cy - dialR - R * 0.13);
      ctx.closePath();
      ctx.fill();

      // ----- Equalizer ring: each bar follows its own wave, eased so it can never flicker (five brightness steps) -----
      const ringR = R * 1.34;
      const barFollow = 1 - Math.exp(-dt / BAR_TAU);
      ctx.lineCap = 'round';
      const barMax = 0.18 + 0.5 * cur.halo * 1.4;
      for (let i = 0; i < NUM_BARS; i++) {
        const a = Math.sin(i * 0.33 + phase.pulse * 2);
        const b = Math.sin(i * 0.11 - phase.bars);
        const wave = a * a * b * b;                       // smooth, 0..1, no sharp corners
        const goal = 0.025 + 0.24 * cur.energy * wave + 0.3 * voice * (0.35 + 0.65 * wave);
        bars[i] += (goal - bars[i]) * barFollow;
        const ang = (i / NUM_BARS) * Math.PI * 2 - Math.PI / 2;
        const c = Math.cos(ang), s = Math.sin(ang);
        const len = R * bars[i];
        lineBatch.add(0.18 + 0.5 * cur.halo * (0.4 + bars[i] / 0.265), barMax, cx + c * ringR, cy + s * ringR, cx + c * (ringR + len), cy + s * (ringR + len));
      }
      lineBatch.flush(ctx, rgba, barMax, Math.max(1.5, R * 0.02));

      // ----- Guide rings: a thin circle plus two dashed arcs that turn in opposite directions -----
      ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(0.12 + 0.1 * cur.halo);
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.18, 0, Math.PI * 2); ctx.stroke();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = rgba(0.3 * cur.halo + cur.scan * 0.3);
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.66, phase.arc, phase.arc + Math.PI * (0.35 + cur.scan * 0.4));
      ctx.stroke();
      ctx.strokeStyle = rgba2(0.22 * cur.halo + cur.scan * 0.18);
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.74, -phase.arc * 0.7 + 2, -phase.arc * 0.7 + 2 + Math.PI * (0.22 + cur.scan * 0.3));
      ctx.stroke();

      // ----- 3D setup shared by the sphere, the gimbal rings and the satellites -----
      const breath = 1 + 0.03 * Math.sin(phase.pulse) + 0.05 * voice;
      const env = Math.min(1.4, cur.energy + voice * 0.8) * (0.55 + 0.45 * Math.sin(phase.pulse * 2.3) * Math.sin(phase.pulse * 1.1 + 1.3));
      const gY = phase.rotY + tilt.y, gX = phase.rotX + tilt.x;
      const cY = Math.cos(gY), sY = Math.sin(gY);
      const cX = Math.cos(gX), sX = Math.sin(gX);
      const fov = R * 4;
      // Project a point in the core's own space to the screen: returns [x, y, depth 0..1, scale].
      const proj = [0, 0, 0, 0];
      const project = (x, y, z, radius) => {
        const x1 = x * cY + z * sY;
        const z1 = -x * sY + z * cY;
        const y1 = y * cX - z1 * sX;
        const z2 = y * sX + z1 * cX;
        const scale = fov / (fov - z2);
        proj[0] = cx + x1 * scale; proj[1] = cy + y1 * scale; proj[2] = (z2 / radius + 1) / 2; proj[3] = scale;
        return proj;
      };
      const nt = phase.noise;
      const wobble = (px, py, pz) => Math.sin(px * 3.2 + nt * 1.4) * Math.sin(py * 3.6 - nt * 1.1) * Math.sin(pz * 3.0 + nt * 0.9);

      // ----- Wireframe: meridians and parallels wrapped around the sphere, faint, so it reads as a hologram -----
      if (q.wire) {
        const wireR = R * breath;
        const wireLines = (count, build) => {
          for (let l = 0; l < count; l++) {
            let px0 = 0, py0 = 0, pd0 = 0, have = false;
            for (let s = 0; s <= WIRE_STEPS; s++) {
              const [ux, uy, uz] = build(l, s / WIRE_STEPS);
              const rr = wireR * (1 + cur.amp * wobble(ux, uy, uz) * (0.6 + env));
              const p = project(ux * rr, uy * rr, uz * rr, rr);
              if (have) lineBatch.add(0.035 + 0.14 * ((p[2] + pd0) / 2) ** 2, 0.175, px0, py0, p[0], p[1]);
              px0 = p[0]; py0 = p[1]; pd0 = p[2]; have = true;
            }
          }
        };
        wireLines(6, (l, t) => {            // meridians
          const a = (l / 6) * Math.PI, b = t * Math.PI * 2;
          return [Math.cos(b) * Math.cos(a), Math.sin(b), Math.cos(b) * Math.sin(a)];
        });
        wireLines(5, (l, t) => {            // parallels
          const lat = ((l + 1) / 6) * Math.PI - Math.PI / 2, b = t * Math.PI * 2;
          return [Math.cos(lat) * Math.cos(b), Math.sin(lat), Math.cos(lat) * Math.sin(b)];
        });
        lineBatch.flush(ctx, rgba, 0.175, 1);
      }

      // ----- Sphere of points, drawn in eight brightness batches -----
      const dotBase = Math.max(0.7, R / 95);
      const scanning = cur.scan > 0.01;
      for (let i = 0; i < NUM_POINTS; i += q.stride) {
        const p = pts[i];
        const n = wobble(p.x, p.y, p.z);
        const rr = R * breath * (1 + cur.amp * n * (0.6 + env));
        const s = project(p.x * rr, p.y * rr, p.z * rr, rr);
        const depth = s[2];
        let a = 0.12 + 0.88 * depth * depth;
        if (scanning) a += cur.scan * 1.4 * Math.pow(Math.max(0, Math.sin(p.y * 2.2 + phase.scan)), 6);
        const k = Math.min(7, Math.floor(Math.min(1, a) * 8));
        dotBuckets[k].push(s[0], s[1], (0.5 + 1.3 * depth) * dotBase * s[3] * (q.stride > 1 ? 1.25 : 1));
      }
      for (let k = 0; k < 8; k++) {
        const list = dotBuckets[k];
        if (!list.length) continue;
        ctx.fillStyle = rgba((k + 0.5) / 8);
        ctx.beginPath();
        for (let i = 0; i < list.length; i += 3) { ctx.moveTo(list[i] + list[i + 2], list[i + 1]); ctx.arc(list[i], list[i + 1], list[i + 2], 0, Math.PI * 2); }
        ctx.fill();
        list.length = 0;
      }

      // ----- Gimbal rings: three great circles that tilt and turn on their own axes -----
      const ringDefs = [
        { r: 1.32, a: phase.ring1, b: 0.4, tint: 0, width: 1.6 },
        { r: 1.46, a: phase.ring2 + 1.6, b: 1.9 + phase.ring2 * 0.3, tint: 1, width: 1.2 },
        { r: 1.58, a: -phase.ring3 + 0.6, b: 3.3 - phase.ring3 * 0.25, tint: 0, width: 1 },
      ];
      const ringPoint = (def, theta) => {
        const px = Math.cos(theta) * def.r * R, py = Math.sin(theta) * def.r * R;
        const y1 = py * Math.cos(def.a), z1 = py * Math.sin(def.a);          // tilt around X
        return [px * Math.cos(def.b) + z1 * Math.sin(def.b), y1, -px * Math.sin(def.b) + z1 * Math.cos(def.b)];  // turn around Y
      };
      ringDefs.forEach((def) => {
        let px0 = 0, py0 = 0, pd0 = 0, have = false;
        for (let s = 0; s <= RING_STEPS; s++) {
          const [x, y, z] = ringPoint(def, (s / RING_STEPS) * Math.PI * 2);
          const p = project(x, y, z, def.r * R);
          if (have) lineBatch.add((0.05 + 0.5 * ((p[2] + pd0) / 2) ** 1.6) * (0.55 + 0.45 * cur.halo), 0.55, px0, py0, p[0], p[1]);
          px0 = p[0]; py0 = p[1]; pd0 = p[2]; have = true;
        }
        lineBatch.flush(ctx, def.tint ? (a) => rgba2(a * 0.8) : rgba, 0.55, def.width);
      });

      // ----- Satellites: bright nodes riding the rings, each leaving a short fading trail -----
      [[0, 0.0, 0], [1, 2.1, 1], [2, 4.2, 0]].forEach(([index, offset, tint]) => {
        const def = ringDefs[index];
        const speed = index === 1 ? -1.15 : index === 2 ? 0.8 : 1;
        for (let t = 0; t < q.trail; t++) {
          const theta = offset + speed * phase.orbit - t * 0.055 * (14 / q.trail) * Math.sign(speed);
          const [x, y, z] = ringPoint(def, theta);
          const p = project(x, y, z, def.r * R);
          const fade = 1 - t / q.trail;
          const dotSize = (t === 0 ? 3.2 : 2.4 * fade) * Math.max(0.7, R / 110) * p[3] * (0.9 + 0.4 * p[2]);
          const alpha = fade * fade * (0.35 + 0.65 * p[2]);
          ctx.fillStyle = tint ? rgba2(alpha) : rgba(alpha);
          ctx.beginPath(); ctx.arc(p[0], p[1], dotSize, 0, Math.PI * 2); ctx.fill();
        }
      });

      // ----- Scan ring: a horizontal slice that sweeps up and down the sphere while thinking -----
      if (cur.scan > 0.02) {
        const sy = Math.sin(phase.scan * 0.5) * 0.92;
        const ring = Math.sqrt(1 - sy * sy);
        let px0 = 0, py0 = 0, pd0 = 0, have = false;
        for (let s = 0; s <= 40; s++) {
          const b = (s / 40) * Math.PI * 2;
          const rr = R * breath * 1.04;
          const p = project(Math.cos(b) * ring * rr, sy * rr, Math.sin(b) * ring * rr, rr);
          if (have) lineBatch.add(cur.scan * (0.1 + 0.6 * ((p[2] + pd0) / 2)), 0.7, px0, py0, p[0], p[1]);
          px0 = p[0]; py0 = p[1]; pd0 = p[2]; have = true;
        }
        lineBatch.flush(ctx, rgba, 0.7, 1.6);
      }

      // ----- Bright core -----
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.95);
      core.addColorStop(0, rgba(Math.min(1, 0.36 * cur.halo + 0.08 * env + 0.25 * voice)));
      core.addColorStop(0.35, rgba(0.1 * cur.halo));
      core.addColorStop(1, rgba(0));
      ctx.fillStyle = core;
      ctx.fillRect(cx - R, cy - R, R * 2, R * 2);

      ctx.globalCompositeOperation = 'source-over';
      govern(performance.now() - started);
      requestAnimationFrame(frame);
    }

    resize();
    if (window.ResizeObserver) new ResizeObserver(resize).observe(parent);
    else window.addEventListener('resize', resize);
    requestAnimationFrame(frame);
    window.__orbQuality = () => ({ level: quality, ms: avgMs });
  };
})();
