// Jarvis 3D globe: the real Earth (NASA imagery, lit by the Sun where it actually is right now), with a cinematic
// flight along the great-circle route between two places: a camera "director" frames the departure, follows the
// plane, pulls wide on long journeys and settles on the arrival. Also route comparisons (several planes at the same
// speed, so the longer route visibly takes longer), places within a radius, and day/night views.
// Every globe shown is kept, so "show me the globe again" can bring any of them back. Drag to look around, scroll
// to zoom; Space pauses, R replays, S skips to the end.
(function () {
  const $ = (id) => document.getElementById(id);
  const MAGENTA = [255, 92, 214], GOLD = [255, 209, 102];
  const ROUTE_COLORS = [[94, 214, 255], [255, 196, 107], [184, 150, 255], [120, 235, 180]];
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const EARTH_KM = 6371;

  // ---------- imagery ----------
  // On the GPU (sphere_gl.js): NASA's Blue Marble at 5400 x 2700, its cloud cover and the Black Marble city lights,
  // shaded per screen pixel. The CPU painter below (smaller maps) is only the fallback where WebGL 2 is missing.
  const IMAGERY = { day: 'vendor/earth/blue_marble_5400.jpg', clouds: 'vendor/earth/clouds_2048.jpg', night: 'vendor/earth/night_lights_3600.jpg' };
  let texture = null;   // CPU fallback map: {data, w, h}
  let gpu;              // undefined: not tried yet; null: unavailable
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
  function gpuRenderer() {
    if (gpu === undefined) {
      gpu = window.createSphereRenderer ? window.createSphereRenderer() : null;
      if (gpu) Object.values(IMAGERY).forEach((url) => gpu.texture(url));
      else loadImage('vendor/earth/earth_atmos_2048.jpg', (t) => { texture = t; });
    }
    return gpu;
  }

  // ---------- vectors on the unit sphere ----------
  // World axes: y is the north pole; longitude 0 lies along -z. (The view's two rotations, project(), and the GPU
  // shader all share this convention.)
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm3 = (v) => { const n = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / n, v[1] / n, v[2] / n]; };
  function latLonToXYZ(latDeg, lonDeg) {
    const lat = (latDeg * Math.PI) / 180, lon = (lonDeg * Math.PI) / 180 - Math.PI / 2, c = Math.cos(lat);
    return [c * Math.cos(lon), Math.sin(lat), c * Math.sin(lon)];
  }
  function slerp(p1, p2, t) {   // along the great circle: crossing the date line or a pole needs no special case
    const d = Math.max(-1, Math.min(1, dot3(p1, p2)));
    const theta = Math.acos(d);
    if (theta < 1e-6) return p1.slice();
    if (Math.PI - theta < 1e-4) {   // exactly opposite points: any great circle works; pick one deterministically
      const axis = norm3(Math.abs(p1[1]) < 0.9 ? [-p1[2], 0, p1[0]] : [1, 0, 0]);
      const perp = norm3([p1[1] * axis[2] - p1[2] * axis[1], p1[2] * axis[0] - p1[0] * axis[2], p1[0] * axis[1] - p1[1] * axis[0]]);
      const a = t * Math.PI;
      return [p1[0] * Math.cos(a) + perp[0] * Math.sin(a), p1[1] * Math.cos(a) + perp[1] * Math.sin(a), p1[2] * Math.cos(a) + perp[2] * Math.sin(a)];
    }
    const s = Math.sin(theta), a = Math.sin((1 - t) * theta) / s, b = Math.sin(t * theta) / s;
    return [p1[0] * a + p2[0] * b, p1[1] * a + p2[1] * b, p1[2] * a + p2[2] * b];
  }
  const angleBetween = (a, b) => Math.acos(Math.max(-1, Math.min(1, dot3(a, b))));
  // A point `km` from the centre on `bearing` (radians, 0 = north, clockwise): for the radius circle.
  function destination(c, bearing, km) {
    const north = norm3([-c[1] * c[0], 1 - c[1] * c[1], -c[1] * c[2]]);
    const east = [north[1] * c[2] - north[2] * c[1], north[2] * c[0] - north[0] * c[2], north[0] * c[1] - north[1] * c[0]];
    const tang = [north[0] * Math.cos(bearing) - east[0] * Math.sin(bearing), north[1] * Math.cos(bearing) - east[1] * Math.sin(bearing),
                  north[2] * Math.cos(bearing) - east[2] * Math.sin(bearing)];
    const d = km / EARTH_KM;
    return norm3([c[0] * Math.cos(d) + tang[0] * Math.sin(d), c[1] * Math.cos(d) + tang[1] * Math.sin(d), c[2] * Math.cos(d) + tang[2] * Math.sin(d)]);
  }
  // The view (spin + tilt) that puts direction `c` at the centre of the screen, and back.
  const viewOf = (c) => ({ spinLon: Math.PI / 2 - Math.atan2(c[2], c[0]), lat: Math.asin(Math.max(-1, Math.min(1, c[1]))) });
  function centerOf(spinLon, lat) {
    const a = Math.PI / 2 - spinLon;
    return [Math.cos(lat) * Math.cos(a), Math.sin(lat), Math.cos(lat) * Math.sin(a)];
  }
  // How far to zoom so an arc of `theta` radians around the centre fills a comfortable part of the view.
  // (Up to 24x for a short hop: closer than that, the ~7 km-per-pixel satellite imagery only turns to blur.)
  const fitZoom = (theta) => Math.max(1, Math.min(24, 0.78 / Math.max(0.02, Math.sin(Math.min(Math.PI / 2, theta / 2 + 0.012)))));
  const ease = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
  const easeFlight = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * t * (t * (t * 6 - 15) + 10));   // gentle take-off and landing
  const lerpZoom = (a, b, t) => Math.exp(Math.log(a) + (Math.log(b) - Math.log(a)) * t);   // even in feel at every scale

  // ---------- what's being shown ----------
  let data = null, raf = 0;
  const history = [];
  let current = -1;
  const MAX_HISTORY = 40;

  function prepare(d) {
    const routes = d.routes ? d.routes : (d.a && d.b ? [d] : []);   // older globes (saved chat chips) had one route, top level
    d._routes = routes.map((r, i) => {
      const a = latLonToXYZ(r.a.lat, r.a.lon), b = latLonToXYZ(r.b.lat, r.b.lon);
      const theta = angleBetween(a, b);
      return { ...r, _a: a, _b: b, theta, color: d.mode === 'compare' ? ROUTE_COLORS[i % ROUTE_COLORS.length] : ROUTE_COLORS[0],
               lift: Math.min(0.075, 0.012 + theta * 0.028) };
    });
    d._sun = d.sun ? latLonToXYZ(d.sun.lat, d.sun.lon) : null;
    d._script = script(d);
    return d;
  }

  // ---------- the director: for each kind of question, where the camera looks and how far it's zoomed, over time ----------
  function script(d) {
    if (d.mode === 'radius' && d.radius) {
      const c = latLonToXYZ(d.radius.center.lat, d.radius.center.lon);
      const z = fitZoom((d.radius.km / EARTH_KM) * 2.3);
      return { total: 3.2, at: (e) => ({ center: c, zoom: lerpZoom(1, z, ease((e - 0.4) / 2.2)) }), reveal: (e) => ease((e - 1.2) / 1.6) };
    }
    if (d.mode === 'sun') {
      const f = latLonToXYZ(d.focus.lat, d.focus.lon);
      const z = d.what === 'sunrise' || d.what === 'sunset' || d.what === 'is_day' ? 1.6 : 1;
      return { total: 2.4, at: (e) => ({ center: f, zoom: lerpZoom(1, z, ease(e / 2.2)) }) };
    }
    const routes = d._routes;
    if (!routes.length) return { total: 0, at: () => ({ center: [0, 0, -1], zoom: 1 }) };
    if (d.mode === 'compare' || routes.length > 1) {
      // Every route at once, framed together; each plane at the same speed, so the longer flight takes visibly longer.
      const pts = routes.flatMap((r) => [r._a, r._b, slerp(r._a, r._b, 0.5)]);
      const mid = norm3(pts.reduce((s, p) => [s[0] + p[0], s[1] + p[1], s[2] + p[2]], [0, 0, 0]));
      const spread = Math.max(...pts.map((p) => angleBetween(mid, p)));
      const z = fitZoom(spread * 2);
      const longest = Math.max(...routes.map((r) => r.theta));
      const start = 1.4, longestFor = 8.5;
      routes.forEach((r) => { r._start = start; r._dur = Math.max(1.6, longestFor * (r.theta / Math.max(longest, 1e-6))); });
      return { total: start + longestFor + 0.8,
               at: (e) => ({ center: mid, zoom: lerpZoom(1, z, ease(e / 1.4)) }),
               progress: (r, e) => easeFlight((e - r._start) / r._dur) };
    }
    // One route: overview -> the departure -> follow the plane (wide in the middle of long journeys) -> arrival -> the
    // whole route. Long journeys are compressed in time, never in space: the plane always follows the true path.
    const r = routes[0];
    const mid = slerp(r._a, r._b, 0.5);
    const zFit = fitZoom(r.theta);
    const zClose = Math.min(24, Math.max(1.7, zFit * 1.7));
    const zWide = Math.max(1, Math.min(zClose, zFit * 0.95));
    const wideness = r.theta > 0.45 ? Math.min(1, (r.theta - 0.45) / 0.6) : 0;
    const T = { overview: 1.1, approach: 1.7, flight: Math.max(4.5, Math.min(13, 4 + (r.km || 0) / 1300)), arrive: 1.3, settle: 1.9 };
    const t1 = T.overview, t2 = t1 + T.approach, t3 = t2 + T.flight, t4 = t3 + T.arrive, t5 = t4 + T.settle;
    r._start = t2; r._dur = T.flight;
    const zStart = Math.min(1.15, zFit);
    const at = (e) => {
      if (e < t1) return { center: mid, zoom: zStart, phase: 'overview' };
      if (e < t2) {
        const k = ease((e - t1) / T.approach);
        return { center: slerp(mid, r._a, k), zoom: lerpZoom(zStart, zClose, k), phase: 'departure' };
      }
      if (e < t3) {
        const k = (e - t2) / T.flight, p = easeFlight(k);
        const wide = wideness * Math.pow(Math.sin(Math.PI * k), 2);   // the cinematic wide shot, mid-journey
        const plane = slerp(r._a, r._b, p);
        return { center: slerp(plane, mid, wide * 0.55), zoom: lerpZoom(zClose, zWide, wide), phase: 'flight' };
      }
      if (e < t4) return { center: r._b, zoom: lerpZoom(zClose, Math.min(24, zClose * 1.2), ease((e - t3) / T.arrive)), phase: 'arrival' };
      const k = ease((e - t4) / T.settle);
      return { center: slerp(r._b, mid, k), zoom: lerpZoom(Math.min(24, zClose * 1.2), zFit, k), phase: e < t5 ? 'settle' : 'done' };
    };
    return { total: t5, at, progress: (route, e) => easeFlight((e - route._start) / route._dur) };
  }

  // ---------- the clock and the camera ----------
  let elapsed = 0, lastNow = 0, paused = false, manual = false, journeyDone = false;
  let cam = { center: [0, 0.15, -0.99], zoom: 1 };
  let zoomMul = 1;            // the user's own scroll, on top of the director's framing
  let lastInteractAt = -1e9;

  function present(index) {
    current = index;
    data = prepare(history[index]);
    $('earthTitle').textContent = data.title || `${data.a.name} → ${data.b.name}`;
    $('earthSub').textContent = subtitle(data);
    $('earthKicker').textContent = { compare: 'Comparison', radius: 'Nearby', sun: 'Sunlight' }[data.mode] || 'Journey';
    buildHud(data);
    const many = history.length > 1;
    $('earthNav').hidden = !many;
    $('earthCount').textContent = `${index + 1} / ${history.length}`;
    $('earthPrev').disabled = index === 0;
    $('earthNext').disabled = index === history.length - 1;
    const opening = $('earthLayer').hidden;
    $('earthLayer').hidden = false;
    document.body.classList.add('scene-paused');
    elapsed = reduced ? data._script.total : 0;
    paused = false; manual = false; journeyDone = false; zoomMul = 1;
    if (opening) cam = { center: data._script.at(0).center.slice(), zoom: 0.92 };   // a new question while open flows on from here
    $('earthSave').textContent = 'Save image';
    setPlayState();
    lastNow = performance.now();
    cancelAnimationFrame(raf);   // never two loops
    raf = requestAnimationFrame(frame);
  }

  function subtitle(d) {
    const fmt = (n) => Math.round(n).toLocaleString();
    if (d.mode === 'radius') return `${(d.radius.places || []).length} places within ${fmt(d.radius.km)} km`;
    if (d.mode === 'sun') return d.sun && d.sun.at ? `Sunlight at ${new Date(d.sun.at).toUTCString().replace(':00 GMT', ' UTC')}` : '';
    if (d.mode === 'compare') return d._routes.map((r) => `${fmt(r.km)} km`).join('  vs  ');
    return `${fmt(d.km)} km  ·  ${fmt(d.miles)} mi  ·  in a straight line`;
  }

  // ---------- the panel under the globe: distance, progress, the estimate, the countries on the way ----------
  function buildHud(d) {
    const facts = $('earthFacts');
    facts.replaceChildren();
    const fmt = (n) => Math.round(n).toLocaleString();
    const add = (label, text, cls) => {
      const li = document.createElement('li');
      if (cls) li.className = cls;
      const s = document.createElement('span'); s.textContent = label;
      const b = document.createElement('b'); b.textContent = text;
      li.append(s, b); facts.append(li);
      return b;
    };
    const single = d._routes.length === 1 && d.mode !== 'compare';
    $('journeyHud').hidden = !single;
    if (d.mode === 'radius') {
      add('Centre', d.radius.center.name);
      add('Radius', `${fmt(d.radius.km)} km · ${fmt(d.radius.km / 1.609344)} mi`);
      add('Biggest nearby', (d.radius.places || []).slice(0, 3).map((p) => p.name).join(', ') || 'none in the map data', 'wide');
      return;
    }
    if (d.mode === 'sun') {
      const s = d.sun || {};
      add('Sun overhead', `${Math.abs(s.lat).toFixed(1)}°${s.lat >= 0 ? 'N' : 'S'}, ${Math.abs(s.lon).toFixed(1)}°${s.lon >= 0 ? 'E' : 'W'}`);
      if (d.focus && d.focus.name) add('Place', d.focus.name, 'wide');
      return;
    }
    if (!single) {
      d._routes.forEach((r) => {
        const b = add(`${r.a.name.split(',')[0]} → ${r.b.name.split(',')[0]}`,
          `${fmt(r.km)} km` + (r.flight ? ` · ≈ ${r.flight.text} flight (est.)` : ''));
        b.style.color = rgba(r.color, 1);
      });
      return;
    }
    const r = d._routes[0];
    add('Straight-line distance', `${fmt(r.km)} km · ${fmt(r.miles)} mi`);
    if (r.flight && !r.flight.too_short) add('Direct flight', `≈ ${r.flight.text} · ~${fmt(r.flight.route_km)} km flown (estimate)`);
    if (r.countries && r.countries.length) {
      const list = r.countries.length > 6 ? `${r.countries.slice(0, 6).join(' · ')} +${r.countries.length - 6}` : r.countries.join(' · ');
      const b = add('Passes over', list, 'wide');
      b.title = r.countries.join(', ');
    }
    $('journeyFrom').textContent = r.a.name.split(',')[0];
    $('journeyTo').textContent = r.b.name.split(',')[0];
  }

  let shownProgress = -1;
  function updateHud(progress) {
    if ($('journeyHud').hidden) return;
    const p = Math.max(0, Math.min(1, progress));
    if (Math.abs(p - shownProgress) < 0.001) return;
    shownProgress = p;
    const r = data._routes[0];
    $('journeyFill').style.transform = `scaleX(${p})`;
    $('journeyPlane').style.left = `${p * 100}%`;
    $('journeyKm').textContent = `${Math.round(p * r.km).toLocaleString()} / ${Math.round(r.km).toLocaleString()} km`;
  }

  function setPlayState() {
    const playable = Boolean(data && data._script.progress);
    $('earthPlay').hidden = !playable; $('earthReplay').hidden = !playable; $('earthSkip').hidden = !playable;
    $('earthPlay').textContent = paused || manual ? 'Resume' : 'Pause';
    $('earthPlay').disabled = journeyDone && !manual;
    $('earthSkip').disabled = journeyDone;
    shownProgress = -1;
  }

  // ---------- public ----------
  window.showGlobe = function showGlobe(d) {
    const key = d.title || `${d.a.name}|${d.b.name}`;
    let index = history.findIndex((h) => (h.title || `${h.a.name}|${h.b.name}`) === key);
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
    raf = 0;
  };
  window.globeOpen = () => !$('earthLayer').hidden;
  window.globeCount = () => history.length;
  window.__earthDebug = () => ({ elapsed, paused, manual, done: journeyDone, total: data && data._script.total, zoom: cam.zoom,
                                 phase: data && data._script.at(Math.min(elapsed, data._script.total)).phase, running: Boolean(raf), frames: framesDrawn, frameMs, plane: planeAt });
  window.globeThumbnail = function globeThumbnail(canvas, d) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 170, h = canvas.clientHeight || 96;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const shown = prepare({ ...d });
    const end = shown._script.at(shown._script.total);
    const draw = () => render(ctx, w, h, { d: shown, center: end.center, zoom: Math.min(end.zoom, 3), time: 0, compact: true, e: 1e9 });
    const sphere = gpuRenderer();
    if (sphere) sphere.texture(IMAGERY.day, draw); else draw();
  };

  // ---------- the frame loop ----------
  let framesDrawn = 0, frameMs = 0, planeAt = null;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    framesDrawn++;
    const dt = Math.min(0.1, Math.max(0, (now - lastNow) / 1000));
    lastNow = now;
    if (document.hidden || !data) return;
    const S = data._script;
    if (!paused && !manual) elapsed = Math.min(S.total, elapsed + dt);
    if (!journeyDone && elapsed >= S.total) { journeyDone = true; setPlayState(); }
    if (!manual) {
      // Follow the director, smoothed: a new question, a skip or a resume eases over instead of jumping.
      const target = S.at(elapsed);
      const k = reduced ? 1 : 1 - Math.exp(-dt * 6.5);
      cam.center = norm3(slerp(cam.center, target.center, k));
      cam.zoom = lerpZoom(cam.zoom, target.zoom, k);
    }
    const canvas = $('earthCanvas');
    const dpr = Math.min(gpuRenderer() ? 2 : 1.5, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 400, h = canvas.clientHeight || 400;
    const px = Math.round(w * dpr), py = Math.round(h * dpr);
    if (canvas.width !== px || canvas.height !== py) { canvas.width = px; canvas.height = py; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const zoom = Math.max(0.55, Math.min(48, cam.zoom * zoomMul));
    const started = performance.now();
    render(ctx, w, h, { d: data, center: cam.center, zoom, time: now / 1000, e: elapsed });
    frameMs += (performance.now() - started - frameMs) * 0.1;
    if (data._routes.length === 1 && S.progress) updateHud(S.progress(data._routes[0], elapsed));
  }

  // ---------- drawing ----------
  let stars = null, starsFor = '';
  function drawStars(ctx, w, h) {
    const key = `${w}x${h}`;
    if (starsFor !== key) {
      starsFor = key;
      const count = Math.round((w * h) / 3400);   // restrained: the Earth is the subject
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w, y: Math.random() * h, r: Math.random() < 0.88 ? Math.random() * 0.6 + 0.3 : Math.random() * 1.1 + 0.8,
        a: Math.random() * 0.45 + 0.25,
      }));
    }
    ctx.fillStyle = '#fff';
    stars.forEach((s) => { ctx.globalAlpha = s.a; ctx.fillRect(s.x, s.y, s.r, s.r); });
    ctx.globalAlpha = 1;
  }

  // The fixed lamp, only where there's no real Sun position (globes saved before this version, the CPU fallback).
  const LAMP = norm3([0.55, 0.42, 0.72]);

  function render(ctx, w, h, S) {
    const d = S.d;
    placed = [];
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * (S.compact ? 0.42 : 0.36) * S.zoom;
    const view = viewOf(S.center);
    const cLon = Math.cos(view.spinLon), sLon = Math.sin(view.spinLon), cLat = Math.cos(view.lat), sLat = Math.sin(view.lat);
    const rotate = ([x, y, z]) => {   // world -> view: x right, y up, z toward the viewer (seen from outside)
      let px = x * cLon - z * sLon, pz = x * sLon + z * cLon;
      const py = y * cLat - pz * sLat;
      pz = y * sLat + pz * cLat;
      return [-px, py, pz];
    };
    const project = (v) => { const r = rotate(v); return [cx + r[0] * R, cy - r[1] * R, r[2], Math.hypot(r[0], r[1])]; };
    const visible = (p) => p[2] > 0 || p[3] > 1.0;   // in front of the globe, or floating beyond its edge

    if (!S.compact) drawStars(ctx, w, h);
    const sphere = gpuRenderer();
    if (sphere) {
      const scale = ctx.canvas.width / w;
      const out = sphere.draw(ctx.canvas.width, ctx.canvas.height, {
        cx: cx * scale, cy: cy * scale, R: R * scale, cLon, sLon, cLat, sLat, light: d._sun ? rotate(d._sun) : LAMP, earth: true,
        day: IMAGERY.day, clouds: IMAGERY.clouds, night: IMAGERY.night, cloudDrift: (S.time || 0) * 0.00025,
        ambient: d._sun ? (d.mode === 'sun' ? 0.1 : 0.2) : 0.06, terminator: d._sun ? [-0.1, 0.16] : [-0.18, 0.42],
      });
      ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(out, 0, 0); ctx.restore();
      ctx.globalCompositeOperation = 'lighter';   // the atmosphere seen edge-on: a thin blue haze just outside the limb
      const haze = ctx.createRadialGradient(cx, cy, R * 0.995, cx, cy, R * 1.07);
      haze.addColorStop(0, 'rgba(120,180,255,.40)'); haze.addColorStop(0.35, 'rgba(90,150,255,.14)'); haze.addColorStop(1, 'rgba(80,140,255,0)');
      ctx.fillStyle = haze;
      ctx.beginPath(); ctx.arc(cx, cy, R * 1.07, 0, Math.PI * 2); ctx.arc(cx, cy, R * 0.995, 0, Math.PI * 2, true); ctx.fill();
      ctx.globalCompositeOperation = 'source-over';
    } else {
      paintEarthCPU(ctx, cx, cy, R, cLon, sLon, cLat, sLat, S.compact ? 110 : 360);
    }

    if (d.mode === 'radius' && d.radius) drawRadius(ctx, d, project, visible, S);
    d._routes.forEach((r, i) => {
      const progress = d._script.progress ? d._script.progress(r, S.e) : 1;
      drawRoute(ctx, d, r, Math.max(0, Math.min(1, progress)), project, visible, R, S, i);
    });
    if (d.mode === 'sun' && d.focus && d.focus.name) {
      const p = project(latLonToXYZ(d.focus.lat, d.focus.lon));
      if (visible(p)) { drawPin(ctx, p, GOLD, S, 6, true); if (!S.compact) drawLabel(ctx, p, d.focus.name.split(',')[0], GOLD, true); }
    }
  }

  // The route: the part already flown glows; the rest waits as a faint dotted line. It arcs a little above the
  // surface (higher for longer journeys), the way flight paths are usually drawn.
  function drawRoute(ctx, d, r, progress, project, visible, R, S, index) {
    const compare = d.mode === 'compare';
    const steps = Math.max(48, Math.min(240, Math.round(r.theta * 90)));
    const lifted = (t) => {
      const p = slerp(r._a, r._b, t), h = 1.004 + r.lift * Math.sin(Math.PI * t);
      return [p[0] * h, p[1] * h, p[2] * h];
    };
    const pts = [];
    for (let i = 0; i <= steps; i++) pts.push(project(lifted(i / steps)));
    const col = r.color, width = S.compact ? 1.6 : Math.min(3, Math.max(1.6, R * 0.01));
    const segment = (from, to) => {
      ctx.beginPath();
      let drawing = false;
      for (let i = from; i <= to; i++) {
        const p = pts[i];
        if (!visible(p)) { drawing = false; continue; }
        if (!drawing) { ctx.moveTo(p[0], p[1]); drawing = true; } else ctx.lineTo(p[0], p[1]);
      }
      ctx.stroke();
    };
    const flown = Math.round(progress * steps);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    if (!S.compact && flown < steps) {   // still ahead: faint dots
      ctx.setLineDash([2, 6]); ctx.strokeStyle = 'rgba(235,245,255,.4)'; ctx.lineWidth = 1.3;
      segment(flown, steps); ctx.setLineDash([]);
    }
    if (flown > 0) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.strokeStyle = rgba(col, 0.2); ctx.lineWidth = width * 3.2; segment(0, flown);   // the glow
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = rgba(col, 0.95); ctx.lineWidth = width; segment(0, flown);
      if (!S.compact && progress < 1) {   // the bright fresh trail just behind the plane
        ctx.strokeStyle = 'rgba(255,255,255,.8)'; ctx.lineWidth = Math.max(0.8, width * 0.4);
        segment(Math.max(0, flown - Math.round(steps * 0.08)), flown);
      }
    }
    const a = project(r._a), b = project(r._b);
    const fromColor = compare && index > 0 ? col : MAGENTA, toColor = compare ? col : GOLD;
    if (visible(a)) drawPin(ctx, a, fromColor, S, 5);
    if (visible(b)) drawPin(ctx, b, toColor, S, 5, progress >= 1);
    if (!S.compact) {
      if (visible(a) && !(compare && index > 0 && angleBetween(r._a, d._routes[0]._a) < 0.01)) drawLabel(ctx, a, r.a.name.split(',')[0], fromColor);
      if (visible(b)) drawLabel(ctx, b, r.b.name.split(',')[0], toColor, progress >= 1);
    }
    if (!S.compact && progress > 0 && progress < 1) {
      const p = project(lifted(progress)), q = project(lifted(Math.min(1, progress + 0.004))), o = project(lifted(Math.max(0, progress - 0.004)));
      if (visible(p)) {
        const ground = project(slerp(r._a, r._b, progress));
        const routePx = Math.hypot(pts[steps][0] - pts[0][0], pts[steps][1] - pts[0][1]);   // a short hop gets a smaller plane
        drawPlane(ctx, p, Math.atan2(q[1] - o[1], q[0] - o[0]), Math.max(9, Math.min(30, R * 0.06, routePx * 0.28)), ground, ground[2] > 0);
        if (S.d === data) planeAt = [p[0], p[1]];
      }
    }
  }

  function drawPin(ctx, p, color, S, size, strong) {
    const s = S.compact ? 3 : size;
    if (!S.compact) {
      const pulse = 0.5 + 0.5 * Math.sin((S.time || 0) * 2.2);
      ctx.strokeStyle = rgba(color, (strong ? 0.75 : 0.45) * (1 - pulse));
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(p[0], p[1], s * (1.8 + pulse * 1.8), 0, Math.PI * 2); ctx.stroke();
    }
    ctx.fillStyle = rgba(color, 1);
    ctx.beginPath(); ctx.arc(p[0], p[1], s, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,.95)';
    ctx.beginPath(); ctx.arc(p[0], p[1], s * 0.42, 0, Math.PI * 2); ctx.fill();
  }

  // Labels never cover each other: each tries above-right, below-right, above-left and below-left of its pin.
  let placed = [];
  function freeSpot(p, w, h) {
    const spots = [[p[0] + 12, p[1] - h - 8], [p[0] + 12, p[1] + 8], [p[0] - w - 12, p[1] - h - 8], [p[0] - w - 12, p[1] + 8]];
    return spots.find(([x, y]) => !placed.some((b) => x < b[0] + b[2] && x + w > b[0] && y < b[1] + b[3] && y + h > b[1])) || null;
  }
  function drawLabel(ctx, p, text, color, strong) {
    ctx.font = '600 12px Inter, -apple-system, system-ui, sans-serif';
    const w = ctx.measureText(text).width + 16, h = 22;
    const spot = freeSpot(p, w, h) || [p[0] + 12, p[1] - h - 8];
    const [x, y] = spot;
    placed.push([x - 2, y - 2, w + 4, h + 4]);
    ctx.fillStyle = 'rgba(4,10,22,.74)';
    ctx.strokeStyle = rgba(color, strong ? 0.85 : 0.45);
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, 6); else ctx.rect(x, y, w, h);
    ctx.fill(); ctx.stroke();
    ctx.strokeStyle = rgba(color, 0.5);
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(x < p[0] ? x + w : x, y < p[1] ? y + h : y); ctx.stroke();
    ctx.fillStyle = '#eef6ff';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x + 8, y + h / 2 + 0.5);
  }

  // A small airliner seen from above, shaded as if lit from the upper left, with its shadow on the ground below.
  function drawPlane(ctx, p, heading, size, ground, groundVisible) {
    if (groundVisible) {
      ctx.save();
      ctx.translate(ground[0] + size * 0.12, ground[1] + size * 0.18);
      ctx.rotate(heading + Math.PI / 2);
      ctx.scale(size * 0.9, size * 0.9);
      ctx.globalAlpha = 0.3;
      ctx.fillStyle = '#000';
      planePath(ctx); ctx.fill();
      ctx.restore();
    }
    ctx.save();
    ctx.translate(p[0], p[1]);
    ctx.rotate(heading + Math.PI / 2);
    ctx.scale(size, size);
    ctx.shadowColor = 'rgba(150,220,255,.5)'; ctx.shadowBlur = 10;
    const body = ctx.createLinearGradient(-0.5, 0, 0.5, 0);
    body.addColorStop(0, '#ffffff'); body.addColorStop(0.55, '#e6edf6'); body.addColorStop(1, '#a9b6c8');
    ctx.fillStyle = body;
    planePath(ctx); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = 0.025; ctx.strokeStyle = 'rgba(20,30,50,.55)';
    planePath(ctx); ctx.stroke();
    ctx.fillStyle = '#8796ab';   // engines
    [-0.2, 0.2].forEach((x) => { ctx.beginPath(); ctx.ellipse(x, 0.02, 0.035, 0.075, 0, 0, Math.PI * 2); ctx.fill(); });
    ctx.fillStyle = 'rgba(40,70,110,.8)';   // cockpit windows
    ctx.beginPath(); ctx.ellipse(0, -0.4, 0.028, 0.035, 0, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
  function planePath(ctx) {   // nose at -y, length 1, wingspan 1
    ctx.beginPath();
    ctx.moveTo(0, -0.5);
    ctx.bezierCurveTo(0.05, -0.47, 0.06, -0.38, 0.06, -0.3);
    ctx.lineTo(0.06, -0.1); ctx.lineTo(0.5, 0.12); ctx.lineTo(0.5, 0.18); ctx.lineTo(0.06, 0.08);   // right wing
    ctx.lineTo(0.05, 0.34); ctx.lineTo(0.2, 0.44); ctx.lineTo(0.2, 0.49); ctx.lineTo(0.03, 0.45);  // right tailplane
    ctx.lineTo(0, 0.5);
    ctx.lineTo(-0.03, 0.45); ctx.lineTo(-0.2, 0.49); ctx.lineTo(-0.2, 0.44); ctx.lineTo(-0.05, 0.34);
    ctx.lineTo(-0.06, 0.08); ctx.lineTo(-0.5, 0.18); ctx.lineTo(-0.5, 0.12); ctx.lineTo(-0.06, -0.1);
    ctx.lineTo(-0.06, -0.3);
    ctx.bezierCurveTo(-0.06, -0.38, -0.05, -0.47, 0, -0.5);
    ctx.closePath();
  }

  // Places within a radius: the circle drawn out, then the places, biggest first.
  function drawRadius(ctx, d, project, visible, S) {
    const c = latLonToXYZ(d.radius.center.lat, d.radius.center.lon);
    const reveal = S.compact ? 1 : d._script.reveal ? d._script.reveal(S.e) : 1;
    const n = 120, shown = Math.round(n * reveal);
    ctx.beginPath();
    let drawing = false;
    for (let i = 0; i <= shown; i++) {
      const p = project(destination(c, (i / n) * Math.PI * 2, d.radius.km));
      if (!visible(p)) { drawing = false; continue; }
      if (!drawing) { ctx.moveTo(p[0], p[1]); drawing = true; } else ctx.lineTo(p[0], p[1]);
    }
    ctx.strokeStyle = rgba(ROUTE_COLORS[0], 0.9); ctx.lineWidth = 1.6; ctx.setLineDash([5, 5]); ctx.stroke(); ctx.setLineDash([]);
    const centre = project(c);
    if (visible(centre)) { drawPin(ctx, centre, GOLD, S, 5, true); if (!S.compact) drawLabel(ctx, centre, d.radius.center.name.split(',')[0], GOLD, true); }
    (d.radius.places || []).forEach((pl, i) => {
      if (reveal < Math.min(1, 0.3 + i * 0.06)) return;
      const p = project(latLonToXYZ(pl.lat, pl.lon));
      if (!visible(p)) return;
      ctx.fillStyle = rgba(ROUTE_COLORS[0], 1);
      ctx.beginPath(); ctx.arc(p[0], p[1], S.compact ? 1.6 : 3.2, 0, Math.PI * 2); ctx.fill();
      if (!S.compact && i < 10) {
        ctx.font = '500 11px Inter, -apple-system, system-ui, sans-serif';
        const tw = ctx.measureText(pl.name).width;
        const spots = [[p[0] + 6, p[1] - 7], [p[0] - tw - 6, p[1] - 7], [p[0] - tw / 2, p[1] + 5], [p[0] - tw / 2, p[1] - 20]];
        const spot = spots.find(([x, y]) => !placed.some((b) => x < b[0] + b[2] && x + tw > b[0] && y < b[1] + b[3] && y + 14 > b[1]));
        if (!spot) return;   // no room: the dot stays, the name doesn't cover another
        placed.push([spot[0] - 2, spot[1] - 1, tw + 4, 16]);
        ctx.fillStyle = 'rgba(238,246,255,.92)';
        ctx.textBaseline = 'top';
        ctx.shadowColor = 'rgba(0,0,0,.85)'; ctx.shadowBlur = 4;
        ctx.fillText(pl.name, spot[0], spot[1]);
        ctx.shadowBlur = 0;
      }
    });
  }

  // The fallback painter for machines without WebGL 2: the same imagery, sampled on the CPU at a fixed size.
  const raster = document.createElement('canvas');
  const rasterCtx = raster.getContext('2d');
  let rasterImage = null, rasterSize = 0;
  function bilinear(map, u, v) {
    const { data: px, w, h } = map;
    const fx = (((u % 1) + 1) % 1) * w - 0.5, fy = Math.max(0, Math.min(h - 1, v * h - 0.5));
    const x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0;
    const xw = ((x0 % w) + w) % w, x1 = (xw + 1) % w, y1 = Math.min(h - 1, y0 + 1);
    const at = (x, y) => (y * w + x) * 4;
    const out = [0, 0, 0];
    for (let i = 0; i < 3; i++) {
      out[i] = (px[at(xw, y0) + i] * (1 - tx) + px[at(x1, y0) + i] * tx) * (1 - ty) + (px[at(xw, y1) + i] * (1 - tx) + px[at(x1, y1) + i] * tx) * ty;
    }
    return out;
  }
  function paintEarthCPU(ctx, cx, cy, R, cLon, sLon, cLat, sLat, RES) {
    if (!texture) {
      ctx.fillStyle = 'rgba(14,26,46,.95)';
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
      return;
    }
    if (rasterSize !== RES) { raster.width = raster.height = RES; rasterImage = rasterCtx.createImageData(RES, RES); rasterSize = RES; }
    const buf = rasterImage.data;
    for (let j = 0; j < RES; j++) {
      const ny = (j + 0.5) / RES * 2 - 1;
      for (let i = 0; i < RES; i++) {
        const idx = (j * RES + i) * 4;
        const sx = (i + 0.5) / RES * 2 - 1, nx = -sx;
        if (sx * sx + ny * ny > 1) { buf[idx + 3] = 0; continue; }
        const py = -ny, pz = Math.sqrt(Math.max(0, 1 - sx * sx - py * py));
        const py1 = py * cLat + pz * sLat, pz1 = -py * sLat + pz * cLat;
        const x = nx * cLon + pz1 * sLon, z = -nx * sLon + pz1 * cLon;
        const lon = Math.atan2(z, x) + Math.PI / 2, lat = Math.asin(Math.max(-1, Math.min(1, py1)));
        const [r, g, b] = bilinear(texture, (lon + Math.PI) / (2 * Math.PI), (Math.PI / 2 - lat) / Math.PI);
        const l = 0.6 + 0.5 * Math.max(0, sx * LAMP[0] + py * LAMP[1] + pz * LAMP[2]);
        buf[idx] = r * l; buf[idx + 1] = g * l; buf[idx + 2] = b * l; buf[idx + 3] = 255;
      }
    }
    rasterCtx.putImageData(rasterImage, 0, 0);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(raster, cx - R, cy - R, R * 2, R * 2);
  }

  // ---------- input ----------
  // Set up now if the page has already loaded (the phone app loads this on demand), else once it has.
  const whenReady = (fn) => (document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', fn) : fn());
  whenReady(() => {
    const canvas = $('earthCanvas');
    let dragging = false, lastX = 0, lastY = 0;
    const onDown = (x, y) => { dragging = true; lastX = x; lastY = y; };
    const onMove = (x, y) => {
      if (!dragging) return;
      if (!manual && (Math.abs(x - lastX) + Math.abs(y - lastY) > 0)) { manual = true; setPlayState(); }   // the user takes the camera
      const v = viewOf(cam.center);
      const k = 0.0055 / Math.max(1, Math.sqrt(cam.zoom * zoomMul));
      cam.center = centerOf(v.spinLon - (x - lastX) * k, Math.max(-1.35, Math.min(1.35, v.lat + (y - lastY) * k)));
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
      zoomMul = Math.max(0.05, Math.min(6, zoomMul * Math.exp(-e.deltaY * 0.0015)));
      lastInteractAt = performance.now();
    }, { passive: false });

    const togglePause = () => {
      if (!data) return;
      if (manual) { manual = false; paused = false; }   // "Resume" after looking around: the director takes the camera back
      else if (!journeyDone) paused = !paused;
      setPlayState();
    };
    const replay = () => { if (!data) return; elapsed = 0; paused = false; manual = false; journeyDone = false; zoomMul = 1; setPlayState(); };
    const skip = () => { if (!data) return; elapsed = data._script.total; manual = false; paused = false; setPlayState(); };
    window.__earthControls = { togglePause, replay, skip };
    $('earthPlay').addEventListener('click', togglePause);
    $('earthReplay').addEventListener('click', replay);
    $('earthSkip').addEventListener('click', skip);
    $('earthClose').addEventListener('click', window.hideGlobe);
    $('earthPrev').addEventListener('click', () => window.reopenGlobe('prev'));
    $('earthNext').addEventListener('click', () => window.reopenGlobe('next'));
    $('earthLayer').addEventListener('mousedown', (e) => { if (e.target === $('earthLayer')) window.hideGlobe(); });
    document.addEventListener('keydown', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      const open = window.globeOpen();
      if (e.key === 'Escape' && open) { e.preventDefault(); window.hideGlobe(); }
      else if (e.key === 'ArrowLeft' && open) { e.preventDefault(); window.reopenGlobe('prev'); }
      else if (e.key === 'ArrowRight' && open) { e.preventDefault(); window.reopenGlobe('next'); }
      else if (e.key === ' ' && open) { e.preventDefault(); togglePause(); }
      else if (e.key.toLowerCase() === 'r' && open && !e.metaKey && !e.ctrlKey) { e.preventDefault(); replay(); }
      else if (e.key.toLowerCase() === 's' && open && !e.metaKey && !e.ctrlKey) { e.preventDefault(); skip(); }
      else if (e.key.toLowerCase() === 'e' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.repeat) {
        e.preventDefault();
        open ? window.hideGlobe() : window.reopenGlobe('last');
      }
    });
    $('earthSave').addEventListener('click', () => {
      if (!data) return;
      const out = document.createElement('canvas');
      out.width = 1400; out.height = 1400;
      render(out.getContext('2d'), 1400, 1400, { d: data, center: cam.center, zoom: cam.zoom * zoomMul, time: 0, e: elapsed });
      out.toBlob((blob) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `jarvis-globe-${Date.now()}.png`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 4000);
        $('earthSave').textContent = 'Saved ✓';
      });
    });
  });
})();
