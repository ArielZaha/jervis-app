// Forecast charts for the weather window, drawn as SVG/HTML from the normalized forecast (see forecast.py):
//   hourly(): the next 24 hours as one picture — a smooth temperature curve, rain chance as bars beneath it, wind
//             arrows, the night hours shaded, and a crosshair readout under the pointer.
//   daily():  7 days as rows, each day's low-to-high span drawn on one shared temperature scale, so warm and cool days
//             can be compared at a glance.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const fmt = (v, unit = '') => (v === null || v === undefined ? '—' : `${v}${unit}`);
  const el = (tag, attrs = {}) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };

  // Temperature -> colour, cold blue through cyan and gold to hot coral (used by both charts).
  const STOPS = [[-10, [120, 150, 255]], [5, [90, 169, 255]], [15, [79, 216, 255]], [22, [61, 242, 192]],
    [28, [255, 196, 87]], [36, [255, 122, 89]]];
  function tempColor(t, alpha = 1) {
    if (t === null || t === undefined) return `rgba(143,163,196,${alpha})`;
    let i = 0;
    while (i < STOPS.length - 2 && t > STOPS[i + 1][0]) i++;
    const [t0, c0] = STOPS[i], [t1, c1] = STOPS[i + 1];
    const k = Math.max(0, Math.min(1, (t - t0) / (t1 - t0)));
    const c = c0.map((v, j) => Math.round(v + (c1[j] - v) * k));
    return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
  }

  // Monotone cubic interpolation (Fritsch–Carlson): smooth, but never overshoots the real values between hours.
  function smoothPath(pts) {
    const n = pts.length;
    if (n < 2) return '';
    const dx = [], dy = [], m = [];
    for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; dy[i] = (pts[i + 1][1] - pts[i][1]) / dx[i]; }
    m[0] = dy[0]; m[n - 1] = dy[n - 2];
    for (let i = 1; i < n - 1; i++) m[i] = dy[i - 1] * dy[i] <= 0 ? 0 : (dy[i - 1] + dy[i]) / 2;
    for (let i = 0; i < n - 1; i++) {
      if (dy[i] === 0) { m[i] = m[i + 1] = 0; continue; }
      const a = m[i] / dy[i], b = m[i + 1] / dy[i], s = a * a + b * b;
      if (s > 9) { const t = 3 / Math.sqrt(s); m[i] = t * a * dy[i]; m[i + 1] = t * b * dy[i]; }
    }
    let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < n - 1; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1], h = dx[i] / 3;
      d += `C${(x0 + h).toFixed(1)},${(y0 + m[i] * h).toFixed(1)} ${(x1 - h).toFixed(1)},${(y1 - m[i + 1] * h).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
    }
    return d;
  }

  const hourLabel = (iso, i) => (i === 0 ? 'Now' : iso.slice(11, 13));
  const windArrow = (deg) => (deg === null || deg === undefined ? 0 : (deg + 180) % 360);   // where it blows to

  function hourly(container, hours, opts = {}) {
    container.textContent = '';
    if (!hours || hours.length < 2) {
      container.innerHTML = '<p class="wx-empty-note">No hourly forecast available.</p>';
      return;
    }
    const W = Math.max(320, container.clientWidth), H = Math.max(190, container.clientHeight);
    const pad = { l: 18, r: 18 };
    const band = { hour: 16, icon: 30, rain: 40, wind: 26 };
    const top = band.hour + band.icon + 22;                // curve area starts below hour labels, icons and temp labels
    const bottom = H - band.rain - band.wind - 6;
    const n = hours.length, step = (W - pad.l - pad.r) / (n - 1);
    const every = step >= 46 ? 1 : step >= 23 ? 2 : 3;     // label density that fits the width
    const temps = hours.map((h) => h.temp).filter((t) => t !== null);
    const lo = Math.min(...temps), hi = Math.max(...temps), span = Math.max(4, hi - lo);
    const yOf = (t) => bottom - ((t - lo) / span) * (bottom - top);
    const xOf = (i) => pad.l + i * step;
    const pts = hours.map((h, i) => [xOf(i), yOf(h.temp ?? lo)]);
    const id = `wxh${Math.random().toString(36).slice(2, 7)}`;

    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'wx-hourly-svg', role: 'img',
      'aria-label': `Temperature and rain chance for the next ${n - 1} hours` });
    const defs = el('defs');
    const area = el('linearGradient', { id: `${id}a`, x1: 0, y1: 0, x2: 0, y2: 1 });
    area.append(el('stop', { offset: 0, 'stop-color': 'rgb(var(--wx-rgb))', 'stop-opacity': 0.32 }),
      el('stop', { offset: 1, 'stop-color': 'rgb(var(--wx-rgb))', 'stop-opacity': 0 }));
    const line = el('linearGradient', { id: `${id}l`, x1: 0, y1: 0, x2: 1, y2: 0, gradientUnits: 'userSpaceOnUse' });
    line.setAttribute('x1', pad.l); line.setAttribute('x2', W - pad.r);
    hours.forEach((h, i) => line.append(el('stop', { offset: (i / (n - 1)).toFixed(3), 'stop-color': tempColor(h.temp) })));
    defs.append(area, line);
    svg.append(defs);

    // night hours: a quiet darker band behind everything
    let runStart = null;
    hours.forEach((h, i) => {
      const dark = !h.is_day;
      if (dark && runStart === null) runStart = i;
      if ((!dark || i === n - 1) && runStart !== null) {
        const end = dark ? i : i - 1;
        const x0 = Math.max(0, xOf(runStart) - step / 2), x1 = Math.min(W, xOf(end) + step / 2);
        svg.append(el('rect', { x: x0, y: 0, width: x1 - x0, height: H, class: 'wx-night-band', rx: 6 }));
        runStart = null;
      }
    });

    // baseline grid
    for (const t of [lo, lo + span / 2, lo + span]) {
      svg.append(el('line', { x1: pad.l, x2: W - pad.r, y1: yOf(t), y2: yOf(t), class: 'wx-gridline' }));
    }

    const curve = smoothPath(pts);
    svg.append(el('path', { d: `${curve}L${xOf(n - 1)},${bottom}L${xOf(0)},${bottom}Z`, fill: `url(#${id}a)` }));
    svg.append(el('path', { d: curve, fill: 'none', stroke: `url(#${id}l)`, 'stroke-width': 2.4, 'stroke-linecap': 'round', class: 'wx-curve' }));

    const rainTop = bottom + 10, rainH = band.rain - 14;
    hours.forEach((h, i) => {
      const x = xOf(i);
      const labelled = i % every === 0;
      if (labelled) {
        const label = el('text', { x, y: 12, class: `wx-h-label${i === 0 ? ' now' : ''}`, 'text-anchor': 'middle' });
        label.textContent = hourLabel(h.time, i);
        svg.append(label);
        const icon = el('foreignObject', { x: x - 12, y: band.hour + 1, width: 24, height: 24 });
        icon.innerHTML = window.wxIcon(h.kind, h.is_day);
        svg.append(icon);
        if (h.temp !== null) {
          const tl = el('text', { x, y: pts[i][1] - 9, class: 'wx-t-label', 'text-anchor': 'middle' });
          tl.textContent = `${h.temp}°`;
          svg.append(tl);
          svg.append(el('circle', { cx: x, cy: pts[i][1], r: i === 0 ? 4 : 2.4, class: i === 0 ? 'wx-dot now' : 'wx-dot', fill: tempColor(h.temp) }));
        }
      }
      const chance = h.rain_chance ?? 0;
      const bh = Math.max(1.5, (chance / 100) * rainH);
      svg.append(el('rect', { x: x - Math.min(7, step * 0.32), y: rainTop + rainH - bh, width: Math.min(14, step * 0.64),
        height: bh, rx: 2, class: 'wx-rain-bar', style: `opacity:${0.25 + (chance / 100) * 0.75}` }));
      if (labelled && chance >= 20) {
        const rl = el('text', { x, y: rainTop + rainH - bh - 4, class: 'wx-r-label', 'text-anchor': 'middle' });
        rl.textContent = `${chance}%`;
        svg.append(rl);
      }
      if (labelled && h.wind !== null) {
        const g = el('g', { transform: `translate(${x} ${H - 15})` });
        const arrow = el('path', { d: 'M0,-5 L3.2,3 L0,1.4 L-3.2,3 Z', class: 'wx-wind-arrow', transform: `rotate(${windArrow(h.wind_dir)})` });
        const wl = el('text', { x: 0, y: 13, class: 'wx-w-label', 'text-anchor': 'middle' });
        wl.textContent = h.wind;
        g.append(arrow, wl);
        svg.append(g);
      }
    });

    // pointer readout
    const cross = el('line', { x1: 0, x2: 0, y1: band.hour + band.icon, y2: H - band.wind, class: 'wx-cross' });
    const dot = el('circle', { r: 5, class: 'wx-cross-dot' });
    cross.style.display = dot.style.display = 'none';
    svg.append(cross, dot);
    const tip = document.createElement('div');
    tip.className = 'wx-tip';
    tip.hidden = true;
    const hit = el('rect', { x: 0, y: 0, width: W, height: H, fill: 'transparent' });
    svg.append(hit);
    const unit = opts.windUnit || 'km/h';
    const show = (clientX) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(n - 1, Math.round((clientX - r.left - pad.l) / step)));
      const h = hours[i], x = xOf(i);
      cross.setAttribute('x1', x); cross.setAttribute('x2', x);
      dot.setAttribute('cx', x); dot.setAttribute('cy', pts[i][1]);
      cross.style.display = dot.style.display = '';
      tip.innerHTML = `<b>${i === 0 ? 'Now' : `${h.time.slice(11, 16)}`}</b><span>${h.label}</span>` +
        `<em>${fmt(h.temp, '°')} <small>feels ${fmt(h.feels, '°')}</small></em>` +
        `<span>Rain ${fmt(h.rain_chance, '%')} · Wind ${fmt(h.wind)} ${unit}</span>`;
      tip.hidden = false;
      const left = Math.max(8, Math.min(W - tip.offsetWidth - 8, x + 14 > W - 150 ? x - tip.offsetWidth - 14 : x + 14));
      tip.style.transform = `translate(${left}px, ${Math.max(4, pts[i][1] - 70)}px)`;
    };
    hit.addEventListener('pointermove', (e) => show(e.clientX));
    hit.addEventListener('pointerleave', () => { cross.style.display = dot.style.display = 'none'; tip.hidden = true; });
    container.append(svg, tip);
  }

  function daily(container, days, current) {
    container.textContent = '';
    if (!days || !days.length) {
      container.innerHTML = '<p class="wx-empty-note">No daily forecast available.</p>';
      return;
    }
    const lows = days.map((d) => d.low).filter((v) => v !== null);
    const highs = days.map((d) => d.high).filter((v) => v !== null);
    const min = Math.min(...lows), max = Math.max(...highs), span = Math.max(1, max - min);
    const fmtDay = new Intl.DateTimeFormat(undefined, { weekday: 'short' });
    const list = document.createElement('ol');
    list.className = 'wx-days';
    days.forEach((d, i) => {
      const date = new Date(`${d.date}T12:00:00`);
      const name = i === 0 ? 'Today' : i === 1 ? 'Tmrw' : fmtDay.format(date);
      const from = d.low === null ? 0 : ((d.low - min) / span) * 100;
      const to = d.high === null ? 100 : ((d.high - min) / span) * 100;
      const li = document.createElement('li');
      li.className = 'wx-day';
      li.style.setProperty('--i', i);
      li.title = `${d.label} · ${fmt(d.low, '°')} to ${fmt(d.high, '°')} · rain ${fmt(d.rain_chance, '%')} · wind up to ${fmt(d.wind)} km/h`;
      const rain = (d.rain_chance ?? 0) >= 10 ? `<span class="wx-day-rain">${d.rain_chance}%</span>` : '<span class="wx-day-rain dry"></span>';
      let marker = '';
      if (i === 0 && current?.temp !== null && current?.temp !== undefined) {
        const at = Math.max(0, Math.min(100, ((current.temp - min) / span) * 100));
        marker = `<i class="wx-range-now" style="left:${at}%" title="Now ${current.temp}°"></i>`;
      }
      li.innerHTML = `<span class="wx-day-name">${name}</span>
        <span class="wx-day-icon">${window.wxIcon(d.kind, true)}</span>
        ${rain}
        <span class="wx-day-lo">${fmt(d.low, '°')}</span>
        <span class="wx-range"><i class="wx-range-fill" style="left:${from}%;right:${100 - to}%;background:linear-gradient(90deg, ${tempColor(d.low)}, ${tempColor(d.high)})"></i>${marker}</span>
        <span class="wx-day-hi">${fmt(d.high, '°')}</span>`;
      list.append(li);
    });
    container.append(list);
  }

  window.weatherCharts = { hourly, daily, tempColor };
})();
