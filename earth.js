// Jervis 3D globe: a lit, rotating wireframe Earth with two glowing pins and an arc between them following the great
// circle (the shortest path on a sphere). Drag to spin it, scroll to zoom. Every globe drawn is kept, exactly like the
// graph window (graph.js), so "show me the globe again" can bring back any of them.
(function () {
  const $ = (id) => document.getElementById(id);
  const CYAN = [79, 216, 255], MAGENTA = [255, 92, 214], GOLD = [255, 209, 102], GREEN = [61, 242, 192];
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const REVEAL_SECONDS = 1.4;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- the real Earth, as a texture (bundled locally, so this works offline) ----------
  // The sphere is raster-painted with real geography instead of a wireframe: for every pixel of the visible disc we
  // work out which point of the globe faces us (an orthographic projection, inverted), turn that into a latitude and
  // longitude, and sample that point from an equirectangular map of the Earth. This runs at a modest fixed resolution
  // (see RES_LEVELS) and is then scaled up smoothly onto the real canvas, which keeps it fast without WebGL.
  let texture = null;    // {data, w, h} the coloured map (continents, oceans, ice)
  let clouds = null;     // {data, w, h} a white cloud layer with its own transparency
  function loadImage(url, onReady) {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      const tctx = c.getContext('2d', { willReadFrequently: true });
      tctx.drawImage(img, 0, 0);
      onReady({ data: tctx.getImageData(0, 0, c.width, c.height).data, w: c.width, h: c.height });
    };
    img.onerror = () => console.warn(`Earth imagery failed to load (${url}); the globe will look plainer without it.`);
    img.src = url;
  }
  loadImage('vendor/earth/earth_atmos_2048.jpg', (t) => { texture = t; });
  loadImage('vendor/earth/earth_clouds_1024.png', (t) => { clouds = t; });

  // The raster (the expensive part) is only recomputed about 24 times a second — plenty for a slowly turning globe —
  // while the canvas is still redrawn at the display's full rate, so dragging and the arc/pins stay perfectly smooth.
  // That roughly doubles how much detail fits in the same time budget, which is what actually fixes a blocky look.
  const RES_LEVELS = [460, 340, 240, 170];   // raster resolution tiers; the governor drops a tier if frames get slow
  const MAX_RES = 900;                       // zooming in asks for more raster samples (see paintEarth); capped here
  const PAINT_INTERVAL = 42;                 // how stale the texture may be while the view is settled (imperceptible)
  const PAINT_INTERVAL_LIVE = 15;            // ...but while dragging or zooming, redraw essentially every frame
  let resLevel = 0, avgMs = 4, lastPaintAt = -1;
  let lastInteractAt = -1e9;
  const raster = document.createElement('canvas');
  const rasterCtx = raster.getContext('2d');
  let rasterImage = null, rasterSize = 0;
  let stars = null, starsFor = '';   // a fixed starfield behind the globe, generated once per canvas size

  function bilinear(map, u, v, channels) {
    // A bilinear sample of an equirectangular map at fraction (u, v), both wrapped/clamped to the image.
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
  function cloudAlpha(u, v) {
    // A cheap NEAREST sample (clouds are soft-edged already, and this is blended and then scaled up, so no bilinear
    // interpolation is needed here — it would cost as much as the whole colour sample again for no visible gain).
    const { data, w, h } = clouds;
    const x = Math.floor(((u % 1) + 1) % 1 * w), y = Math.max(0, Math.min(h - 1, Math.floor(v * h)));
    return data[(y * w + x) * 4 + 3];
  }

  function sphereXYZ(lat, lon) {
    const c = Math.cos(lat);
    return [c * Math.cos(lon), Math.sin(lat), c * Math.sin(lon)];
  }
  function latLonToXYZ(latDeg, lonDeg) {
    return sphereXYZ((latDeg * Math.PI) / 180, (lonDeg * Math.PI) / 180 - Math.PI / 2);
  }
  // A point a fraction `t` (0..1) along the great-circle arc from p1 to p2 (slerp on the unit sphere).
  function slerp(p1, p2, t) {
    const dot = Math.max(-1, Math.min(1, p1[0] * p2[0] + p1[1] * p2[1] + p1[2] * p2[2]));
    const theta = Math.acos(dot);
    if (theta < 1e-6) return p1;
    const s = Math.sin(theta);
    const a = Math.sin((1 - t) * theta) / s, b = Math.sin(t * theta) / s;
    return [p1[0] * a + p2[0] * b, p1[1] * a + p2[1] * b, p1[2] * a + p2[2] * b];
  }

  let data = null, raf = 0, openedAt = 0;
  const history = [];
  let current = -1;
  const MAX_HISTORY = 40;

  function loadPayload(d) {
    data = d;
    d._a = latLonToXYZ(d.a.lat, d.a.lon);
    d._b = latLonToXYZ(d.b.lat, d.b.lon);
    // Face the camera at the midpoint of the arc, so both pins are visible when it opens.
    const mid = slerp(d._a, d._b, 0.5);
    // The camera's longitude spin must be offset by 90 degrees from the point's own longitude: rotating the globe by
    // spinLon leaves the resulting x on screen at cos(lat)*cos(lon+spinLon), and only spinLon = 90deg - lon zeroes it
    // out (drag it a quarter turn to bring the meridian to the "front", the second rotation then centers the latitude).
    d._targetLon = Math.PI / 2 - Math.atan2(mid[2], mid[0]);
    d._targetLat = Math.asin(Math.max(-1, Math.min(1, mid[1])));
  }

  function present(index) {
    current = index;
    loadPayload(history[index]);
    const d = data;
    $('earthTitle').textContent = `${d.a.name} → ${d.b.name}`;
    $('earthSub').textContent = `${d.km.toLocaleString()} km  ·  ${d.miles.toLocaleString()} mi  ·  heading ${d.bearing}°`;
    const facts = $('earthFacts');
    facts.replaceChildren();
    [['From', d.a.name], ['To', d.b.name], ['Distance', `${d.km.toLocaleString()} km (${d.miles.toLocaleString()} mi)`], ['Heading', `${d.bearing}°`]]
      .forEach(([label, text]) => {
        const li = document.createElement('li');
        const s = document.createElement('span'); s.textContent = label;
        const b = document.createElement('b'); b.textContent = text;
        li.append(s, b);
        facts.append(li);
      });
    const many = history.length > 1;
    $('earthNav').hidden = !many;
    $('earthCount').textContent = `${index + 1} / ${history.length}`;
    $('earthPrev').disabled = index === 0;
    $('earthNext').disabled = index === history.length - 1;
    $('earthLayer').hidden = false;
    document.body.classList.add('scene-paused');
    openedAt = performance.now();
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }

  window.showGlobe = function showGlobe(d) {
    const key = `${d.a.name}|${d.b.name}`;
    let index = history.findIndex((h) => `${h.a.name}|${h.b.name}` === key);
    if (index < 0) {
      history.push(d);
      if (history.length > MAX_HISTORY) history.shift();
      index = history.length - 1;
    }
    present(index);
    return index;
  };
  window.reopenGlobe = function reopenGlobe(which) {
    if (!history.length) return false;
    let index = current < 0 ? history.length - 1 : current;
    if (which === 'prev') index = Math.max(0, index - 1);
    else if (which === 'next') index = Math.min(history.length - 1, index + 1);
    else if (which === 'first') index = 0;
    else if (which === 'last') index = history.length - 1;
    present(index);
    return true;
  };
  window.hideGlobe = function hideGlobe() {
    $('earthLayer').hidden = true;
    document.body.classList.remove('scene-paused');
    cancelAnimationFrame(raf);
  };
  window.globeOpen = () => !$('earthLayer').hidden;
  window.globeCount = () => history.length;
  window.__earthDebug = () => ({ resLevel, avgMs, RES: RES_LEVELS[resLevel] });
  window.globeThumbnail = function globeThumbnail(canvas, d) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 170, h = canvas.clientHeight || 96;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    loadPayload(d);
    render(ctx, w, h, { t: 1, since: 1, spinLon: data._targetLon, lat: data._targetLat, zoom: 1, compact: true });
  };

  let userLon = 0, userLat = 0.15, zoom = 1;
  let autoSpin = 0;                                  // eases to 0 once the user has touched the globe
  let dragging = false, lastX = 0, lastY = 0;

  function frame(now) {
    if (document.hidden) { raf = requestAnimationFrame(frame); return; }
    const canvas = $('earthCanvas');
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 400, h = canvas.clientHeight || 400;
    const px = Math.round(w * dpr), py = Math.round(h * dpr);
    if (canvas.width !== px || canvas.height !== py) { canvas.width = px; canvas.height = py; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const elapsed = reduced ? REVEAL_SECONDS + 1 : (now - openedAt) / 1000;
    const settle = 1 - Math.exp(-elapsed / 0.5);
    const targetLon = data._targetLon + autoSpin;
    render(ctx, w, h, {
      t: Math.min(1, elapsed / REVEAL_SECONDS),
      since: Math.max(0, elapsed - REVEAL_SECONDS),
      spinLon: userLon + (targetLon - userLon) * (dragging ? 1 : settle),
      lat: userLat + (data._targetLat - userLat) * (dragging ? 1 : settle),
      zoom,
      time: now / 1000,
      cloudDrift: (now / 1000) * 0.006,
      live: dragging || now - lastInteractAt < 500,   // dragging or just zoomed: keep the texture right under the cursor
    });
    if (!dragging && !reduced) autoSpin += 0.0022;
    raf = requestAnimationFrame(frame);
  }

  // The fixed "sun": lighting is a simple dot product against the camera-facing normal, so it stays put on screen
  // regardless of how the globe itself is spun (like a desk lamp on the prop), and never lets the far side go black.
  // It sits mostly toward the camera and to the upper right, so almost the whole visible disc reads as sunlit, the
  // way a "hero shot" of Earth from space usually looks, with a soft bloom where it grazes the limb (see glow()).
  const LIGHT = normalize([0.4, 0.5, 0.85]);
  function normalize(v) {
    const n = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / n, v[1] / n, v[2] / n];
  }

  const SAT = 1.22, CONTRAST = 1.06;   // a punchier, more vivid grade than the source photo on its own

  // A starfield behind the globe: generated once per canvas size, then just redrawn (cheap: a few hundred dots).
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

  // Paints the real Earth into the raster canvas at the current quality tier, then scales it onto the visible canvas.
  // The raster itself is only recomputed every PAINT_INTERVAL ms (see the comment by RES_LEVELS); in between, the
  // previous raster is simply redrawn, which costs almost nothing and looks identical for a slowly turning globe.
  function paintEarth(ctx, cx, cy, R, cLon, sLon, cLat, sLat, compact, S_export, driftRad, nowMs, zoom, live) {
    // Zoomed in, the same sphere covers far more screen space, so it needs more raster samples to look just as sharp
    // (not more DETAIL than the source imagery has — a satellite photo only shows so much — but no blockiness either).
    const RES = compact ? 96 : S_export ? 1000 : Math.min(MAX_RES, Math.round(RES_LEVELS[resLevel] * Math.max(1, Math.sqrt(zoom))));
    const interval = live ? PAINT_INTERVAL_LIVE : PAINT_INTERVAL;
    const stale = rasterSize === RES && !compact && !S_export && nowMs - lastPaintAt < interval;
    if (stale) {
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(raster, cx - R, cy - R, R * 2, R * 2);
      return;
    }
    const started = compact ? 0 : performance.now();
    if (rasterSize !== RES) {
      raster.width = raster.height = RES;
      rasterImage = rasterCtx.createImageData(RES, RES);
      rasterSize = RES;
    }
    const haveClouds = Boolean(clouds);
    const buf = rasterImage.data;
    const edgePx = 1.3 / RES;   // how many pixels wide the antialiased edge of the disc is
    for (let j = 0; j < RES; j++) {
      const ny = (j + 0.5) / RES * 2 - 1;
      for (let i = 0; i < RES; i++) {
        const idx = (j * RES + i) * 4;
        const nx = (i + 0.5) / RES * 2 - 1;
        const dist = Math.hypot(nx, ny);
        if (dist > 1 + edgePx) { buf[idx + 3] = 0; continue; }
        const py = -ny;
        const pz = Math.sqrt(Math.max(0, 1 - nx * nx - py * py));
        // Undo the two view rotations (see project()) to find which point of the Earth's own surface this is.
        const py1 = py * cLat + pz * sLat;
        const pz1 = -py * sLat + pz * cLat;
        const x = nx * cLon + pz1 * sLon;
        const z = -nx * sLon + pz1 * cLon;
        const y = py1;
        const lon = Math.atan2(z, x) + Math.PI / 2;
        const lat = Math.asin(Math.max(-1, Math.min(1, y)));
        const u = (lon + Math.PI) / (2 * Math.PI), v = (Math.PI / 2 - lat) / Math.PI;
        let [r, g, b] = texel(u, v);

        // A richer, more saturated grade than the flat satellite photo, so oceans read as blue and land has real colour.
        const lum = 0.299 * r + 0.587 * g + 0.114 * b;
        r = lum + (r - lum) * SAT; g = lum + (g - lum) * SAT; b = lum + (b - lum) * SAT;

        if (haveClouds) {   // a bright white cloud layer, drifting slowly east on its own
          const a = (cloudAlpha(u + driftRad / (2 * Math.PI), v) / 255) * 0.95;
          if (a > 0) { r = r * (1 - a) + 255 * a; g = g * (1 - a) + 255 * a; b = b * (1 - a) + 255 * a; }
        }

        // A soft, bright terminator (smoothstep, not a hard cutoff): with the light sitting mostly toward the camera,
        // almost the whole visible disc reads as sunlit, the way a "hero shot" of Earth from space usually looks.
        const dot = nx * LIGHT[0] + py * LIGHT[1] + pz * LIGHT[2];
        const t = Math.max(0, Math.min(1, (dot + 0.35) / 0.6));
        const light = 0.6 + 0.62 * t * t * (3 - 2 * t);
        const isOcean = b > r * 1.08 && b > 40;
        const glint = isOcean && dot > 0.5 ? (dot - 0.5) * 0.8 : 0;

        r = (r - 128) * CONTRAST + 128; g = (g - 128) * CONTRAST + 128; b = (b - 128) * CONTRAST + 128;
        const alpha = dist > 1 ? Math.max(0, (1 + edgePx - dist) / edgePx) : 1;
        buf[idx] = r * light + glint * 255; buf[idx + 1] = g * light + glint * 255; buf[idx + 2] = b * light + glint * 200;
        buf[idx + 3] = 255 * alpha;
      }
    }
    rasterCtx.putImageData(rasterImage, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(raster, cx - R, cy - R, R * 2, R * 2);
    if (!compact && !S_export) {
      lastPaintAt = nowMs;
      const ms = performance.now() - started;
      avgMs += (ms - avgMs) * 0.15;
      // The budget is PAINT_INTERVAL ms normally, but PAINT_INTERVAL_LIVE while actively dragging or zooming, so the
      // governor asks for less detail on a slower machine right when responsiveness (not sharpness) matters most.
      const budget = live ? PAINT_INTERVAL_LIVE : PAINT_INTERVAL;
      if (avgMs > budget * 0.7 && resLevel < RES_LEVELS.length - 1) { resLevel++; avgMs = budget * 0.35; }
      else if (avgMs < budget * 0.2 && resLevel > 0) { resLevel--; avgMs = budget * 0.35; }
    }
  }

  function render(ctx, w, h, S) {
    const d = data;
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * (S.compact ? 0.42 : 0.36) * S.zoom;
    const cLon = Math.cos(S.spinLon), sLon = Math.sin(S.spinLon), cLat = Math.cos(S.lat), sLat = Math.sin(S.lat);
    // Rotate a unit-sphere point by the current longitude/latitude and project it (simple orthographic projection).
    function project([x, y, z]) {
      let px = x * cLon - z * sLon, pz = x * sLon + z * cLon;
      const py = y * cLat - pz * sLat;
      pz = y * sLat + pz * cLat;
      return [cx + px * R, cy - py * R, pz];   // pz > 0 = facing the camera
    }
    if (!S.compact) drawStars(ctx, w, h);
    ctx.globalCompositeOperation = 'lighter';
    // Soft halo behind the sphere.
    if (!S.compact) {
      const halo = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 2.1);
      halo.addColorStop(0, rgba(CYAN, 0.16)); halo.addColorStop(1, rgba(CYAN, 0));
      ctx.fillStyle = halo; ctx.fillRect(0, 0, w, h);
    }
    ctx.globalCompositeOperation = 'source-over';

    if (texture) {
      paintEarth(ctx, cx, cy, R, cLon, sLon, cLat, sLat, S.compact, S.exportRes, S.cloudDrift || 0, (S.time || 0) * 1000, S.zoom, Boolean(S.live));
    } else {
      // The map image hasn't finished loading yet (should only ever be a frame or two): a plain sphere in the meantime.
      const body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.35, R * 0.1, cx, cy, R * 1.05);
      body.addColorStop(0, 'rgba(20,32,54,.9)'); body.addColorStop(0.75, 'rgba(8,14,26,.95)'); body.addColorStop(1, 'rgba(4,7,14,.97)');
      ctx.fillStyle = body;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    }
    // A rim of atmosphere around the edge, and a soft sunlit bloom where the (fixed) light grazes the limb.
    ctx.globalCompositeOperation = 'lighter';
    const rim = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R * 1.04);
    rim.addColorStop(0, rgba(CYAN, 0)); rim.addColorStop(1, rgba(CYAN, 0.5));
    ctx.fillStyle = rim;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.04, 0, Math.PI * 2); ctx.fill();
    if (!S.compact) {
      const lmag = Math.hypot(LIGHT[0], LIGHT[1]);
      const gx = cx + (LIGHT[0] / lmag) * R * 0.95, gy = cy + (-LIGHT[1] / lmag) * R * 0.95;
      const glow = ctx.createRadialGradient(gx, gy, 0, gx, gy, R * 0.85);
      glow.addColorStop(0, 'rgba(255,255,255,.75)'); glow.addColorStop(0.35, rgba(CYAN, 0.28)); glow.addColorStop(1, rgba(CYAN, 0));
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(gx, gy, R * 0.85, 0, Math.PI * 2); ctx.fill();
    }

    // The great-circle arc, drawn progressively while the globe first opens.
    const arcSteps = 90;
    const shown = S.compact ? arcSteps : Math.max(1, Math.round(arcSteps * Math.min(1, S.t * 1.3)));
    let prevP = null, prevVisible = false;
    const grad = [];
    for (let i = 0; i <= shown; i++) {
      const pt = slerp(d._a, d._b, i / arcSteps);
      const raised = pt.map((v) => v * 1.012);   // just above the surface, so it doesn't z-fight with the sphere
      const p = project(raised);
      const visible = p[2] > -0.05;
      if (prevP && prevVisible && visible) grad.push([prevP, p, i / arcSteps]);
      prevP = p; prevVisible = visible;
    }
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    if (grad.length) {
      const g0 = grad[0][0], g1 = grad[grad.length - 1][1];
      const lg = ctx.createLinearGradient(g0[0], g0[1], g1[0], g1[1]);
      lg.addColorStop(0, rgba(MAGENTA, 1)); lg.addColorStop(1, rgba(CYAN, 1));
      ctx.strokeStyle = lg;
      ctx.lineWidth = Math.max(1.4, R * (S.compact ? 0.02 : 0.014));
      ctx.beginPath();
      grad.forEach(([a, b]) => { ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); });
      ctx.stroke();
      if (!S.compact) {
        ctx.lineWidth *= 3; ctx.globalAlpha = 0.18;
        ctx.beginPath();
        grad.forEach(([a, b]) => { ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); });
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }

    // Pins: a bright node with a pulsing ring at each city, hidden (dimmed) when on the far side.
    const dotBase = Math.max(1.6, R * (S.compact ? 0.045 : 0.028));
    [[d._a, MAGENTA], [d._b, GOLD]].forEach(([pt, color]) => {
      const p = project(pt.map((v) => v * 1.015));
      const behind = p[2] < 0;
      const alpha = behind ? 0.15 : 1;
      if (!S.compact && !behind) {
        const pulse = 0.5 + 0.5 * Math.sin(S.time || 0);
        ctx.strokeStyle = rgba(color, 0.5 * (1 - pulse));
        ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(p[0], p[1], dotBase * (1.6 + pulse * 1.6), 0, Math.PI * 2); ctx.stroke();
      }
      ctx.fillStyle = rgba(color, alpha);
      ctx.beginPath(); ctx.arc(p[0], p[1], dotBase, 0, Math.PI * 2); ctx.fill();
      if (!behind) {
        ctx.fillStyle = 'rgba(255,255,255,.9)';
        ctx.beginPath(); ctx.arc(p[0], p[1], dotBase * 0.4, 0, Math.PI * 2); ctx.fill();
      }
    });
    ctx.globalCompositeOperation = 'source-over';
  }

  document.addEventListener('DOMContentLoaded', () => {
    const canvas = $('earthCanvas');
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
    // Once the user drags, stop auto-rotating so it stays where they left it.
    canvas.addEventListener('mousedown', () => { autoSpin = 0; });

    $('earthClose').addEventListener('click', window.hideGlobe);
    $('earthPrev').addEventListener('click', () => window.reopenGlobe('prev'));
    $('earthNext').addEventListener('click', () => window.reopenGlobe('next'));
    $('earthLayer').addEventListener('mousedown', (e) => { if (e.target === $('earthLayer')) window.hideGlobe(); });
    document.addEventListener('keydown', (e) => {
      if (e.target && e.target.tagName === 'INPUT') return;
      if (e.key === 'Escape' && window.globeOpen()) { e.preventDefault(); window.hideGlobe(); }
      else if (e.key === 'ArrowLeft' && window.globeOpen()) { e.preventDefault(); window.reopenGlobe('prev'); }
      else if (e.key === 'ArrowRight' && window.globeOpen()) { e.preventDefault(); window.reopenGlobe('next'); }
      else if (e.key.toLowerCase() === 'e' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.repeat) {
        e.preventDefault();
        window.globeOpen() ? window.hideGlobe() : window.reopenGlobe('last');
      }
    });
    $('earthSave').addEventListener('click', () => {
      if (!data) return;
      const out = document.createElement('canvas');
      out.width = 1400; out.height = 1400;
      render(out.getContext('2d'), 1400, 1400, { t: 1, since: 2, spinLon: userLon + (data._targetLon - userLon), lat: userLat + (data._targetLat - userLat), zoom, time: 0, exportRes: true });
      out.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `jervis-globe-${Date.now()}.png`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 4000);
        $('earthSave').textContent = 'Saved ✓';
      });
    });
  });
})();
