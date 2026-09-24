document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const app = $('appShell');
  const chatLog = $('chatLog');
  const connectBtn = $('connectBtn');
  const RING_LENGTH = 163.4;   // circumference of the gauge circles (r = 26)
  const SPARK_POINTS = 60;     // 60 samples at 2 s each = 2 minutes
  const TOGGLE_GRACE_MS = 800; // ignore stale mute/unmute echoes from the server after a click

  const STATES = {
    idle:      { title: 'Ready',            sub: 'I’m listening. Just say what you need.' },
    sleeping:  { title: 'Sleeping',         sub: 'Say “Hey Jervis” or “Wake up Jervis” to wake me.' },
    listening: { title: 'Listening…',       sub: 'Go ahead, I’m all ears.' },
    thinking:  { title: 'Thinking…',        sub: 'Working on it.' },
    speaking:  { title: 'Speaking',         sub: 'Press the stop button, or Space, to make me listen.' },
    muted:     { title: 'Muted',            sub: 'The microphone is off. Press M to turn it back on.' },
    generating:{ title: 'Creating…',        sub: 'Working on your image — this can take up to a minute.' },
  };

  let socket = null;
  let reconnectTimer = null;
  let isMuted = false;
  let toggledAt = 0;
  let messageCount = 0;
  let typingEl = null;
  let captionTimer = null;
  const startedAt = Date.now();
  const cpuHistory = [];

  if (/Mac/i.test(navigator.userAgent)) app.classList.add('is-mac');

  // ---------- Clock + uptime ----------
  const pad = (n) => String(n).padStart(2, '0');
  function updateClock() {
    const now = new Date();
    $('clockValue').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    $('dateValue').textContent = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    const s = Math.floor((now - startedAt) / 1000);
    $('uptimeText').textContent = s >= 3600
      ? `${Math.floor(s / 3600)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`
      : `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
  }

  // ---------- Connection ----------
  function setConnection(connected) {
    app.classList.toggle('is-connected', connected);
    $('connectionText').textContent = connected ? 'Connected' : 'Reconnecting…';
  }
  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connectSocket(); }, 1500);
  }
  function connectSocket() {
    if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;
    setConnection(false);
    try {
      socket = new WebSocket(new URLSearchParams(location.search).get('ws') || 'ws://127.0.0.1:8765');
      socket.onopen = () => { setConnection(true); window.dispatchEvent(new CustomEvent('jervis-connected')); };
      socket.onclose = () => { setConnection(false); scheduleReconnect(); };
      socket.onerror = () => setConnection(false);
      socket.onmessage = handleMessage;
    } catch (error) {
      console.error('WebSocket setup error:', error);
      scheduleReconnect();
    }
  }

  // ---------- Assistant state ----------
  // Change an element's text with a short fade-and-lift, only when the text actually differs.
  function swapText(el, text) {
    if (el.textContent === text) return;
    el.textContent = text;
    el.classList.remove('swap');
    void el.offsetWidth;   // restart the animation
    el.classList.add('swap');
  }

  function setState(rawState) {
    let state = String(rawState || 'idle').toLowerCase();
    if (!STATES[state]) state = 'idle';
    const fresh = Date.now() - toggledAt < TOGGLE_GRACE_MS;
    if (fresh && ((isMuted && state !== 'muted') || (!isMuted && state === 'muted'))) return;
    if (state === 'muted' && !isMuted) applyMute(true, false);

    app.dataset.state = state;
    swapText($('stateTitle'), STATES[state].title);
    swapText($('stateSub'), STATES[state].sub);
    if (window.setOrbState) window.setOrbState(state);
    (state === 'thinking' || state === 'generating') ? showTyping() : hideTyping();
  }

  // ---------- System stats ----------
  function setRing(id, valueId, value) {
    const v = Math.max(0, Math.min(100, Number(value)));
    $(id).style.strokeDashoffset = RING_LENGTH * (1 - v / 100);
    $(valueId).textContent = `${Math.round(v)}%`;
  }
  function drawSpark() {
    const step = 120 / (SPARK_POINTS - 1);
    const offset = (SPARK_POINTS - cpuHistory.length) * step;
    const pts = cpuHistory.map((v, i) => `${(offset + i * step).toFixed(1)},${(30 - (v / 100) * 28).toFixed(1)}`);
    $('sparkLine').setAttribute('points', pts.join(' '));
    $('sparkArea').setAttribute('d', pts.length > 1 ? `M${pts[0]} L${pts.join(' L')} L120,32 L${pts[0].split(',')[0]},32 Z` : '');
    $('cpuPeak').textContent = `peak ${Math.round(Math.max(...cpuHistory))}%`;
  }
  function updateStats({ cpu, ram, battery }) {
    if (cpu !== undefined) {
      setRing('cpuRing', 'cpuVal', cpu);
      cpuHistory.push(cpu);
      if (cpuHistory.length > SPARK_POINTS) cpuHistory.shift();
      drawSpark();
    }
    if (ram !== undefined) setRing('ramRing', 'ramVal', ram);
    if (battery !== undefined) setRing('batteryRing', 'batteryVal', battery);
    const hot = Math.max(cpu || 0, ram || 0);
    const badge = $('healthBadge');
    badge.className = `badge ${hot > 90 ? 'bad' : hot > 75 ? 'warn' : 'ok'}`;
    badge.textContent = hot > 90 ? 'Under load' : hot > 75 ? 'Busy' : 'Optimal';
  }
  // ---------- Timer alert: a square card with a soft, repeating chime ----------
  const { ipcRenderer } = require('electron');
  ipcRenderer.on('fullscreen-state', (_event, on) => app.classList.toggle('is-full', on));
  const alerts = [];
  let audioCtx = null;
  let chimeTimer = null;
  let chimeUntil = 0;

  function playChime() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const now = audioCtx.currentTime;
      // A gentle rising bell: E5 - G#5 - B5 - E6, each a sine with a quiet octave partial and a long decay.
      [659.25, 830.61, 987.77, 1318.51].forEach((freq, i) => {
        const start = now + i * 0.17;
        [[freq, 0.2], [freq * 2, 0.05]].forEach(([f, peak]) => {
          const osc = audioCtx.createOscillator();
          const gain = audioCtx.createGain();
          osc.type = 'sine';
          osc.frequency.value = f;
          gain.gain.setValueAtTime(0.0001, start);
          gain.gain.exponentialRampToValueAtTime(peak, start + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.0001, start + 1.7);
          osc.connect(gain).connect(audioCtx.destination);
          osc.start(start);
          osc.stop(start + 1.8);
        });
      });
    } catch (error) {
      console.error('Chime failed:', error);
    }
  }
  function startChime() {
    stopChime();
    chimeUntil = Date.now() + 2 * 60 * 1000;   // keep gently repeating for two minutes
    playChime();
    chimeTimer = setInterval(() => {
      if (Date.now() > chimeUntil) return stopChime();
      playChime();
    }, 5000);
  }
  function stopChime() {
    clearInterval(chimeTimer);
    chimeTimer = null;
  }

  function renderAlert() {
    const layer = $('alertLayer');
    const current = alerts[0];
    layer.hidden = !current;
    if (!current) return stopChime();
    const reminder = current.kind === 'reminder';
    $('alertKicker').textContent = reminder ? 'Reminder' : 'Timer';
    $('alertTitle').textContent = reminder && current.label ? current.label : 'Time’s up';
    $('alertSub').textContent = reminder
      ? (current.label ? 'Time’s up' : '')
      : `${current.label ? current.label + ' · ' : ''}${describeDuration(current.total)}`;
    $('alertSnooze').hidden = false;
    $('alertMore').hidden = alerts.length < 2;
    $('alertMore').textContent = `+${alerts.length - 1} more`;
    $('alertDismiss').focus();
  }
  function describeDuration(seconds) {
    const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    return [h && `${h} hour${h > 1 ? 's' : ''}`, m && `${m} minute${m > 1 ? 's' : ''}`, s && `${s} second${s > 1 ? 's' : ''}`]
      .filter(Boolean).join(' ') || '0 seconds';
  }
  function showAlert(data) {
    alerts.push(data);
    renderAlert();
    startChime();
    ipcRenderer.send('alert-focus');
  }
  function dismissAlert(count = 1) {
    alerts.splice(0, count);
    renderAlert();
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'alert_dismissed', count }));
    if (alerts.length) startChime();
  }
  $('alertDismiss').addEventListener('click', () => dismissAlert());
  $('alertSnooze').addEventListener('click', () => {
    const current = alerts[0];
    if (current && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'snooze', seconds: 300, label: current.label, kind: current.kind }));
    }
    dismissAlert();
  });
  const typing = (e) => e.target && e.target.tagName === 'INPUT';   // shortcuts must not fire while typing
  document.addEventListener('keydown', (e) => {
    if (!alerts.length || typing(e)) return;
    if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); dismissAlert(); }
    if (e.key.toLowerCase() === 's' && !e.metaKey && !e.ctrlKey) $('alertSnooze').click();
  });

  // ---------- Timers ----------
  let timers = [];
  function formatRemaining(ms) {
    const s = Math.max(0, Math.ceil(ms / 1000));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
  }
  function renderTimers() {
    const card = $('timersCard');
    const list = $('timerList');
    card.hidden = timers.length === 0;
    $('timerCount').textContent = String(timers.length);
    while (list.children.length > timers.length) list.lastChild.remove();
    timers.forEach((t, i) => {
      let li = list.children[i];
      if (!li) {
        li = document.createElement('li');
        li.className = 'timer-item';
        li.innerHTML = '<div class="timer-top"><span class="timer-name"></span><span class="timer-time"></span></div><div class="timer-bar"><i></i></div>';
        list.appendChild(li);
      }
      const left = t.end - Date.now();
      li.classList.toggle('done', left <= 0);
      li.querySelector('.timer-name').textContent = t.label || (t.kind === 'reminder' ? 'Reminder' : 'Timer');
      li.querySelector('.timer-time').textContent = formatRemaining(left);
      li.querySelector('.timer-bar i').style.width = `${Math.max(0, Math.min(100, (left / (t.total * 1000)) * 100))}%`;
    });
  }
  function setTimers(data) {
    timers = Array.isArray(data) ? data : [];
    renderTimers();
  }

  // Weather icons (fixed SVG strings, never built from server text) chosen by the words in the condition.
  const WX = {
    sun: '<circle cx="24" cy="24" r="8" fill="#ffd166"/><g stroke="#ffd166" stroke-width="2.4" stroke-linecap="round"><path d="M24 6v5M24 37v5M6 24h5M37 24h5M11.3 11.3l3.5 3.5M33.2 33.2l3.5 3.5M11.3 36.7l3.5-3.5M33.2 14.8l3.5-3.5"/></g>',
    cloud: '<path d="M14 34a8 8 0 0 1-1-15.9A11 11 0 0 1 34 16a9 9 0 0 1 1 18z" fill="#9db4d9" fill-opacity=".9"/>',
    partly: '<circle cx="17" cy="17" r="6" fill="#ffd166"/><g stroke="#ffd166" stroke-width="2" stroke-linecap="round"><path d="M17 5v3M5 17h3M8.5 8.5l2 2M25.5 8.5l-2 2"/></g><path d="M16 38a7 7 0 0 1-1-13.9A10 10 0 0 1 34 23a8 8 0 0 1 1 15z" fill="#9db4d9" fill-opacity=".92"/>',
    rain: '<path d="M14 29a8 8 0 0 1-1-15.9A11 11 0 0 1 34 11a9 9 0 0 1 1 18z" fill="#8aa2c8"/><g stroke="#4fd8ff" stroke-width="2.4" stroke-linecap="round"><path d="M16 35l-2 6M25 35l-2 6M34 35l-2 6"/></g>',
    storm: '<path d="M14 27a8 8 0 0 1-1-15.9A11 11 0 0 1 34 9a9 9 0 0 1 1 18z" fill="#6f83a8"/><path d="M26 28l-6 9h5l-3 8 9-11h-5z" fill="#ffd166"/>',
    snow: '<path d="M14 29a8 8 0 0 1-1-15.9A11 11 0 0 1 34 11a9 9 0 0 1 1 18z" fill="#b6c6e2"/><g fill="#eaf6ff"><circle cx="16" cy="37" r="2"/><circle cx="25" cy="41" r="2"/><circle cx="34" cy="37" r="2"/></g>',
    fog: '<g stroke="#9db4d9" stroke-width="3" stroke-linecap="round"><path d="M10 16h28M6 24h32M12 32h30M8 40h24"/></g>',
  };
  function weatherIcon(condition) {
    const c = String(condition || '').toLowerCase();
    if (/thunder|storm/.test(c)) return 'storm';
    if (/snow|sleet|ice|blizzard/.test(c)) return 'snow';
    if (/rain|drizzle|shower/.test(c)) return 'rain';
    if (/fog|mist|haze|smoke/.test(c)) return 'fog';
    if (/partly|few clouds|scattered|mostly sunny/.test(c)) return 'partly';
    if (/cloud|overcast/.test(c)) return 'cloud';
    return 'sun';
  }
  function updateWeather({ city, temp, condition }) {
    if (city) $('cityValue').textContent = city;
    if (temp !== undefined) $('tempValue').textContent = temp;
    if (condition) {
      $('weatherCond').textContent = condition;
      $('wxIcon').innerHTML = WX[weatherIcon(condition)];
    }
  }

  // ---------- Math: LaTeX between $...$ (inline) or $$...$$ (own line) is typeset with KaTeX ----------
  // KaTeX is a bundled file (vendor/katex), so it works offline. Loaded with require because this window has Node
  // enabled, which stops a plain <script> from defining the global. If it is missing, the raw formula is shown.
  let katex = null;
  try { katex = require('./vendor/katex/katex.min.js'); } catch (error) { console.warn('Math typesetting unavailable:', error.message); }
  function typeset(tex, display) {
    const el = document.createElement(display ? 'div' : 'span');
    el.className = display ? 'md-math' : 'md-math-inline';
    try {
      if (!katex) throw new Error('no katex');
      katex.render(tex, el, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore' });
    } catch (error) {
      el.textContent = tex;
    }
    return el;
  }

  // ---------- Markdown for the chat (built with DOM nodes only, so replies can never inject HTML) ----------
  function inlineMarkdown(text, parent) {
    const pattern = /(\$\$[^$]+\$\$|\$(?=\S)[^$\n]*?\S\$(?!\d)|\$[^\s$]\$(?!\d)|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*)/g;
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > last) parent.append(text.slice(last, match.index));
      const token = match[0];
      if (token.startsWith('$')) {
        parent.append(typeset(token.replace(/^\$\$?|\$\$?$/g, '').trim(), false));
        last = match.index + token.length;
        continue;
      }
      const el = document.createElement(token.startsWith('`') ? 'code' : token.startsWith('**') || token.startsWith('__') ? 'strong' : 'em');
      el.textContent = token.startsWith('**') || token.startsWith('__') ? token.slice(2, -2) : token.slice(1, -1);
      parent.append(el);
      last = match.index + token.length;
    }
    if (last < text.length) parent.append(text.slice(last));
  }
  function splitRow(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
  }
  function renderMarkdown(source) {
    const root = document.createElement('div');
    root.className = 'md';
    // \( ... \) and \[ ... \] are another way of writing formulas: turn them into $ ... $ and $$ ... $$ first.
    source = String(source)
      .replace(/\\\[\s*([\s\S]+?)\s*\\\]/g, (_m, tex) => `\n$$${tex.trim()}$$\n`)
      .replace(/\\\(\s*([\s\S]+?)\s*\\\)/g, (_m, tex) => `$${tex.trim()}$`);
    const lines = source.replace(/\r/g, '').split('\n');
    const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l || '') && (l || '').includes('-');
    const isBlock = (l) => /^\s*(#{1,6}\s|[-*•]\s|\d+[.)]\s|```|\||>\s?|\$\$|-{3,}\s*$)/.test(l);
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (/^\s*```/.test(line)) {
        const code = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
        i++;
        const pre = document.createElement('pre');
        pre.textContent = code.join('\n');
        root.append(pre);
        continue;
      }
      if (/^\s*-{3,}\s*$/.test(line)) {   // --- : a divider between two answers
        const rule = document.createElement('hr');
        rule.className = 'md-rule';
        root.append(rule);
        i++;
        continue;
      }
      const display = line.match(/^\s*\$\$(.+)\$\$\s*$/);
      if (display) {   // a formula on its own line: centred and larger
        root.append(typeset(display[1].trim(), true));
        i++;
        continue;
      }
      if (/^\s*\$\$\s*$/.test(line)) {   // $$ on one line, the formula below, $$ to close
        const tex = [];
        for (i++; i < lines.length && !/^\s*\$\$\s*$/.test(lines[i]); i++) tex.push(lines[i]);
        i++;
        root.append(typeset(tex.join(' ').trim(), true));
        continue;
      }
      if (/^\s*>\s?/.test(line)) {   // "> ..." is a highlighted callout (used for the final answer of a calculation)
        const box = document.createElement('div');
        box.className = 'md-answer';
        const chunk = [];
        for (; i < lines.length && /^\s*>\s?/.test(lines[i]); i++) chunk.push(lines[i].replace(/^\s*>\s?/, '').trim());
        chunk.forEach((text, n) => { if (n) box.append(document.createElement('br')); inlineMarkdown(text, box); });
        root.append(box);
        continue;
      }
      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
      if (heading) {
        const h = document.createElement('h4');
        inlineMarkdown(heading[2], h);
        root.append(h);
        i++;
        continue;
      }
      if (/^\s*\|/.test(line) && isTableSep(lines[i + 1])) {
        const wrap = document.createElement('div');
        wrap.className = 'md-table';
        const table = document.createElement('table');
        const head = document.createElement('thead');
        const headRow = document.createElement('tr');
        splitRow(line).forEach((cell) => { const th = document.createElement('th'); inlineMarkdown(cell, th); headRow.append(th); });
        head.append(headRow);
        const body = document.createElement('tbody');
        for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i++) {
          const row = document.createElement('tr');
          splitRow(lines[i]).forEach((cell) => { const td = document.createElement('td'); inlineMarkdown(cell, td); row.append(td); });
          body.append(row);
        }
        table.append(head, body);
        wrap.append(table);
        root.append(wrap);
        continue;
      }
      const bullet = /^\s*[-*•]\s+/;
      const numbered = /^\s*\d+[.)]\s+/;
      if (bullet.test(line) || numbered.test(line)) {
        const ordered = numbered.test(line);
        const list = document.createElement(ordered ? 'ol' : 'ul');
        const marker = ordered ? numbered : bullet;
        if (ordered) list.start = parseInt(line, 10) || 1;
        for (; i < lines.length && marker.test(lines[i]); i++) {
          const li = document.createElement('li');
          inlineMarkdown(lines[i].replace(marker, ''), li);
          list.append(li);
        }
        root.append(list);
        continue;
      }
      const p = document.createElement('p');
      const chunk = [];
      for (; i < lines.length && lines[i].trim() && !isBlock(lines[i]); i++) chunk.push(lines[i].trim());
      chunk.forEach((text, n) => { if (n) p.append(document.createElement('br')); inlineMarkdown(text, p); });
      root.append(p);
    }
    return root;
  }
  // Plain text for the caption above the mic: no symbols or table rows.
  function plainText(source) {
    return String(source).split('\n')
      .filter((l) => l.trim() && !/^\s*\|/.test(l) && !/^\s*```/.test(l) && !/^\s*(#{1,6}\s|>?\s*\$)/.test(l))
      .map((l) => l.replace(/^\s*(#{1,6}|[-*•]|>|\d+[.)])\s*/, '').replace(/\*\*|__|`/g, ''))
      .join(' ');
  }

  // ---------- Conversation ----------
  function showEmpty() {
    chatLog.replaceChildren($('emptyTpl').content.cloneNode(true));
  }
  function updateCount() {
    $('msgCount').textContent = `${messageCount} message${messageCount === 1 ? '' : 's'}`;
  }
  function showTyping() {
    if (typingEl) return;
    $('emptyChat')?.remove();
    typingEl = document.createElement('div');
    typingEl.className = 'typing';
    typingEl.innerHTML = '<i></i><i></i><i></i>';
    chatLog.appendChild(typingEl);
    chatLog.scrollTop = chatLog.scrollHeight;
  }
  function hideTyping() {
    typingEl?.remove();
    typingEl = null;
  }
  function showCaption(isUser, text) {
    $('capLabel').textContent = isUser ? 'You said' : 'Jervis';
    $('capText').textContent = text;
    $('caption').classList.add('show');
    clearTimeout(captionTimer);
    captionTimer = setTimeout(() => $('caption').classList.remove('show'), 9000);
  }
  // ---------- Graphs in the conversation: a small picture you can click to open the graph again, as often as you like ----------
  const pendingGraphs = [];
  let graphChipTimer = null;
  function makeGraphChip(d) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'graph-chip';
    chip.title = 'Open this graph again';
    const picture = document.createElement('canvas');
    const label = document.createElement('span');
    label.className = 'chip-text';
    const kicker = document.createElement('small');
    kicker.textContent = 'Graph';
    const name = document.createElement('b');
    name.textContent = d.plain;
    const hint = document.createElement('em');
    hint.textContent = 'Click to open again';
    label.append(kicker, name, hint);
    chip.append(picture, label);
    chip.addEventListener('click', () => window.showGraph?.(d));
    requestAnimationFrame(() => window.graphThumbnail?.(picture, d));
    return chip;
  }
  const pendingPlanets = [];
  let planetChipTimer = null;
  function makePlanetChip(d) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'graph-chip globe-chip';
    chip.title = 'Open this model again';
    const picture = document.createElement('canvas');
    const label = document.createElement('span');
    label.className = 'chip-text';
    const kicker = document.createElement('small');
    kicker.textContent = d.bodyKind.charAt(0).toUpperCase() + d.bodyKind.slice(1);
    const name = document.createElement('b');
    name.textContent = d.name;
    const hint = document.createElement('em');
    hint.textContent = 'Click to open again';
    label.append(kicker, name, hint);
    chip.append(picture, label);
    chip.addEventListener('click', () => window.showPlanet?.(d));
    requestAnimationFrame(() => window.planetThumbnail?.(picture, d));
    return chip;
  }
  function queuePlanetChip(d) {
    pendingPlanets.push(d);
    clearTimeout(planetChipTimer);
    planetChipTimer = setTimeout(() => {
      if (!pendingPlanets.length) return;
      $('emptyChat')?.remove();
      const wrap = document.createElement('article');
      wrap.className = 'msg jervis';
      pendingPlanets.splice(0).forEach((p) => wrap.append(makePlanetChip(p)));
      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }, 2500);
  }

  const pendingGlobes = [];
  let globeChipTimer = null;
  function makeGlobeChip(d) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'graph-chip globe-chip';
    chip.title = 'Open this globe again';
    const picture = document.createElement('canvas');
    const label = document.createElement('span');
    label.className = 'chip-text';
    const kicker = document.createElement('small');
    kicker.textContent = 'Globe';
    const name = document.createElement('b');
    name.textContent = `${d.a.name} \u2192 ${d.b.name}`;
    const hint = document.createElement('em');
    hint.textContent = `${d.km.toLocaleString()} km \u00b7 click to open again`;
    label.append(kicker, name, hint);
    chip.append(picture, label);
    chip.addEventListener('click', () => window.showGlobe?.(d));
    requestAnimationFrame(() => window.globeThumbnail?.(picture, d));
    return chip;
  }
  function queueGlobeChip(d) {
    pendingGlobes.push(d);
    clearTimeout(globeChipTimer);
    globeChipTimer = setTimeout(() => {
      if (!pendingGlobes.length) return;
      $('emptyChat')?.remove();
      const wrap = document.createElement('article');
      wrap.className = 'msg jervis';
      pendingGlobes.splice(0).forEach((g) => wrap.append(makeGlobeChip(g)));
      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }, 2500);
  }

  function queueGraphChip(d) {
    pendingGraphs.push(d);
    clearTimeout(graphChipTimer);
    // Normally the answer text arrives right after and carries the picture; if not, show it on its own.
    graphChipTimer = setTimeout(() => {
      if (!pendingGraphs.length) return;
      $('emptyChat')?.remove();
      const wrap = document.createElement('article');
      wrap.className = 'msg jervis';
      pendingGraphs.splice(0).forEach((g) => wrap.append(makeGraphChip(g)));
      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }, 2500);
  }

  // ---------- Images in the conversation: attached by the user, or generated/edited by Jervis ----------
  const IMAGE_KIND_LABEL = { upload: 'Attached image', generated: 'Generated image', edited: 'Edited image' };
  function openLightbox(src) {
    $('lightboxImg').src = src;
    $('lightbox').hidden = false;
  }
  $('lightbox').addEventListener('click', () => { $('lightbox').hidden = true; });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('lightbox').hidden) $('lightbox').hidden = true;
  });
  function makeImageFigure(src, kind) {
    const fig = document.createElement('figure');
    fig.className = 'msg-image';
    const img = document.createElement('img');
    img.src = src;
    img.alt = IMAGE_KIND_LABEL[kind] || 'Image';
    img.loading = 'lazy';
    img.addEventListener('click', () => openLightbox(src));
    fig.append(img);
    if (kind && kind !== 'upload') {
      const cap = document.createElement('figcaption');
      cap.textContent = IMAGE_KIND_LABEL[kind];
      fig.append(cap);
    }
    return fig;
  }

  function appendChatMessage(sender, text, image, imageKind) {
    const isUser = sender === 'user';
    $('emptyChat')?.remove();
    hideTyping();
    const msg = document.createElement('article');
    msg.className = `msg ${isUser ? 'user' : 'jervis'}`;
    const meta = document.createElement('small');
    meta.textContent = `${isUser ? 'You' : 'Jervis'} · ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    msg.append(meta);
    if (image) msg.append(makeImageFigure(image, imageKind));
    if (text && text.trim()) {
      const body = isUser ? document.createElement('p') : document.createElement('div');
      if (isUser) body.textContent = text;
      else { body.className = 'bubble'; body.append(renderMarkdown(text)); }
      msg.append(body);
    }
    if (!isUser && (pendingGraphs.length || pendingGlobes.length || pendingPlanets.length)) {
      clearTimeout(graphChipTimer);
      clearTimeout(globeChipTimer);
      clearTimeout(planetChipTimer);
      const holder = document.createElement('div');
      holder.className = 'chips';
      pendingGraphs.splice(0).forEach((g) => holder.append(makeGraphChip(g)));
      pendingGlobes.splice(0).forEach((g) => holder.append(makeGlobeChip(g)));
      pendingPlanets.splice(0).forEach((p) => holder.append(makePlanetChip(p)));
      msg.append(holder);
    }
    chatLog.appendChild(msg);
    chatLog.scrollTop = chatLog.scrollHeight;
    messageCount += 1;
    updateCount();
    const captionText = text && text.trim() ? (isUser ? text : plainText(text)) : (image ? (IMAGE_KIND_LABEL[imageKind] || 'Sent an image') : '');
    if (captionText) showCaption(isUser, captionText);
    if (isUser && app.dataset.state === 'thinking') showTyping();
  }

  // Other scripts (panels.js: setup, settings, computer control) talk to the backend through these two.
  window.jervisSend = (payload) => {
    if (socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  };

  function handleMessage(event) {
    try {
      const data = JSON.parse(event.data);
      window.dispatchEvent(new CustomEvent('jervis-message', { detail: data }));
      if (data.sender && (data.text || data.image)) appendChatMessage(data.sender, data.text || '', data.image, data.imageKind);
      if (data.status) setState(data.status);
      if (data.type === 'system_stats' && data.data) updateStats(data.data);
      if (data.type === 'weather' && data.data) updateWeather(data.data);
      if (data.type === 'fullscreen') ipcRenderer.send('window-fullscreen', true);
      if (data.type === 'graph' && data.data) { window.showGraph?.(data.data); queueGraphChip(data.data); }
      if (data.type === 'show_graph') window.reopenGraph?.(data.which || 'last');
      if (data.type === 'close_graph') window.hideGraph?.();
      if (data.type === 'globe' && data.data) { window.showGlobe?.(data.data); queueGlobeChip(data.data); }
      if (data.type === 'show_globe') window.reopenGlobe?.(data.which || 'last');
      if (data.type === 'close_globe') window.hideGlobe?.();
      if (data.type === 'planet' && data.data) { window.showPlanet?.(data.data); queuePlanetChip(data.data); }
      if (data.type === 'show_planet') window.reopenPlanet?.(data.which || 'last');
      if (data.type === 'close_planet') window.hidePlanet?.();
      if (data.type === 'timers') setTimers(data.data);
      if (data.type === 'timer_done' && data.data) showAlert(data.data);
      if (data.type === 'dismiss_alert' && alerts.length) dismissAlert(alerts.length);
    } catch (error) {
      console.error('Error handling WebSocket message:', error);
    }
  }

  // ---------- Voice meter: the core spins and pulses with how loud you speak ----------
  // Only the loudness is measured, in this window. Nothing is recorded and no audio leaves the window.
  const meter = { stream: null, ctx: null, raf: 0, floor: -60, starting: false };
  async function startVoiceMeter() {
    if (meter.stream || meter.starting || !navigator.mediaDevices?.getUserMedia) return;
    meter.starting = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
      if (isMuted) { stream.getTracks().forEach((t) => t.stop()); return; }   // muted while the permission was pending
      meter.stream = stream;
      meter.ctx = new (window.AudioContext || window.webkitAudioContext)();
      const analyser = meter.ctx.createAnalyser();
      analyser.fftSize = 512;
      meter.ctx.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      let lastMeter = 0;
      const tick = (now = 0) => {
        meter.raf = requestAnimationFrame(tick);
        if (now - lastMeter < 30) return;   // about 30 readings a second is plenty for the core
        lastMeter = now;
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
        const db = 20 * Math.log10(Math.sqrt(sum / samples.length) + 1e-6);
        // Follow the room's background noise, so only speech above it counts.
        meter.floor = db < meter.floor + 6 ? meter.floor * 0.995 + db * 0.005 : meter.floor;
        window.setOrbLevel?.((db - meter.floor - 6) / 24);
      };
      tick();
    } catch (error) {
      console.warn('Voice meter unavailable (microphone not allowed for this window):', error?.name || error);
    } finally {
      meter.starting = false;
    }
  }
  function stopVoiceMeter() {
    cancelAnimationFrame(meter.raf);
    meter.stream?.getTracks().forEach((t) => t.stop());
    meter.ctx?.close().catch(() => {});
    meter.stream = meter.ctx = null;
    window.setOrbLevel?.(0);
  }

  // ---------- Microphone ----------
  function applyMute(muted, notify = true) {
    isMuted = muted;
    connectBtn.setAttribute('aria-pressed', String(muted));
    connectBtn.classList.toggle('muted', muted);
    $('pillText').textContent = muted ? 'Microphone off' : 'Microphone on';
    $('buttonHint').textContent = muted ? 'unmute' : 'mute';
    muted ? stopVoiceMeter() : startVoiceMeter();
    if (notify) {
      toggledAt = Date.now();
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: muted ? 'mute' : 'unmute' }));
      setState(muted ? 'muted' : 'idle');
    }
  }
  function interruptSpeech() {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'interrupt' }));
  }
  $('stopBtn').addEventListener('click', () => { if (app.dataset.state === 'speaking') interruptSpeech(); });
  connectBtn.addEventListener('click', () => applyMute(!isMuted));
  document.addEventListener('keydown', (e) => {
    if (typing(e)) return;
    if (e.key.toLowerCase() === 'f' && !alerts.length && !e.metaKey && !e.ctrlKey && !e.altKey) {   // F: full screen on/off
      e.preventDefault();
      ipcRenderer.send('window-fullscreen', 'toggle');
      return;
    }
    if (e.key === 'Escape' && !alerts.length && !window.graphOpen?.()) {
      ipcRenderer.send('window-fullscreen', false);
      return;
    }
    if (e.key === '/' && !alerts.length && !e.metaKey && !e.ctrlKey && !e.altKey) {   // "/" jumps to the typing box
      e.preventDefault();
      $('typeInput').focus();
      return;
    }
    if (e.key === ' ' && app.dataset.state === 'speaking' && !alerts.length) {
      e.preventDefault();
      interruptSpeech();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat || alerts.length) return;
    if (e.key.toLowerCase() === 'm') applyMute(!isMuted);
  });

  const typeInput = $('typeInput');

  // ---------- Attaching an image: the file picker, drag-and-drop anywhere, or pasting from the clipboard ----------
  let stagedImage = null;   // { dataUrl, name } staged for the next send
  const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
  const IMAGE_MIME_RE = /^image\/(png|jpe?g|webp|gif|bmp)$/i;
  const attachPreview = $('attachPreview');
  const imageFileInput = $('imageFileInput');

  function flashTypebarNotice(message) {
    typeInput.placeholder = message;
    $('typeForm').classList.remove('nope');
    void $('typeForm').offsetWidth;
    $('typeForm').classList.add('nope');
    clearTimeout(flashTypebarNotice._t);
    flashTypebarNotice._t = setTimeout(() => { typeInput.placeholder = 'Type a message or a number to Jervis…'; }, 2600);
  }
  function renderAttachPreview() {
    attachPreview.hidden = !stagedImage;
    if (stagedImage) {
      $('attachPreviewImg').src = stagedImage.dataUrl;
      $('attachPreviewName').textContent = stagedImage.name || 'image';
    }
  }
  function clearStagedImage() {
    stagedImage = null;
    imageFileInput.value = '';
    renderAttachPreview();
  }
  function stageImageFile(file) {
    if (!file || !IMAGE_MIME_RE.test(file.type)) return flashTypebarNotice('That file is not a supported image (PNG, JPEG, WEBP, GIF, BMP).');
    if (file.size > MAX_IMAGE_BYTES) return flashTypebarNotice('That image is too large (limit 20 MB).');
    const reader = new FileReader();
    reader.onload = () => { stagedImage = { dataUrl: reader.result, name: file.name || 'image' }; renderAttachPreview(); typeInput.focus(); };
    reader.onerror = () => flashTypebarNotice('Could not read that image file.');
    reader.readAsDataURL(file);
  }
  $('attachBtn').addEventListener('click', () => imageFileInput.click());
  imageFileInput.addEventListener('change', () => { if (imageFileInput.files[0]) stageImageFile(imageFileInput.files[0]); });
  $('attachRemoveBtn').addEventListener('click', clearStagedImage);
  ['dragover', 'dragenter'].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); app.classList.add('drag-over'); }));
  ['dragleave', 'dragend'].forEach((ev) => document.addEventListener(ev, () => app.classList.remove('drag-over')));
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    app.classList.remove('drag-over');
    const file = [...(e.dataTransfer?.files || [])].find((f) => IMAGE_MIME_RE.test(f.type));
    if (file) stageImageFile(file);
  });
  document.addEventListener('paste', (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => IMAGE_MIME_RE.test(i.type));
    if (item) { e.preventDefault(); stageImageFile(item.getAsFile()); }
  });

  // ---------- Typing to Jervis: the same as saying it (words, numbers, anything) ----------
  const sent = [];        // what was typed, so the arrow keys can bring it back
  let sentAt = 0;         // where in that history the arrow keys are
  function sendTyped() {
    const text = typeInput.value.replace(/\s+/g, ' ').trim();
    if (!text && !stagedImage) return;
    if (socket?.readyState !== WebSocket.OPEN) {
      typeInput.placeholder = 'Not connected yet, try again in a moment…';
      $('typeForm').classList.remove('nope');
      void $('typeForm').offsetWidth;
      $('typeForm').classList.add('nope');
      return;
    }
    if (stagedImage) {
      socket.send(JSON.stringify({ type: 'image', data: stagedImage.dataUrl, name: stagedImage.name, text }));
      clearStagedImage();
    } else {
      socket.send(JSON.stringify({ type: 'text', text }));
    }
    if (text && sent[sent.length - 1] !== text) sent.push(text);
    if (sent.length > 30) sent.shift();
    sentAt = sent.length;
    typeInput.value = '';
    typeInput.placeholder = 'Type a message or a number to Jervis…';
    $('typeForm').classList.remove('sent');
    void $('typeForm').offsetWidth;
    $('typeForm').classList.add('sent');
  }
  $('typeForm').addEventListener('submit', (e) => { e.preventDefault(); sendTyped(); });
  typeInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { typeInput.blur(); return; }
    if (e.key === 'ArrowUp' && sent.length) {
      e.preventDefault();
      sentAt = Math.max(0, sentAt - 1);
      typeInput.value = sent[sentAt];
    } else if (e.key === 'ArrowDown' && sent.length) {
      e.preventDefault();
      sentAt = Math.min(sent.length, sentAt + 1);
      typeInput.value = sent[sentAt] || '';
    }
  });

  $('clearBtn').addEventListener('click', () => {
    messageCount = 0;
    typingEl = null;
    updateCount();
    showEmpty();
    $('caption').classList.remove('show');
  });

  showEmpty();
  updateCount();
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(renderTimers, 1000);
  if (window.initOrb) window.initOrb('orbCanvas');
  if (window.initBackground) window.initBackground('netCanvas');
  setState('idle');
  startVoiceMeter();
  connectSocket();
});
