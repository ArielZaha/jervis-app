// Jervis planet viewer: any body Jervis is asked about ("tell me about Mars", "show me Saturn") as a real, lit, spinning
// 3D model with a starfield behind it — the same raster-texturing technique as the Earth-distance globe (earth.js),
// generalised to one body at a time, with no pins or arc, and an optional ring system for Saturn.
(function () {
  const $ = (id) => document.getElementById(id);
  const CYAN = [79, 216, 255];
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const REVEAL_SECONDS = 1.1;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // A plain, textureless look for a body with no imagery yet (Earth reuses the real distance-globe window instead;
  // Pluto has no bundled texture), coloured roughly to how that kind of body actually looks.
  const PLAIN_COLOR = { star: [255, 214, 130], rock: [176, 158, 140], gas: [214, 189, 152], ice: [162, 196, 214], earth: [90, 140, 200] };

  let texture = null, textureKey = null, ringAlpha = null;
  function loadImage(url, onReady) {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      const tctx = c.getContext('2d', { willReadFrequently: true });
      tctx.drawImage(img, 0, 0);
      onReady({ data: tctx.getImageData(0, 0, c.width, c.height).data, w: c.width, h: c.height });
    };
    img.onerror = () => console.warn(`Planet imagery failed to load (${url}).`);
    img.src = url;
  }
  loadImage('vendor/planets/2k_saturn_ring_alpha.png', (t) => { ringAlpha = t; });

  function bilinear(map, u, v, channels) {
    const { data, w, h } = map;
    const fx = ((u % 1) + 1) % 1 * w - 0.5, fy = Math.max(0, Math.min(h - 1, v * h - 0.5));
    const x0 = Math.floor(fx), y0 = Math.floor(fy);
    const tx = fx - x0, ty = fy - y0;
    const x1 = (x0 + 1) % w, y1 = Math.min(h - 1, y0 + 1);
    const xw = ((x0 % w) + w) % w;
    const at = (x, y) => (y * w + x) * 4;
    const a = at(xw, y0), b = at(x1, y0), c = at(xw, y1), d = at(x1, y1);
    const out = new Array(channels);
    for (let i = 0; i < channels; i++) {
      out[i] = (data[a + i] * (1 - tx) + data[b + i] * tx) * (1 - ty) + (data[c + i] * (1 - tx) + data[d + i] * tx) * ty;
    }
    return out;
  }
  const texel = (u, v) => bilinear(texture, u, v, 3);

  const RES_LEVELS = [460, 340, 240, 170];
  const MAX_RES = 900;
  const PAINT_INTERVAL = 42;
  const PAINT_INTERVAL_LIVE = 15;   // while dragging or zooming, keep the texture right under the cursor
  let resLevel = 0, avgMs = 4, lastPaintAt = -1;
  let lastInteractAt = -1e9;
  const raster = document.createElement('canvas');
  const rasterCtx = raster.getContext('2d');
  let rasterImage = null, rasterSize = 0;
  let stars = null, starsFor = '';

  function drawStars(ctx, w, h) {
    const key = `${w}x${h}`;
    if (starsFor !== key) {
      starsFor = key;
      const count = Math.round((w * h) / 2600);
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w, y: Math.random() * h, r: Math.random() < 0.85 ? Math.random() * 0.7 + 0.3 : Math.random() * 1.3 + 0.9,
        a: Math.random() * 0.5 + 0.35, phase: Math.random() * Math.PI * 2,
      }));
    }
    ctx.fillStyle = '#fff';
    stars.forEach((s) => {
      ctx.globalAlpha = s.a * (0.75 + 0.25 * Math.sin(s.phase));
      ctx.fillRect(s.x, s.y, s.r, s.r);
    });
    ctx.globalAlpha = 1;
  }

  const LIGHT = normalize([0.4, 0.5, 0.85]);
  function normalize(v) {
    const n = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / n, v[1] / n, v[2] / n];
  }
  const SAT = 1.15, CONTRAST = 1.05;

  function paintBody(ctx, cx, cy, R, cLon, sLon, cLat, sLat, compact, exportRes, nowMs, zoom, live) {
    // Zoomed in, the same body covers more screen space, so it needs more raster samples to stay just as sharp.
    const RES = compact ? 96 : exportRes ? 1000 : Math.min(MAX_RES, Math.round(RES_LEVELS[resLevel] * Math.max(1, Math.sqrt(zoom))));
    const plain = !texture;
    const interval = live ? PAINT_INTERVAL_LIVE : PAINT_INTERVAL;
    const stale = !plain && rasterSize === RES && !compact && !exportRes && nowMs - lastPaintAt < interval;
    if (stale) {
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(raster, cx - R, cy - R, R * 2, R * 2);
      return;
    }
    const started = compact ? 0 : performance.now();
    if (rasterSize !== RES) {
      raster.width = raster.height = RES;
      rasterImage = rasterCtx.createImageData(RES, RES);
      rasterSize = RES;
    }
    const buf = rasterImage.data;
    const edgePx = 1.3 / RES;
    const flat = PLAIN_COLOR[data.colorKind] || PLAIN_COLOR.rock;
    for (let j = 0; j < RES; j++) {
      const ny = (j + 0.5) / RES * 2 - 1;
      for (let i = 0; i < RES; i++) {
        const idx = (j * RES + i) * 4;
        const nx = (i + 0.5) / RES * 2 - 1;
        const dist = Math.hypot(nx, ny);
        if (dist > 1 + edgePx) { buf[idx + 3] = 0; continue; }
        const py = -ny;
        const pz = Math.sqrt(Math.max(0, 1 - nx * nx - py * py));
        let r, g, b;
        if (plain) {
          [r, g, b] = flat;
        } else {
          const py1 = py * cLat + pz * sLat;
          const pz1 = -py * sLat + pz * cLat;
          const x = nx * cLon + pz1 * sLon;
          const z = -nx * sLon + pz1 * cLon;
          const y = py1;
          const lon = Math.atan2(z, x) + Math.PI / 2;
          const lat = Math.asin(Math.max(-1, Math.min(1, y)));
          [r, g, b] = texel((lon + Math.PI) / (2 * Math.PI), (Math.PI / 2 - lat) / Math.PI);
          const lum = 0.299 * r + 0.587 * g + 0.114 * b;
          r = lum + (r - lum) * SAT; g = lum + (g - lum) * SAT; b = lum + (b - lum) * SAT;
          r = (r - 128) * CONTRAST + 128; g = (g - 128) * CONTRAST + 128; b = (b - 128) * CONTRAST + 128;
        }
        const dot = nx * LIGHT[0] + py * LIGHT[1] + pz * LIGHT[2];
        const t = Math.max(0, Math.min(1, (dot + 0.35) / 0.6));
        const light = 0.58 + 0.62 * t * t * (3 - 2 * t);
        const alpha = dist > 1 ? Math.max(0, (1 + edgePx - dist) / edgePx) : 1;
        buf[idx] = r * light; buf[idx + 1] = g * light; buf[idx + 2] = b * light; buf[idx + 3] = 255 * alpha;
      }
    }
    rasterCtx.putImageData(rasterImage, 0, 0);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(raster, cx - R, cy - R, R * 2, R * 2);
    if (!compact && !exportRes) {
      lastPaintAt = nowMs;
      const ms = performance.now() - started;
      avgMs += (ms - avgMs) * 0.15;
      const budget = live ? PAINT_INTERVAL_LIVE : PAINT_INTERVAL;
      if (avgMs > budget * 0.7 && resLevel < RES_LEVELS.length - 1) { resLevel++; avgMs = budget * 0.35; }
      else if (avgMs < budget * 0.2 && resLevel > 0) { resLevel--; avgMs = budget * 0.35; }
    }
  }

  // Saturn's rings: a flat disc in the body's equatorial plane, split into the half behind the sphere and the half in
  // front of it, so the sphere itself still occludes the far side correctly.
  function drawRings(ctx, cx, cy, R, cLon, sLon, cLat, sLat, front) {
    if (!ringAlpha) return;
    const project = (x, y, z) => {
      let px = x * cLon - z * sLon, pz = x * sLon + z * cLon;
      const py = y * cLat - pz * sLat;
      pz = y * sLat + pz * cLat;
      return [cx + px * R, cy - py * R, pz];
    };
    const steps = 96;
    for (let ring = 0; ring < 40; ring++) {
      const r0 = 1.24 + (ring / 40) * 1.1, r1 = 1.24 + ((ring + 1) / 40) * 1.1;
      const rMid = (r0 + r1) / 2;
      const profile = bilinear(ringAlpha, Math.min(0.995, (rMid - 1.24) / 1.1), 0.5, 4);   // radius runs along the image's width
      if (profile[3] < 4) continue;
      ctx.beginPath();
      let has = false;
      for (let s = 0; s <= steps; s++) {
        const a = (s / steps) * Math.PI * 2;
        const x = Math.cos(a) * rMid, z = Math.sin(a) * rMid;   // a point on the ring, in the equatorial (y = 0) plane
        const q = project(x, 0, z);
        const onFront = q[2] >= -0.001;
        if (onFront !== front) { has = false; continue; }
        if (!has) { ctx.moveTo(q[0], q[1]); has = true; } else ctx.lineTo(q[0], q[1]);
      }
      ctx.strokeStyle = `rgba(214,196,168,${(profile[3] / 255) * 0.8})`;
      ctx.lineWidth = Math.max(1, (r1 - r0) * R);
      ctx.stroke();
    }
  }

  let data = null, raf = 0, openedAt = 0;
  const history = [];
  let current = -1;
  const MAX_HISTORY = 40;

  function present(index) {
    current = index;
    data = history[index];
    if (data.texture !== textureKey) {
      texture = null; textureKey = data.texture;
      if (data.texture) loadImage(`vendor/planets/${data.texture}`, (t) => { if (textureKey === data.texture) texture = t; });
    }
    $('planetKicker').textContent = data.bodyKind.charAt(0).toUpperCase() + data.bodyKind.slice(1);
    $('planetTitle').textContent = data.name;
    $('planetFacts').replaceChildren();
    (data.chips || []).forEach(([label, text]) => {
      const li = document.createElement('li');
      const s = document.createElement('span'); s.textContent = label;
      const b = document.createElement('b'); b.textContent = text;
      li.append(s, b);
      $('planetFacts').append(li);
    });
    const many = history.length > 1;
    $('planetNav').hidden = !many;
    $('planetCount').textContent = `${index + 1} / ${history.length}`;
    $('planetPrev').disabled = index === 0;
    $('planetNext').disabled = index === history.length - 1;
    $('planetLayer').hidden = false;
    document.body.classList.add('scene-paused');
    openedAt = performance.now();
    userLon = 0; userLat = 0.1; zoom = 1; autoSpin = 0;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }

  window.showPlanet = function showPlanet(d) {
    let index = history.findIndex((h) => h.key === d.key);
    if (index < 0) {
      history.push(d);
      if (history.length > MAX_HISTORY) history.shift();
      index = history.length - 1;
    } else {
      history[index] = d;
    }
    present(index);
    return index;
  };
  window.reopenPlanet = function reopenPlanet(which) {
    if (!history.length) return false;
    let index = current < 0 ? history.length - 1 : current;
    if (which === 'prev') index = Math.max(0, index - 1);
    else if (which === 'next') index = Math.min(history.length - 1, index + 1);
    else if (which === 'first') index = 0;
    else if (which === 'last') index = history.length - 1;
    present(index);
    return true;
  };
  window.hidePlanet = function hidePlanet() {
    $('planetLayer').hidden = true;
    document.body.classList.remove('scene-paused');
    cancelAnimationFrame(raf);
  };
  window.planetOpen = () => !$('planetLayer').hidden;
  window.planetThumbnail = function planetThumbnail(canvas, d) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 170, h = canvas.clientHeight || 96;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const savedTex = texture, savedKey = textureKey;
    if (d.texture) {
      texture = null;
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
        const tctx = c.getContext('2d'); tctx.drawImage(img, 0, 0);
        const tex = { data: tctx.getImageData(0, 0, c.width, c.height).data, w: c.width, h: c.height };
        const cur = texture; texture = tex;
        renderThumb(ctx, w, h, d);
        texture = cur;
      };
      img.src = `vendor/planets/${d.texture}`;
    } else {
      renderThumb(ctx, w, h, d);
    }
    function renderThumb() { render(ctx, w, h, { t: 1, since: 1, spinLon: 0.6, lat: 0.15, zoom: 1, compact: true, planetData: d }); }
    texture = savedTex; textureKey = savedKey;
  };

  let userLon = 0, userLat = 0.1, zoom = 1;
  let autoSpin = 0;
  let dragging = false, lastX = 0, lastY = 0;

  function frame(now) {
    if (document.hidden) { raf = requestAnimationFrame(frame); return; }
    const canvas = $('planetCanvas');
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 400, h = canvas.clientHeight || 400;
    const px = Math.round(w * dpr), py = Math.round(h * dpr);
    if (canvas.width !== px || canvas.height !== py) { canvas.width = px; canvas.height = py; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const elapsed = reduced ? REVEAL_SECONDS + 1 : (now - openedAt) / 1000;
    render(ctx, w, h, {
      t: Math.min(1, elapsed / REVEAL_SECONDS), since: Math.max(0, elapsed - REVEAL_SECONDS),
      spinLon: userLon + autoSpin, lat: userLat, zoom, time: now / 1000,
      live: dragging || now - lastInteractAt < 500,
    });
    if (!dragging && !reduced) autoSpin += 0.0016;
    raf = requestAnimationFrame(frame);
  }

  function render(ctx, w, h, S) {
    const d = S.planetData || data;
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * (S.compact ? 0.4 : 0.32) * S.zoom;
    const cLon = Math.cos(S.spinLon), sLon = Math.sin(S.spinLon), cLat = Math.cos(S.lat), sLat = Math.sin(S.lat);
    if (!S.compact) drawStars(ctx, w, h);
    ctx.globalCompositeOperation = 'lighter';
    if (!S.compact) {
      const halo = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 2.1);
      halo.addColorStop(0, rgba(CYAN, 0.14)); halo.addColorStop(1, rgba(CYAN, 0));
      ctx.fillStyle = halo; ctx.fillRect(0, 0, w, h);
    }
    ctx.globalCompositeOperation = 'source-over';
    if (d.rings) drawRings(ctx, cx, cy, R, cLon, sLon, cLat, sLat, false);
    paintBody(ctx, cx, cy, R, cLon, sLon, cLat, sLat, S.compact, S.exportRes, (S.time || 0) * 1000, S.zoom, Boolean(S.live));
    if (d.rings) drawRings(ctx, cx, cy, R, cLon, sLon, cLat, sLat, true);
    ctx.globalCompositeOperation = 'lighter';
    const rim = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R * 1.03);
    rim.addColorStop(0, rgba(CYAN, 0)); rim.addColorStop(1, rgba(CYAN, 0.35));
    ctx.fillStyle = rim;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.03, 0, Math.PI * 2); ctx.fill();
    if (!S.compact) {
      const lmag = Math.hypot(LIGHT[0], LIGHT[1]);
      const gx = cx + (LIGHT[0] / lmag) * R * 0.9, gy = cy + (-LIGHT[1] / lmag) * R * 0.9;
      const glow = ctx.createRadialGradient(gx, gy, 0, gx, gy, R * 0.75);
      glow.addColorStop(0, 'rgba(255,255,255,.65)'); glow.addColorStop(0.35, rgba(CYAN, 0.22)); glow.addColorStop(1, rgba(CYAN, 0));
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(gx, gy, R * 0.75, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  document.addEventListener('DOMContentLoaded', () => {
    const canvas = $('planetCanvas');
    const onDown = (x, y) => { dragging = true; lastX = x; lastY = y; };
    const onMove = (x, y) => {
      if (!dragging) return;
      userLon += (x - lastX) * 0.0055;
      userLat = Math.max(-1.3, Math.min(1.3, userLat + (y - lastY) * 0.0055));
      lastX = x; lastY = y;
      lastInteractAt = performance.now();
    };
    const onUp = () => { dragging = false; lastInteractAt = performance.now(); };
    canvas.addEventListener('mousedown', (e) => onDown(e.clientX, e.clientY));
    window.addEventListener('mousemove', (e) => onMove(e.clientX, e.clientY));
    window.addEventListener('mouseup', onUp);
    canvas.addEventListener('touchstart', (e) => onDown(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
    canvas.addEventListener('touchmove', (e) => onMove(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
    canvas.addEventListener('touchend', onUp);
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      zoom = Math.max(0.55, Math.min(9, zoom - e.deltaY * 0.0015));
      lastInteractAt = performance.now();
    }, { passive: false });

    $('planetClose').addEventListener('click', window.hidePlanet);
    $('planetPrev').addEventListener('click', () => window.reopenPlanet('prev'));
    $('planetNext').addEventListener('click', () => window.reopenPlanet('next'));
    $('planetLayer').addEventListener('mousedown', (e) => { if (e.target === $('planetLayer')) window.hidePlanet(); });
    document.addEventListener('keydown', (e) => {
      if (e.target && e.target.tagName === 'INPUT') return;
      if (e.key === 'Escape' && window.planetOpen()) { e.preventDefault(); window.hidePlanet(); }
      else if (e.key === 'ArrowLeft' && window.planetOpen()) { e.preventDefault(); window.reopenPlanet('prev'); }
      else if (e.key === 'ArrowRight' && window.planetOpen()) { e.preventDefault(); window.reopenPlanet('next'); }
      else if (e.key.toLowerCase() === 'p' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.repeat) {
        e.preventDefault();
        window.planetOpen() ? window.hidePlanet() : window.reopenPlanet('last');
      }
    });
    $('planetSave').addEventListener('click', () => {
      if (!data) return;
      const out = document.createElement('canvas');
      out.width = 1400; out.height = 1400;
      render(out.getContext('2d'), 1400, 1400, { t: 1, since: 2, spinLon: userLon, lat: userLat, zoom, time: 0, exportRes: true });
      out.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `jervis-${data.key}-${Date.now()}.png`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 4000);
        $('planetSave').textContent = 'Saved ✓';
      });
    });
  });
})();
