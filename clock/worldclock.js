// The world clock window: what "what time is it in Tokyo?" opens. One large live clock for the place asked about, the
// Sun's real path over its day, and every place on the clock as a row on one shared 24-hour strip, so the hours line
// up and you can see who is asleep. Move over the strips to read every place's time at another moment.
//
// The backend (app.py, worldclock.py) only names the places and their IANA time zones ("Asia/Tokyo"). Every time shown
// here comes from one source, this computer's clock, read once a second and turned into each place's wall time by the
// browser's own time-zone database (Intl), so daylight saving and odd offsets are followed without any table here.
// Sunrise, sunset and the Sun's height use the same NOAA formulas as geo.py and need only the place's coordinates;
// a place without them simply has no Sun path. Nothing here needs the network.
//
// Talks to the rest of Jarvis only through the 'jarvis-message' event and window.jarvisSend (renderer.js).
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const MAX_CITIES = 6;
  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* the choice just isn't kept */ } },
  };
  const ICON = {
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5"/><path d="M5.5 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v.5"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    remove: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  };

  // ---------- time: one clock, every zone derived from it ----------
  const formatters = new Map();
  function formatter(tz, kind) {
    const key = `${tz}|${kind}`;
    if (!formatters.has(key)) {
      const options = kind === 'parts'
        ? { year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', hourCycle: 'h23' }
        : kind === 'date' ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }
        : kind === 'weekday' ? { weekday: 'short' } : { timeZoneName: kind };
      formatters.set(key, new Intl.DateTimeFormat('en-US', { ...options, timeZone: tz }));
    }
    return formatters.get(key);
  }
  function wall(ms, tz) {   // that instant on the zone's own clock
    const out = {};
    for (const part of formatter(tz, 'parts').formatToParts(ms)) if (part.type !== 'literal') out[part.type] = Number(part.value);
    return out;
  }
  const dayNumber = (w) => Math.floor(Date.UTC(w.year, w.month - 1, w.day) / 86400000);
  function offsetMinutes(ms, tz) {   // how far the zone's clock is ahead of UTC at that instant
    const w = wall(ms, tz);
    return Math.round((Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second) - Math.floor(ms / 1000) * 1000) / 60000);
  }
  function instantOf(tz, year, month, day, hour, minute = 0) {   // the instant a wall time happens in the zone
    const asUtc = Date.UTC(year, month - 1, day, hour, minute);
    let guess = asUtc - offsetMinutes(asUtc, tz) * 60000;
    return asUtc - offsetMinutes(guess, tz) * 60000;
  }
  function daylightSaving(ms, tz) {   // 'on' | 'off' (the zone has it, not now) | 'none'
    const year = wall(ms, tz).year;
    const winter = offsetMinutes(Date.UTC(year, 0, 1, 12), tz), summer = offsetMinutes(Date.UTC(year, 6, 1, 12), tz);
    if (winter === summer) return 'none';
    return offsetMinutes(ms, tz) === Math.max(winter, summer) ? 'on' : 'off';
  }
  function utcLabel(minutes) {
    const sign = minutes < 0 ? '−' : '+', abs = Math.abs(minutes);
    return `UTC${sign}${Math.floor(abs / 60)}${abs % 60 ? ':' + String(abs % 60).padStart(2, '0') : ''}`;
  }
  function zoneName(ms, tz) {
    const part = formatter(tz, 'long').formatToParts(ms).find((p) => p.type === 'timeZoneName');
    return part && !/^GMT/.test(part.value) ? part.value : tz.replace(/_/g, ' ');
  }
  const two = (n) => String(n).padStart(2, '0');
  function clockText(w, hour24) {
    return hour24 ? { time: `${two(w.hour)}:${two(w.minute)}`, half: '' } : { time: `${w.hour % 12 || 12}:${two(w.minute)}`, half: w.hour < 12 ? 'AM' : 'PM' };
  }
  const plainTime = (w, hour24) => { const t = clockText(w, hour24); return t.half ? `${t.time} ${t.half}` : t.time; };
  function span(minutes) {   // "6 h", "5 h 30 min", "45 min"
    const abs = Math.abs(Math.round(minutes)), h = Math.floor(abs / 60), m = abs % 60;
    return h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`;
  }
  function spanWords(minutes) {
    const abs = Math.abs(Math.round(minutes)), h = Math.floor(abs / 60), m = abs % 60;
    const hours = h ? `${h} hour${h === 1 ? '' : 's'}` : '';
    return h && m ? `${hours} ${m} minutes` : h ? hours : `${m} minutes`;
  }

  // ---------- the Sun (NOAA's formulas, the same as geo.py) ----------
  const rad = (d) => d * Math.PI / 180, deg = (r) => r * 180 / Math.PI, mod = (a, n) => ((a % n) + n) % n;
  function solar(ms) {
    const n = (ms - Date.UTC(2000, 0, 1, 12)) / 86400000;
    const L = mod(280.460 + 0.9856474 * n, 360), g = rad(mod(357.528 + 0.9856003 * n, 360));
    const lam = rad(L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)), eps = rad(23.439 - 0.0000004 * n);
    const ra = mod(deg(Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam))), 360);
    return { eqtime: 4 * (mod(L - ra + 540, 360) - 180), decl: Math.asin(Math.sin(eps) * Math.sin(lam)), ra, n };
  }
  function sunElevation(lat, lon, ms) {   // degrees above the horizon (negative: below)
    const { decl, ra, n } = solar(ms);
    const overhead = mod(ra - mod(280.46061837 + 360.98564736629 * n, 360) + 540, 360) - 180;   // the longitude the Sun is over
    const p = rad(lat);
    return deg(Math.asin(Math.sin(p) * Math.sin(decl) + Math.cos(p) * Math.cos(decl) * Math.cos(rad(lon - overhead))));
  }
  function sunEvents(lat, lon, year, month, day) {   // that local date's sunrise and sunset as instants, or { polar }
    const noon = Date.UTC(year, month - 1, day, 12) - lon / 15 * 3600000;
    const { eqtime, decl } = solar(noon);
    const p = rad(lat);
    const cosHa = Math.cos(rad(90.833)) / (Math.cos(p) * Math.cos(decl)) - Math.tan(p) * Math.tan(decl);
    if (cosHa < -1) return { polar: 'day' };
    if (cosHa > 1) return { polar: 'night' };
    const ha = deg(Math.acos(cosHa)), midnight = Date.UTC(year, month - 1, day);
    return { sunrise: midnight + (720 - 4 * (lon + ha) - eqtime) * 60000, sunset: midnight + (720 - 4 * (lon - ha) - eqtime) * 60000 };
  }
  const located = (city) => typeof city.lat === 'number' && typeof city.lon === 'number';

  // ---------- the window ----------
  const layer = document.createElement('div');
  layer.className = 'wc-layer';
  layer.id = 'clockLayer';
  layer.hidden = true;
  layer.setAttribute('role', 'dialog');
  layer.setAttribute('aria-modal', 'true');
  layer.setAttribute('aria-labelledby', 'wcCity');
  layer.innerHTML = `
    <div class="wc-card" tabindex="-1" data-phase="night">
      <div class="wc-sky" aria-hidden="true"></div>
      <header class="wc-head">
        <div class="wc-title"><h2 id="wcCity"></h2><p class="wc-country"></p></div>
        <div class="wc-actions">
          <div class="wc-seg" role="group" aria-label="Clock format">
            <button type="button" data-hours="12" title="12-hour clock">12h</button><button type="button" data-hours="24" title="24-hour clock">24h</button>
          </div>
          <button type="button" class="ghost wc-view" title="Show only the times"></button>
          <button type="button" class="ghost wc-close" title="Close (Esc)">Close</button>
        </div>
      </header>
      <div class="wc-top">
        <section class="wc-main" aria-live="off">
          <p class="wc-time"><span class="wc-hm"></span><span class="wc-side"><span class="wc-half"></span><span class="wc-sec"></span></span></p>
          <div class="wc-under">
            <div><p class="wc-date"></p><p class="wc-zone"></p></div>
            <button type="button" class="wc-copy" title="Copy this time">${ICON.copy}<span>Copy time</span></button>
          </div>
        </section>
        <section class="wc-sun" aria-label="The Sun's path today">
          <div class="wc-sun-box"><svg class="wc-sun-path" viewBox="0 0 400 150" preserveAspectRatio="none" aria-hidden="true">
            <defs><clipPath id="wcAbove"><rect x="0" y="0" width="400" height="100"/></clipPath>
              <linearGradient id="wcDayFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".34"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
            <path class="wc-sun-fill" clip-path="url(#wcAbove)" fill="url(#wcDayFill)"/>
            <path class="wc-sun-night"/>
            <path class="wc-sun-day" clip-path="url(#wcAbove)"/>
            <line class="wc-horizon" x1="0" y1="100" x2="400" y2="100"/>
          </svg><i class="wc-sun-dot"></i></div>
          <p class="wc-sun-times"><span class="wc-rise"></span><span class="wc-daylight"></span><span class="wc-set"></span></p>
        </section>
      </div>
      <ul class="wc-facts"></ul>
      <section class="wc-compare" aria-label="Every place on the clock">
        <p class="wc-compare-head"><span class="wc-moment">Now</span><span class="wc-legend"><i class="wc-key-day"></i>Daylight<i class="wc-key-work"></i>9 to 5</span></p>
        <ol class="wc-rows"></ol>
        <i class="wc-nowline" aria-hidden="true"></i><i class="wc-scrubline" aria-hidden="true" hidden></i>
      </section>
      <footer class="wc-foot">
        <form class="wc-add" autocomplete="off">
          <label class="wc-add-field">${ICON.plus}<input type="text" name="city" maxlength="60" placeholder="Add a city or country" aria-label="Add a city or country" spellcheck="false"></label>
          <button type="submit" class="ghost">Add</button>
        </form>
        <div class="wc-recent" aria-label="Recent places"></div>
        <p class="wc-note" role="status"></p>
      </footer>
    </div>`;
  document.body.append(layer);
  const card = $('.wc-card', layer);

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  let home = { name: 'Your time', country: '', tz: browserZone, lat: null, lon: null, home: true };
  let cities = [];            // the places on the clock, besides your own
  let primary = home;         // the one in the large clock
  let hour24 = store.get('jarvis-clock-24h', false) === true;
  let compact = store.get('jarvis-clock-compact', false) === true;
  let ticker = 0, drawnMinute = -1, drawnSecond = -1, scrub = 0, pendingAdd = 0, copiedTimer = 0, closeTimer = 0;
  const idOf = (city) => (city.home ? 'home' : `${city.tz}|${city.name}`);
  const everyone = () => [home, ...cities];

  // ---------- drawing ----------
  function drawHead() {
    $('#wcCity', layer).textContent = primary.home ? (home.name === 'Your time' ? 'Your time' : home.name) : primary.name;
    $('.wc-country', layer).textContent = primary.home ? (home.name === 'Your time' ? '' : 'Your time') : primary.country || '';
    for (const button of layer.querySelectorAll('.wc-seg button')) button.setAttribute('aria-pressed', String((button.dataset.hours === '24') === hour24));
    card.dataset.view = compact ? 'compact' : 'detail';
    card.classList.toggle('many', cities.length >= 4);   // five rows or more: the large clock makes room for them
    $('.wc-view', layer).textContent = compact ? 'Details' : 'Compact';
    $('.wc-view', layer).title = compact ? 'Show the Sun, the facts and the timeline' : 'Show only the times';
  }

  function drawSecond(now) {
    const w = wall(now, primary.tz), text = clockText(w, hour24);
    $('.wc-hm', layer).textContent = text.time;
    $('.wc-half', layer).textContent = text.half;
    $('.wc-sec', layer).textContent = two(w.second);
  }

  function phaseOf(city, now, w) {
    if (located(city)) {
      const height = sunElevation(city.lat, city.lon, now);
      return height > 6 ? 'day' : height < -6 ? 'night' : w.hour < 12 ? 'dawn' : 'dusk';
    }
    return w.hour >= 8 && w.hour < 17 ? 'day' : w.hour >= 5 && w.hour < 8 ? 'dawn' : w.hour >= 17 && w.hour < 20 ? 'dusk' : 'night';
  }

  function drawSun(now, w) {
    const section = $('.wc-sun', layer);
    card.classList.toggle('no-sun', !located(primary));
    if (!located(primary)) return;
    const start = instantOf(primary.tz, w.year, w.month, w.day, 0), dayMs = 86400000;
    const heights = [];
    for (let i = 0; i <= 96; i++) heights.push(sunElevation(primary.lat, primary.lon, start + i * dayMs / 96));
    const scale = 78 / Math.max(25, ...heights);   // the day's highest point sits near the top
    const y = (height) => Math.max(-6, Math.min(156, 100 - height * scale));
    const line = heights.map((height, i) => `${i ? 'L' : 'M'}${(i / 96 * 400).toFixed(1)} ${y(height).toFixed(1)}`).join(' ');
    $('.wc-sun-day', section).setAttribute('d', line);
    $('.wc-sun-night', section).setAttribute('d', line);
    $('.wc-sun-fill', section).setAttribute('d', `${line} L400 100 L0 100 Z`);
    const at = Math.max(0, Math.min(1, (now - start) / dayMs)), height = sunElevation(primary.lat, primary.lon, now);
    const dot = $('.wc-sun-dot', section);
    dot.style.left = `${at * 100}%`;
    dot.style.top = `${Math.max(2, Math.min(96, y(height) / 150 * 100))}%`;
    dot.classList.toggle('down', height < -0.833);
    const events = sunEvents(primary.lat, primary.lon, w.year, w.month, w.day);
    const at12 = (ms) => plainTime(wall(ms, primary.tz), hour24);
    if (events.polar) {
      $('.wc-rise', section).textContent = '';
      $('.wc-set', section).textContent = '';
      $('.wc-daylight', section).textContent = events.polar === 'day' ? 'The Sun stays up all day' : 'The Sun doesn’t rise today';
    } else {
      $('.wc-rise', section).textContent = `Sunrise ${at12(events.sunrise)}`;
      $('.wc-set', section).textContent = `Sunset ${at12(events.sunset)}`;
      $('.wc-daylight', section).textContent = `${span((events.sunset - events.sunrise) / 60000)} of daylight`;
    }
  }

  function drawFacts(now, w) {
    const here = wall(now, home.tz), facts = [];
    const part = w.hour >= 5 && w.hour < 12 ? 'Morning' : w.hour >= 12 && w.hour < 17 ? 'Afternoon' : w.hour >= 17 && w.hour < 21 ? 'Evening' : 'Night';
    facts.push(['Right now', part]);
    if (!primary.home) {
      const gap = offsetMinutes(now, primary.tz) - offsetMinutes(now, home.tz);
      facts.push(['From you', gap === 0 ? 'The same time' : `${gap % 60 ? span(gap) : spanWords(gap)} ${gap > 0 ? 'ahead' : 'behind'}`]);
      const days = dayNumber(w) - dayNumber(here);
      facts.push(['Calendar', days === 0 ? 'The same day as you' : days > 0 ? 'Already tomorrow there' : 'Still yesterday there']);
    }
    const saving = daylightSaving(now, primary.tz);
    facts.push(['Daylight saving', saving === 'on' ? 'On now' : saving === 'off' ? 'Off now (standard time)' : 'Not used here']);
    const midnight = instantOf(primary.tz, w.year, w.month, w.day, 0) + 86400000;
    facts.push(['Midnight', `in ${span(Math.max(1, (midnight - now) / 60000))}`]);
    $('.wc-facts', layer).replaceChildren(...facts.map(([label, value]) => {
      const li = document.createElement('li'), s = document.createElement('span'), b = document.createElement('b');
      s.textContent = label; b.textContent = value; li.append(s, b);
      return li;
    }));
  }

  // One row's strip: 24 hours centred on now, light where the Sun is up there, a band for 9 to 5, a tick at midnight.
  function stripFor(city, now) {
    const from = now - 43200000, pct = (ms) => (ms - from) / 864000;
    const strip = document.createElement('div');
    strip.className = 'wc-strip';
    const w = wall(now, city.tz), today = Date.UTC(w.year, w.month - 1, w.day);
    const days = [-1, 0, 1].map((shift) => { const d = new Date(today + shift * 86400000); return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()]; });
    if (located(city)) {
      const stops = ['var(--wc-night) 0%'];
      let polarDay = false;
      for (const [y, m, d] of days) {
        const events = sunEvents(city.lat, city.lon, y, m, d);
        if (events.polar) { polarDay = polarDay || events.polar === 'day'; continue; }
        const a = pct(events.sunrise), b = pct(events.sunset);
        if (b < 0 || a > 100) continue;
        stops.push(`var(--wc-night) ${(a - 2.2).toFixed(2)}%`, `var(--wc-day) ${(a + 2.2).toFixed(2)}%`, `var(--wc-day) ${(b - 2.2).toFixed(2)}%`, `var(--wc-night) ${(b + 2.2).toFixed(2)}%`);
      }
      strip.style.background = stops.length > 1 ? `linear-gradient(90deg, ${stops.join(', ')}, var(--wc-night) 100%)` : polarDay ? 'var(--wc-day)' : 'var(--wc-night)';
    } else strip.classList.add('unlit');   // no coordinates: no daylight is claimed
    for (const [y, m, d] of days) {
      const open = pct(instantOf(city.tz, y, m, d, 9)), shut = pct(instantOf(city.tz, y, m, d, 17));
      if (shut > 0 && open < 100) {
        const band = document.createElement('i');
        band.className = 'wc-work';
        band.style.left = `${Math.max(0, open)}%`;
        band.style.width = `${Math.min(100, shut) - Math.max(0, open)}%`;
        strip.append(band);
      }
      const midnight = pct(instantOf(city.tz, y, m, d, 0));
      if (midnight > 1 && midnight < 99) {
        const tick = document.createElement('i');
        tick.className = 'wc-midnight';
        tick.style.left = `${midnight}%`;
        tick.dataset.day = formatter(city.tz, 'weekday').format(instantOf(city.tz, y, m, d, 12));
        strip.append(tick);
      }
    }
    return strip;
  }

  function drawRows(now) {
    const list = $('.wc-rows', layer), homeOffset = offsetMinutes(now, home.tz);
    list.replaceChildren(...everyone().map((city) => {
      const li = document.createElement('li');
      li.className = 'wc-row';
      li.dataset.id = idOf(city);
      if (idOf(city) === idOf(primary)) li.setAttribute('aria-current', 'true');
      const pick = document.createElement('button');
      pick.type = 'button';
      pick.className = 'wc-pick';
      pick.title = idOf(city) === idOf(primary) ? '' : `Show ${city.home ? 'your time' : city.name} in the large clock`;
      const name = document.createElement('span'); name.className = 'wc-row-name';
      const b = document.createElement('b'); b.textContent = city.home ? 'You' : city.name;
      const small = document.createElement('small'); small.textContent = city.home ? (home.name === 'Your time' ? '' : home.name) : city.country || '';
      name.append(b, small);
      const time = document.createElement('span'); time.className = 'wc-row-time';
      const gap = document.createElement('span'); gap.className = 'wc-row-gap';
      const minutes = offsetMinutes(now, city.tz) - homeOffset;
      gap.textContent = city.home ? '' : minutes === 0 ? 'same' : `${minutes > 0 ? '+' : '−'}${span(minutes)}`;
      gap.title = city.home ? '' : minutes === 0 ? 'The same time as you' : `${spanWords(minutes)} ${minutes > 0 ? 'ahead of' : 'behind'} you`;
      pick.append(name, time, gap);
      pick.addEventListener('click', () => setPrimary(city));
      li.append(pick, stripFor(city, now));
      if (!city.home) {
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'wc-remove'; remove.innerHTML = ICON.remove;
        remove.title = `Remove ${city.name}`; remove.setAttribute('aria-label', `Remove ${city.name} from the clock`);
        remove.addEventListener('click', () => removeCity(city));
        li.append(remove);
      }
      return li;
    }));
    drawRowTimes(now);
  }

  function drawRowTimes(now) {   // every row's time, now or at the moment the pointer is over
    const moment = now + scrub * 60000, hereDay = dayNumber(wall(moment, home.tz));
    everyone().forEach((city, i) => {
      const row = $('.wc-rows', layer).children[i];
      if (!row) return;
      const w = wall(moment, city.tz), days = dayNumber(w) - hereDay;
      const time = $('.wc-row-time', row);
      time.textContent = plainTime(w, hour24);
      time.dataset.day = days === 0 ? '' : days > 0 ? 'tomorrow' : 'yesterday';
    });
    $('.wc-moment', layer).textContent = scrub === 0 ? 'Now' : scrub > 0 ? `In ${span(scrub)}` : `${span(scrub)} ago`;
    card.classList.toggle('scrubbing', scrub !== 0);
  }

  function drawMinute(now) {
    const w = wall(now, primary.tz);
    $('.wc-date', layer).textContent = formatter(primary.tz, 'date').format(now);
    $('.wc-zone', layer).textContent = `${zoneName(now, primary.tz)} · ${utcLabel(offsetMinutes(now, primary.tz))}`;
    card.dataset.phase = phaseOf(primary, now, w);
    drawSun(now, w);
    drawFacts(now, w);
    drawRows(now);
    placeLines();
  }

  function placeLines() {   // the "now" line through every strip, wherever the layout put them
    const strip = $('.wc-strip', layer), box = $('.wc-compare', layer);
    const line = $('.wc-nowline', layer);
    if (!strip || compact) { line.hidden = true; return; }
    const s = strip.getBoundingClientRect(), b = box.getBoundingClientRect(), rows = $('.wc-rows', layer).getBoundingClientRect();
    line.hidden = false;
    line.style.left = `${s.left - b.left + s.width / 2}px`;
    line.style.top = `${rows.top - b.top}px`;
    line.style.height = `${rows.height}px`;
  }

  function draw(force) {
    const now = Date.now(), second = Math.floor(now / 1000), minute = Math.floor(now / 60000);
    if (force || minute !== drawnMinute) { drawnMinute = minute; drawHead(); drawMinute(now); }
    if (force || second !== drawnSecond) { drawnSecond = second; drawSecond(now); }
  }

  // One timer for the whole window, aimed at the top of each second, and gone when the window closes.
  function start() {
    stop();
    const beat = () => { draw(false); ticker = setTimeout(beat, 1000 - (Date.now() % 1000) + 5); };
    beat();
  }
  function stop() { clearTimeout(ticker); ticker = 0; }

  // ---------- what changes it ----------
  function report() {   // tell the engine what is on the clock, so "remove Tokyo" and "what time is it there" know
    window.jarvisSend?.({ type: 'clock_cities', open: !layer.hidden,
      cities: cities.map(({ name, country, tz, lat, lon }) => ({ name, country, tz, lat, lon })) });
  }
  function remember(city) {
    const recent = [city, ...store.get('jarvis-clock-recent', []).filter((c) => c && idOf(c) !== idOf(city))].slice(0, 8);
    store.set('jarvis-clock-recent', recent.map(({ name, country, tz, lat, lon }) => ({ name, country, tz, lat, lon })));
  }
  function drawRecent() {
    const shown = new Set(cities.map(idOf));
    const recent = store.get('jarvis-clock-recent', []).filter((c) => c && c.name && validZone(c.tz) && !shown.has(idOf(c))).slice(0, 4);
    $('.wc-recent', layer).replaceChildren(...recent.map((city) => {
      const chip = document.createElement('button');
      const twin = recent.some((other) => other !== city && other.name === city.name) || cities.some((c) => c.name === city.name);
      chip.type = 'button'; chip.className = 'wc-chip'; chip.textContent = twin && city.country ? `${city.name}, ${city.country}` : city.name;
      chip.title = `Add ${city.name}${city.country ? ', ' + city.country : ''} again`;
      chip.addEventListener('click', () => { addCities([city]); note(''); });
      return chip;
    }));
  }
  function validZone(tz) { try { formatter(tz, 'parts'); return Boolean(tz); } catch (e) { return false; } }
  function note(message, options) {
    const p = $('.wc-note', layer);
    p.replaceChildren(document.createTextNode(message || ''));
    for (const option of options || []) {
      const choose = document.createElement('button');
      choose.type = 'button'; choose.className = 'wc-chip';
      choose.textContent = option.country ? `${option.name}, ${option.country}` : option.name;
      choose.addEventListener('click', () => { addCities([option]); note(''); });
      p.append(choose);
    }
  }
  function addCities(list, { replace = false, focus = 0 } = {}) {
    const incoming = (list || []).filter((c) => c && c.name && !c.home && validZone(c.tz));
    if (replace) cities = [];
    let first = null, full = false;
    for (const city of incoming) {
      let have = cities.find((c) => idOf(c) === idOf(city));
      if (!have) {
        if (cities.length >= MAX_CITIES) { full = true; continue; }
        have = { name: String(city.name), country: String(city.country || ''), tz: city.tz,
          lat: typeof city.lat === 'number' ? city.lat : null, lon: typeof city.lon === 'number' ? city.lon : null };
        cities.push(have);
        remember(have);
      }
      first = first || have;
    }
    if (replace) primary = focus === -1 ? home : cities[Math.max(0, Math.min(focus, cities.length - 1))] || home;
    else if (first) primary = first;
    if (full) note(`The clock holds ${MAX_CITIES} places. Remove one to add another.`);
    refresh(true);
  }
  function removeCity(city) {
    cities = cities.filter((c) => c !== city);
    if (primary === city) primary = cities[0] || home;
    note('');
    refresh(true);
  }
  function setPrimary(city) {
    if (idOf(city) === idOf(primary)) return;
    primary = city;
    refresh(true);
  }
  function refresh(swap) {
    scrub = 0;
    drawRecent();
    if (layer.hidden) return;
    draw(true);
    if (swap) { const main = $('.wc-top', layer); main.classList.remove('swap'); void main.offsetWidth; main.classList.add('swap'); }
    report();
  }

  function open() {
    clearTimeout(closeTimer);
    layer.classList.remove('closing');
    if (layer.hidden) {
      window.hideGraph?.(); window.hideGlobe?.(); window.hidePlanet?.(); window.weatherPanel?.close?.();   // one window at a time
      layer.hidden = false;
      card.focus({ preventScroll: true });
    }
    start();
    draw(true);
    report();
  }
  function close() {
    if (layer.hidden || layer.classList.contains('closing')) return;
    stop();
    layer.classList.add('closing');
    closeTimer = setTimeout(() => { layer.hidden = true; layer.classList.remove('closing'); report(); }, 220);
  }

  // Your own row is this computer's time zone. It takes the name and coordinates of the weather city only when that
  // city really is on this computer's time (someone travelling keeps a true clock, just without a name on it).
  function setHome(place) {
    if (!place) return;
    const here = validZone(place.tz) && offsetMinutes(Date.now(), place.tz) === offsetMinutes(Date.now(), browserZone);
    home = here && place.name
      ? { ...home, name: place.name, lat: typeof place.lat === 'number' ? place.lat : null, lon: typeof place.lon === 'number' ? place.lon : null }
      : { ...home, name: 'Your time', lat: null, lon: null };
    if (primary.home) primary = home;
  }

  // ---------- from the backend ----------
  window.addEventListener('jarvis-message', (event) => {
    const msg = event.detail || {};
    if (msg.type === 'clock' && msg.data) {
      const data = msg.data;
      setHome(data.home);
      clearTimeout(pendingAdd);
      card.classList.remove('adding');
      if (data.mode === 'remove') {
        const gone = new Set((data.cities || []).map(idOf));
        const wasPrimary = gone.has(idOf(primary));
        cities = cities.filter((c) => !gone.has(idOf(c)));
        if (wasPrimary) primary = cities[0] || home;
        refresh(true);
        return;
      }
      note('');
      const wasHidden = layer.hidden;
      addCities(data.cities, { replace: data.mode !== 'add', focus: typeof data.focus === 'number' ? data.focus : 0 });
      if (data.mode === 'add' && $('.wc-add input', layer).value) $('.wc-add input', layer).value = '';
      if (wasHidden || layer.classList.contains('closing')) open();
    } else if (msg.type === 'clock_note') {
      clearTimeout(pendingAdd);
      card.classList.remove('adding');
      note(msg.message || '', msg.options);
    } else if (msg.type === 'close_clock') close();
  });

  // ---------- controls ----------
  $('.wc-close', layer).addEventListener('click', close);
  $('.wc-view', layer).addEventListener('click', () => { compact = !compact; store.set('jarvis-clock-compact', compact); draw(true); });
  $('.wc-seg', layer).addEventListener('click', (e) => {
    const button = e.target.closest('button');
    if (!button) return;
    hour24 = button.dataset.hours === '24';
    store.set('jarvis-clock-24h', hour24);
    draw(true);
  });
  $('.wc-copy', layer).addEventListener('click', async () => {
    const now = Date.now(), w = wall(now, primary.tz);
    const text = `${plainTime(w, hour24)}, ${formatter(primary.tz, 'date').format(now)} in ${primary.home ? 'my time zone' : primary.name} (${utcLabel(offsetMinutes(now, primary.tz))})`;
    let done = false;
    try { require('electron').clipboard.writeText(text); done = true; } catch (e) { /* not in Electron: the browser's own */ }
    if (!done) { try { await navigator.clipboard.writeText(text); done = true; } catch (e) { done = false; } }
    const button = $('.wc-copy', layer);
    button.innerHTML = done ? `${ICON.check}<span>Copied</span>` : `${ICON.copy}<span>Couldn’t copy</span>`;
    button.dataset.copied = text;
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => { button.innerHTML = `${ICON.copy}<span>Copy time</span>`; }, 1600);
  });
  $('.wc-add', layer).addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('.wc-add input', layer), name = input.value.trim();
    if (!name) { input.focus(); return; }
    if (cities.length >= MAX_CITIES) { note(`The clock holds ${MAX_CITIES} places. Remove one to add another.`); return; }
    if (!window.jarvisSend?.({ type: 'clock_add', name })) { note('Jarvis’s engine isn’t connected, so I can’t look that place up right now.'); return; }
    note(`Looking for ${name}…`);
    card.classList.add('adding');
    clearTimeout(pendingAdd);
    pendingAdd = setTimeout(() => { card.classList.remove('adding'); note('That took too long. Check the connection and try again.'); }, 15000);
  });
  layer.addEventListener('mousedown', (e) => { if (e.target === layer) close(); });
  window.addEventListener('keydown', (e) => {   // capture: before the window's own Escape (which leaves full screen)
    if (e.key === 'Escape' && !layer.hidden) { e.preventDefault(); e.stopImmediatePropagation(); close(); }
  }, true);

  // Move over the strips (or use the arrow keys on them) to read every place's time at another moment.
  const compare = $('.wc-compare', layer);
  function scrubTo(minutes) {
    scrub = Math.max(-720, Math.min(720, Math.round(minutes / 15) * 15));
    drawRowTimes(Date.now());
    const strip = $('.wc-strip', layer), line = $('.wc-scrubline', layer);
    if (!strip || scrub === 0) { line.hidden = true; return; }
    const s = strip.getBoundingClientRect(), b = compare.getBoundingClientRect(), rows = $('.wc-rows', layer).getBoundingClientRect();
    line.hidden = false;
    line.style.left = `${s.left - b.left + s.width * (0.5 + scrub / 1440)}px`;
    line.style.top = `${rows.top - b.top}px`;
    line.style.height = `${rows.height}px`;
  }
  compare.addEventListener('pointermove', (e) => {
    const strip = e.target.closest('.wc-strip');
    if (!strip) { if (scrub) scrubTo(0); return; }
    const box = strip.getBoundingClientRect();
    scrubTo(((e.clientX - box.left) / box.width - 0.5) * 1440);
  });
  compare.addEventListener('pointerleave', () => scrubTo(0));
  $('.wc-rows', layer).tabIndex = 0;
  $('.wc-rows', layer).setAttribute('aria-label', 'Timeline: use the left and right arrow keys to look at another moment');
  $('.wc-rows', layer).addEventListener('keydown', (e) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); scrubTo(scrub + (e.key === 'ArrowRight' ? 15 : -15) * (e.shiftKey ? 4 : 1)); }
    else if (e.key === 'Home' || e.key === '0') { e.preventDefault(); scrubTo(0); }
  });
  $('.wc-rows', layer).addEventListener('blur', () => scrubTo(0));
  new ResizeObserver(() => { if (!layer.hidden) placeLines(); }).observe(card);

  window.hideClock = () => { if (!layer.hidden) close(); };
  window.clockOpen = () => !layer.hidden && !layer.classList.contains('closing');
  window.worldClock = { open, close, add: addCities, isOpen: window.clockOpen,   // the same maths, for tests
    math: { wall, offsetMinutes, instantOf, daylightSaving, utcLabel, sunEvents, sunElevation } };
})();
