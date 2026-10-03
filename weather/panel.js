// The weather window: what "what's the weather?" opens. It shows up at once as a skeleton, fills in when the forecast
// arrives (backend: forecast.py, sent as "weather_panel"), and never gets stuck: no answer within a while, or an
// error, shows a clear message with "Try again". Drawn by the pieces next to it: icons.js (condition icons), fx.js
// (the living sky behind it), charts.js (hourly curve, 7-day ranges) and map.js (map + rain radar).
//
// Talks to the rest of Jervis only through the 'jervis-message' event and window.jervisSend (renderer.js), so the
// renderer needs no weather code of its own.
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const LOADING_TIMEOUT = 25000;
  const TINT = {
    day: { clear: '255 196 87', partly: '255 206 128', cloudy: '143 178 222', fog: '170 184 204', drizzle: '94 200 255',
      rain: '90 169 255', snow: '200 228 255', storm: '165 139 255' },
    night: { clear: '150 162 255', partly: '140 160 255', cloudy: '128 150 196', fog: '150 162 186', drizzle: '94 190 255',
      rain: '90 160 255', snow: '190 214 255', storm: '165 139 255' },
  };
  const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const fmt = (v, unit = '') => (v === null || v === undefined ? '—' : `${v}${unit}`);
  const compass = (deg) => (deg === null || deg === undefined ? '' : COMPASS[Math.round(deg / 22.5) % 16]);

  const ICON_REFRESH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>';
  const ICON_OFFLINE = '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 44h28a10 10 0 0 0 1.4-19.9A14 14 0 0 0 21 20.5 9.5 9.5 0 0 0 18 44z" opacity=".55"/><path d="M12 12l40 40"/></svg>';

  function build() {
    const layer = document.createElement('div');
    layer.className = 'wx-layer';
    layer.id = 'weatherLayer';
    layer.hidden = true;
    layer.setAttribute('role', 'dialog');
    layer.setAttribute('aria-modal', 'true');
    layer.setAttribute('aria-labelledby', 'wxPlace');
    layer.innerHTML = `
      <div class="wx-card" data-state="loading">
        <div class="wx-sky" aria-hidden="true"><canvas class="wx-fx"></canvas></div>
        <header class="wx-head">
          <div class="wx-title">
            <p class="wx-kicker"><i class="wx-live"></i><span>Weather</span><span class="wx-approx" hidden title="Set your city in Settings, General, for exact weather">Approximate location</span></p>
            <h2 id="wxPlace">Locating…</h2>
            <p class="wx-sub"><span class="wx-clock"></span><span class="wx-updated"></span></p>
          </div>
          <div class="wx-actions">
            <button type="button" class="wx-icon-btn wx-refresh" aria-label="Refresh the forecast" title="Refresh">${ICON_REFRESH}</button>
            <button type="button" class="ghost wx-close" title="Close (Esc)">Close</button>
          </div>
        </header>
        <p class="wx-banner" hidden role="status"></p>
        <div class="wx-grid">
          <section class="wx-tile wx-hero" aria-label="Current conditions">
            <div class="wx-hero-top">
              <div class="wx-hero-icon"></div>
              <div class="wx-hero-cond"><b class="wx-cond">—</b><span class="wx-feels"></span></div>
            </div>
            <p class="wx-temp" aria-live="polite"><span class="wx-temp-num">--</span><span class="wx-temp-unit">°C</span></p>
            <p class="wx-hilo"><span class="wx-hi-wrap">H <b class="wx-hi">—</b></span><span class="wx-lo-wrap">L <b class="wx-lo">—</b></span><span class="wx-sun"></span></p>
            <ul class="wx-metrics">
              <li class="wx-metric" data-m="humidity"><span class="wx-m-label">Humidity</span><b class="wx-m-value">—</b><small class="wx-m-note"></small>
                <svg class="wx-ring" viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="15" class="track"/><circle cx="18" cy="18" r="15" class="value" pathLength="100"/></svg></li>
              <li class="wx-metric" data-m="wind"><span class="wx-m-label">Wind</span><b class="wx-m-value">—</b><small class="wx-m-note"></small>
                <svg class="wx-compass" viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="15" class="track"/><path d="M18 3.6v3" class="north"/><g class="needle"><path d="M18 8.5l3.6 10.5H14.4z"/><circle cx="18" cy="18" r="2.2"/></g></svg></li>
              <li class="wx-metric" data-m="visibility"><span class="wx-m-label">Visibility</span><b class="wx-m-value">—</b><small class="wx-m-note"></small></li>
              <li class="wx-metric" data-m="uv"><span class="wx-m-label">UV index</span><b class="wx-m-value">—</b><small class="wx-m-note"></small>
                <span class="wx-uv-scale" aria-hidden="true"><i></i></span></li>
            </ul>
          </section>
          <section class="wx-tile wx-map" aria-label="Weather map"><div class="wx-map-root"></div></section>
          <section class="wx-tile wx-hourly" aria-label="Next 24 hours">
            <header class="wx-tile-head"><h3>Next 24 hours</h3><span class="wx-legend"><i class="t"></i>Temperature<i class="r"></i>Rain chance</span></header>
            <div class="wx-hourly-chart"></div>
          </section>
          <section class="wx-tile wx-daily" aria-label="7-day forecast">
            <header class="wx-tile-head"><h3>7-day forecast</h3><span class="wx-credit"></span></header>
            <div class="wx-daily-list"></div>
          </section>
        </div>
        <div class="wx-error" hidden role="alert">
          <div class="wx-error-icon">${ICON_OFFLINE}</div>
          <h3>Weather data is temporarily unavailable.</h3>
          <p class="wx-error-detail"></p>
          <div class="wx-error-actions">
            <button type="button" class="sheet-btn primary wx-retry">Try again</button>
            <button type="button" class="sheet-btn wx-settings">Open Settings</button>
          </div>
        </div>
      </div>`;
    document.body.append(layer);
    return layer;
  }

  const layer = build();
  const card = $('.wx-card', layer);
  const fx = new window.WeatherFX($('.wx-fx', layer), $('.wx-sky', layer));
  const map = new window.WeatherMap($('.wx-map-root', layer));
  let data = null;
  let askedCity = '';
  let clockTimer = 0, loadingTimer = 0, closeTimer = 0;
  let returnFocus = null;

  // ---------- states ----------
  function setState(state) {
    card.dataset.state = state;
    $('.wx-error', layer).hidden = state !== 'error';
    layer.setAttribute('aria-busy', String(state === 'loading'));
  }

  function open(opts = {}) {
    clearTimeout(closeTimer);
    const wasOpen = !layer.hidden;
    askedCity = opts.city || '';
    if (!wasOpen) {
      returnFocus = document.activeElement;
      layer.hidden = false;
      layer.classList.remove('closing');
      requestAnimationFrame(() => $('.wx-close', layer).focus({ preventScroll: true }));
    }
    const sameCity = data && !askedCity && data.place.source !== 'asked';
    if (sameCity) {
      render(data);           // show what we have straight away; the fresh answer replaces it in a moment
      $('.wx-refresh', layer).classList.add('busy');
    } else {
      setState('loading');
      $('#wxPlace', layer).textContent = askedCity ? `${askedCity[0].toUpperCase()}${askedCity.slice(1)}` : 'Locating…';
      $('.wx-updated', layer).textContent = 'Getting the forecast…';
      $('.wx-clock', layer).textContent = '';
    }
    fx.start();
    map.start();
    clearTimeout(loadingTimer);
    loadingTimer = setTimeout(() => {
      if (card.dataset.state === 'loading') fail('The weather service didn’t answer in time.');
      $('.wx-refresh', layer).classList.remove('busy');
    }, LOADING_TIMEOUT);
    startClock();
  }

  function close() {
    if (layer.hidden) return;
    layer.classList.add('closing');
    clearTimeout(loadingTimer);
    closeTimer = setTimeout(() => {
      layer.hidden = true;
      layer.classList.remove('closing');
      fx.stop();
      map.stop();
      clearInterval(clockTimer);
      if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
    }, 220);
  }

  function fail(message) {
    clearTimeout(loadingTimer);
    $('.wx-refresh', layer).classList.remove('busy');
    if (data && !askedCity) {   // keep showing the last forecast, say it may be old
      render(data);
      banner(`${message || 'Weather data is temporarily unavailable.'} Showing the last forecast.`);
      return;
    }
    if (layer.hidden) return;
    $('.wx-error-detail', layer).textContent = message && message !== 'Weather data is temporarily unavailable.' ? message : 'Check the internet connection, then try again.';
    $('.wx-settings', layer).hidden = !/Settings/i.test(message || '');
    $('#wxPlace', layer).textContent = 'Weather';
    $('.wx-updated', layer).textContent = '';
    setState('error');
    fx.set({ kind: 'cloudy', isDay: true, cloud: 60, wind: 6 });
  }

  function banner(text) {
    const b = $('.wx-banner', layer);
    b.textContent = text || '';
    b.hidden = !text;
  }

  // ---------- drawing ----------
  function render(d) {
    const c = d.current, today = d.today;
    const time = c.is_day ? 'day' : 'night';
    card.style.setProperty('--wx-rgb', (TINT[time] || TINT.day)[c.kind] || TINT.day.cloudy);
    card.dataset.kind = c.kind;
    card.dataset.time = time;
    $('#wxPlace', layer).textContent = d.place.name;
    $('.wx-approx', layer).hidden = d.place.source !== 'approximate';
    $('.wx-hero-icon', layer).innerHTML = window.wxIcon(c.kind, c.is_day, { animated: true });
    $('.wx-cond', layer).textContent = c.label;
    $('.wx-feels', layer).textContent = c.feels === null ? '' : `Feels like ${c.feels}°`;
    $('.wx-temp-num', layer).textContent = fmt(c.temp);
    $('.wx-temp', layer).setAttribute('aria-label', `${fmt(c.temp)} degrees Celsius, ${c.label}`);
    $('.wx-hi', layer).textContent = fmt(today.high, '°');
    $('.wx-lo', layer).textContent = fmt(today.low, '°');
    const hm = (iso) => (iso ? iso.slice(11, 16) : '');
    $('.wx-sun', layer).textContent = today.sunrise && today.sunset ? `Sunrise ${hm(today.sunrise)} · Sunset ${hm(today.sunset)}` : '';

    metric('humidity', fmt(c.humidity, '%'), c.humidity === null ? '' :
      c.humidity < 30 ? 'Dry' : c.humidity < 60 ? 'Comfortable' : c.humidity < 80 ? 'Humid' : 'Very humid');
    $('[data-m="humidity"] .value', layer).style.strokeDasharray = `${c.humidity ?? 0} 100`;
    metric('wind', c.wind === null ? '—' : `${c.wind} km/h`,
      [c.wind_dir !== null ? `From ${compass(c.wind_dir)}` : '', c.gusts !== null ? `gusts ${c.gusts}` : ''].filter(Boolean).join(' · '));
    $('[data-m="wind"] .needle', layer).style.transform = `rotate(${((c.wind_dir ?? 0) + 180) % 360}deg)`;
    const vis = c.visibility_km;
    metric('visibility', vis === null ? '—' : `${vis >= 10 ? Math.round(vis) : vis} km`,
      vis === null ? '' : vis >= 10 ? 'Clear' : vis >= 4 ? 'Good' : vis >= 1 ? 'Hazy' : 'Fog');
    const uv = c.uv;
    const uvLevel = uv === null ? '' : uv < 3 ? 'Low' : uv < 6 ? 'Moderate' : uv < 8 ? 'High' : uv < 11 ? 'Very high' : 'Extreme';
    metric('uv', uv === null ? '—' : String(Math.round(uv)), uv === null ? '' : `${uvLevel}${!c.is_day ? ' · night' : ''}`);
    $('.wx-uv-scale i', layer).style.left = `${Math.min(100, ((uv ?? 0) / 11) * 100)}%`;

    window.weatherCharts.hourly($('.wx-hourly-chart', layer), d.hourly, { windUnit: d.units?.wind });
    window.weatherCharts.daily($('.wx-daily-list', layer), d.daily, c);

    if (d.place.lat !== null && d.place.lat !== undefined) {
      const moved = !data || data.place.lat !== d.place.lat || data.place.lon !== d.place.lon || !map.home;
      if (moved) map.setLocation(d.place.lat, d.place.lon, `${fmt(c.temp, '°')}`);
      else map.setLabel(`${fmt(c.temp, '°')}`);
      map.setCloudCover(c.cloud);
      if (!data || data.radar !== d.radar) map.setRadar(d.radar);
    }
    fx.set({ kind: c.kind, isDay: c.is_day, wind: c.wind, windDir: c.wind_dir, cloud: c.cloud });
    const source = d.source || { name: 'Open-Meteo.com', license: 'CC BY 4.0' };
    $('.wx-credit', layer).textContent = `Data: ${source.name} · ${source.license}`;   // the licence asks for credit
    banner(d.stale ? 'The weather service isn’t answering, so this is the last forecast I got.' : '');
    data = d;
    setState('ready');
    tickClock();
  }

  function metric(name, value, note) {
    const li = $(`[data-m="${name}"]`, layer);
    $('.wx-m-value', li).textContent = value;
    $('.wx-m-note', li).textContent = note || '';
  }

  // ---------- the location's own clock, and "updated 3 min ago" ----------
  function tickClock() {
    if (!data) return;
    let clock;
    try {
      clock = new Intl.DateTimeFormat([], { weekday: 'long', hour: '2-digit', minute: '2-digit', timeZone: data.timezone || undefined }).format(new Date());
    } catch (e) {
      const t = new Date(Date.now() + data.utc_offset * 1000);
      clock = `${String(t.getUTCHours()).padStart(2, '0')}:${String(t.getUTCMinutes()).padStart(2, '0')}`;
    }
    $('.wx-clock', layer).textContent = clock;
    const mins = Math.max(0, Math.round((Date.now() / 1000 - data.updated) / 60));
    $('.wx-updated', layer).textContent = mins < 1 ? 'Updated just now' : mins < 60 ? `Updated ${mins} min ago` : `Updated ${Math.round(mins / 60)} h ago`;
  }

  function startClock() {
    clearInterval(clockTimer);
    clockTimer = setInterval(tickClock, 15000);
    tickClock();
  }

  function refresh(force = true) {
    $('.wx-refresh', layer).classList.add('busy');
    if (!window.jervisSend?.({ type: 'weather_refresh', city: askedCity, refresh: force })) {
      fail('Jervis’s engine isn’t connected, so I can’t get the forecast right now.');
      return;
    }
    clearTimeout(loadingTimer);
    loadingTimer = setTimeout(() => fail('The weather service didn’t answer in time.'), LOADING_TIMEOUT);
  }

  // ---------- from the backend ----------
  window.addEventListener('jervis-message', (event) => {
    const msg = event.detail || {};
    if (msg.type === 'weather_open') open({ city: msg.city || '' });
    else if (msg.type === 'close_weather') close();
    else if (msg.type === 'weather_panel') {
      if (layer.hidden) return;   // closed while it was loading: keep it closed
      clearTimeout(loadingTimer);
      $('.wx-refresh', layer).classList.remove('busy');
      if (msg.data) render(msg.data);
      else fail(msg.error);
    }
  });

  // ---------- controls ----------
  $('.wx-close', layer).addEventListener('click', close);
  $('.wx-refresh', layer).addEventListener('click', () => refresh(true));
  $('.wx-retry', layer).addEventListener('click', () => { setState('loading'); refresh(true); });
  $('.wx-settings', layer).addEventListener('click', () => { close(); document.getElementById('settingsBtn')?.click(); });
  layer.addEventListener('mousedown', (e) => { if (e.target === layer) close(); });
  window.addEventListener('keydown', (e) => {   // capture: before the window's own Escape (which leaves full screen)
    if (e.key === 'Escape' && !layer.hidden) {
      e.preventDefault();
      e.stopImmediatePropagation();
      close();
    }
  }, true);
  let resizeTimer = 0;
  new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (data && !layer.hidden) window.weatherCharts.hourly($('.wx-hourly-chart', layer), data.hourly, { windUnit: data.units?.wind }); }, 120);
  }).observe($('.wx-hourly-chart', layer));

  // The small weather card in the left column opens the full forecast.
  const cardEl = document.querySelector('.card.weather');
  if (cardEl) {
    cardEl.classList.add('wx-opener');
    cardEl.tabIndex = 0;
    cardEl.setAttribute('role', 'button');
    cardEl.setAttribute('aria-label', 'Open the full weather forecast');
    cardEl.title = 'Open the full forecast';
    const openFromCard = () => { open({}); refresh(false); };
    cardEl.addEventListener('click', openFromCard);
    cardEl.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openFromCard(); } });
  }

  window.weatherOpen = () => !layer.hidden;
  window.weatherPanel = { open, close, render, fail, isOpen: window.weatherOpen };
})();
