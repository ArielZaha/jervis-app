// The weather window's atmosphere: one canvas behind the content that follows the real conditions — drifting clouds,
// rain or snow (slanted by the wind), stars at night, a soft sun or moon glow, fog banks, and the odd lightning flash
// in a storm. Deliberately quiet: low opacities, few particles, nothing that competes with the numbers on top.
//
// Performance: the device pixel ratio is capped, cloud shapes are drawn once into small sprites and reused, the loop
// only runs while the window is open and visible, and with "reduce motion" a single still frame is drawn instead.
(function () {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const DPR_CAP = 1.5;
  const rand = (a, b) => a + Math.random() * (b - a);

  // Sky colours per condition, [top, bottom] of a vertical gradient (painted by CSS behind the canvas).
  const SKY = {
    day: {
      clear: ['#0b2b55', '#0a1830'], partly: ['#0d2748', '#0a162b'], cloudy: ['#17233a', '#0b1222'],
      fog: ['#1b2333', '#0d121c'], drizzle: ['#13213a', '#0a1222'], rain: ['#0f1c33', '#080f1d'],
      snow: ['#1d2b44', '#0e1626'], storm: ['#130f2a', '#07070f'],
    },
    night: {
      clear: ['#060b1f', '#03050d'], partly: ['#080d22', '#04060f'], cloudy: ['#0b1020', '#05070e'],
      fog: ['#0d111c', '#05070c'], drizzle: ['#080e1e', '#04060d'], rain: ['#070c1b', '#03050b'],
      snow: ['#0c1426', '#050810'], storm: ['#0b081c', '#040309'],
    },
  };

  function cloudSprite(w, h, puffs, shade) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    // Many overlapping, horizontally stretched puffs: reads as one soft bank of cloud, not a row of blobs.
    g.scale(1.8, 1);
    for (let i = 0; i < puffs * 2; i++) {
      const x = rand(w * 0.14, w * 0.42), y = rand(h * 0.42, h * 0.6), r = rand(h * 0.2, h * 0.4);
      const grad = g.createRadialGradient(x, y, 0, x, y, r);
      grad.addColorStop(0, `rgba(${shade},0.32)`);
      grad.addColorStop(0.55, `rgba(${shade},0.12)`);
      grad.addColorStop(1, `rgba(${shade},0)`);
      g.fillStyle = grad;
      g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
    }
    return c;
  }

  class WeatherFX {
    constructor(canvas, sky) {
      this.canvas = canvas;
      this.sky = sky;
      this.ctx = canvas.getContext('2d');
      this.state = { kind: 'cloudy', isDay: true, wind: 8, cloud: 40, windDir: 270 };
      this.running = false;
      this.last = 0;
      this.flash = 0;
      this.nextFlash = 0;
      this.w = 0; this.h = 0;
      this.drops = []; this.flakes = []; this.stars = []; this.clouds = []; this.fog = []; this.wisps = [];
      this.sprites = [cloudSprite(420, 160, 9, '220,232,250'), cloudSprite(360, 140, 7, '200,214,236'),
        cloudSprite(300, 120, 6, '235,242,255')];
      this.darkSprites = [cloudSprite(420, 160, 9, '120,134,160'), cloudSprite(360, 140, 7, '96,110,138')];
      this.resize = this.resize.bind(this);
      this.frame = this.frame.bind(this);
      new ResizeObserver(this.resize).observe(canvas);
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) cancelAnimationFrame(this.raf);
        else if (this.running) this.raf = requestAnimationFrame(this.frame);
      });
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
      this.w = Math.max(1, rect.width); this.h = Math.max(1, rect.height);
      this.canvas.width = Math.round(this.w * dpr); this.canvas.height = Math.round(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.populate();
      if (!this.running || reduced.matches) this.draw(0);
    }

    // Conditions from the forecast: kind (clear, partly, cloudy, fog, drizzle, rain, snow, storm), day or night,
    // wind speed (km/h) and direction (degrees it blows from), cloud cover (%).
    set(next) {
      this.state = { ...this.state, ...next };
      const sky = SKY[this.state.isDay ? 'day' : 'night'][this.state.kind] || SKY.day.cloudy;
      this.sky.style.setProperty('--sky-top', sky[0]);
      this.sky.style.setProperty('--sky-bottom', sky[1]);
      this.sky.dataset.kind = this.state.kind;
      this.sky.dataset.time = this.state.isDay ? 'day' : 'night';
      this.populate();
      if (!this.running || reduced.matches) this.draw(0);
    }

    populate() {
      const { kind, isDay, cloud } = this.state;
      const area = (this.w * this.h) / (1280 * 820);
      const wet = { drizzle: 70, rain: 150, storm: 210 }[kind] || 0;
      this.drops = Array.from({ length: Math.round(wet * area) }, () => this.newDrop(true));
      this.flakes = Array.from({ length: kind === 'snow' ? Math.round(110 * area) : 0 }, () => this.newFlake(true));
      const starry = !isDay && (kind === 'clear' || kind === 'partly');
      this.stars = Array.from({ length: starry ? Math.round(150 * area) : 0 }, () => ({
        x: Math.random() * this.w, y: Math.random() * this.h * 0.75, r: rand(0.4, 1.3), p: rand(0, Math.PI * 2),
        s: rand(0.4, 1.4),
      }));
      const cover = kind === 'clear' ? 0.08 : kind === 'partly' ? 0.4 : Math.max(0.55, (cloud ?? 70) / 100);
      const count = Math.round(2 + cover * 9);
      const dark = ['rain', 'storm', 'drizzle'].includes(kind) || (kind === 'cloudy' && (cloud ?? 0) > 85);
      this.clouds = Array.from({ length: count }, (_, i) => {
        const depth = i / Math.max(1, count - 1);   // 0 far .. 1 near
        const sprites = dark && Math.random() < 0.65 ? this.darkSprites : this.sprites;
        return {
          img: sprites[i % sprites.length], x: Math.random() * (this.w + 400) - 200,
          y: rand(-30, this.h * (0.18 + depth * 0.32)), scale: 0.7 + depth * 1.1, depth,
          alpha: (0.1 + cover * 0.25) * (0.55 + depth * 0.6) * (isDay ? 1 : 0.55),
        };
      });
      this.fog = kind === 'fog' ? [0, 1, 2].map((i) => ({ y: this.h * (0.45 + i * 0.17), x: rand(0, this.w), a: 0.07 + i * 0.03 })) : [];
      const windy = (this.state.wind || 0) >= 25 && !wet && kind !== 'snow';
      this.wisps = Array.from({ length: windy ? 9 : 0 }, () => this.newWisp(true));
      this.nextFlash = performance.now() + rand(2500, 6000);
    }

    // Wind blows *from* windDir; the visual drift is left/right only. Speed in px/s.
    drift() {
      const toward = ((this.state.windDir ?? 270) + 180) % 360;
      const sign = toward > 180 ? -1 : 1;
      return sign * (6 + Math.min(60, this.state.wind || 0) * 0.9);
    }

    newDrop(anywhere) {
      return { x: Math.random() * (this.w + 200) - 100, y: anywhere ? Math.random() * this.h : rand(-60, -10),
        len: rand(10, 22), v: rand(780, 1150), a: rand(0.18, 0.42) };
    }

    newFlake(anywhere) {
      return { x: Math.random() * this.w, y: anywhere ? Math.random() * this.h : rand(-20, -4), r: rand(0.9, 2.6),
        v: rand(22, 60), p: rand(0, Math.PI * 2), a: rand(0.45, 0.9) };
    }

    newWisp(anywhere) {
      return { x: anywhere ? Math.random() * this.w : (this.drift() > 0 ? -220 : this.w + 20), y: rand(this.h * 0.1, this.h * 0.9),
        len: rand(90, 220), v: rand(1.6, 2.6), a: rand(0.04, 0.09) };
    }

    start() {
      if (this.running) return;
      this.running = true;
      this.last = performance.now();
      if (reduced.matches) { this.draw(0); return; }
      this.raf = requestAnimationFrame(this.frame);
    }

    stop() {
      this.running = false;
      cancelAnimationFrame(this.raf);
    }

    frame(now) {
      if (!this.running) return;
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      this.draw(dt, now);
      this.raf = requestAnimationFrame(this.frame);
    }

    draw(dt, now = performance.now()) {
      const { ctx, w, h, state } = this;
      ctx.clearRect(0, 0, w, h);
      const t = now / 1000;
      const drift = this.drift();

      // glow: the sun (day, mostly clear) or the moon (night, mostly clear), breathing very slowly
      if (state.kind === 'clear' || state.kind === 'partly') {
        const breathe = 0.9 + Math.sin(t * 0.25) * 0.1;
        const gx = w * 0.82, gy = h * 0.06;
        const r = Math.max(w, h) * (state.isDay ? 0.55 : 0.38) * breathe;
        const g = ctx.createRadialGradient(gx, gy, 0, gx, gy, r);
        if (state.isDay) {
          g.addColorStop(0, 'rgba(255,214,140,0.30)'); g.addColorStop(0.35, 'rgba(255,170,90,0.08)'); g.addColorStop(1, 'rgba(255,170,90,0)');
        } else {
          g.addColorStop(0, 'rgba(170,185,255,0.20)'); g.addColorStop(0.4, 'rgba(120,135,220,0.05)'); g.addColorStop(1, 'rgba(120,135,220,0)');
        }
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      }

      for (const s of this.stars) {
        const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * s.s + s.p));
        ctx.globalAlpha = tw * 0.8;
        ctx.fillStyle = '#dfe8ff';
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;

      for (const c of this.clouds) {
        c.x += drift * (0.25 + c.depth * 0.75) * dt;
        const cw = c.img.width * c.scale, ch = c.img.height * c.scale;
        if (drift > 0 && c.x > w + 40) c.x = -cw - 40;
        if (drift < 0 && c.x < -cw - 40) c.x = w + 40;
        ctx.globalAlpha = c.alpha;
        ctx.drawImage(c.img, c.x, c.y, cw, ch);
      }
      ctx.globalAlpha = 1;

      for (const f of this.fog) {
        f.x += drift * 0.15 * dt;
        const g = ctx.createLinearGradient(0, f.y - 70, 0, f.y + 70);
        g.addColorStop(0, 'rgba(200,212,230,0)'); g.addColorStop(0.5, `rgba(200,212,230,${f.a})`); g.addColorStop(1, 'rgba(200,212,230,0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, f.y - 70, w, 140);
      }

      for (const s of this.wisps) {
        s.x += drift * s.v * dt;
        if ((drift > 0 && s.x > w + 20) || (drift < 0 && s.x < -s.len - 20)) Object.assign(s, this.newWisp(false));
        const g = ctx.createLinearGradient(s.x, 0, s.x + s.len, 0);
        g.addColorStop(0, 'rgba(210,230,255,0)'); g.addColorStop(0.5, `rgba(210,230,255,${s.a})`); g.addColorStop(1, 'rgba(210,230,255,0)');
        ctx.strokeStyle = g; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(s.x + s.len, s.y + Math.sin(t + s.y) * 3); ctx.stroke();
      }

      if (this.drops.length) {
        const slant = Math.max(-0.45, Math.min(0.45, drift / 160));
        ctx.lineWidth = 1;
        ctx.lineCap = 'round';
        for (const d of this.drops) {
          d.y += d.v * dt; d.x += d.v * slant * dt;
          if (d.y > h + 20) Object.assign(d, this.newDrop(false));
          ctx.strokeStyle = `rgba(170,215,255,${d.a})`;
          ctx.beginPath(); ctx.moveTo(d.x, d.y); ctx.lineTo(d.x - d.len * slant, d.y - d.len); ctx.stroke();
        }
      }

      for (const f of this.flakes) {
        f.y += f.v * dt; f.p += dt * 1.2;
        f.x += (Math.sin(f.p) * 14 + drift * 0.4) * dt;
        if (f.y > h + 8) Object.assign(f, this.newFlake(false));
        if (f.x > w + 8) f.x = -8; else if (f.x < -8) f.x = w + 8;
        ctx.globalAlpha = f.a;
        ctx.fillStyle = '#eef6ff';
        ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;

      // lightning: a rare, brief double flicker of the whole sky (no cartoon bolts)
      if (state.kind === 'storm' && dt > 0) {
        if (now > this.nextFlash) { this.flash = 1; this.nextFlash = now + rand(5000, 12000); }
        if (this.flash > 0) {
          const flicker = this.flash > 0.55 ? this.flash : this.flash * (0.5 + 0.5 * Math.sin(now / 18));
          ctx.fillStyle = `rgba(200,210,255,${0.16 * flicker})`;
          ctx.fillRect(0, 0, w, h);
          this.flash = Math.max(0, this.flash - dt * 2.4);
        }
      }
    }
  }

  window.WeatherFX = WeatherFX;
})();
