// Jervis's panels: the first-start setup of the AI, the Settings screen, and the engine banner.
// They talk to the backend through window.jervisSend() and the 'jervis-message' event (see renderer.js), and to the
// window's main process for things only it can do (open a folder, start at sign-in).
document.addEventListener('DOMContentLoaded', () => {
  const $ = (id) => document.getElementById(id);
  const { ipcRenderer } = require('electron');
  const make = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  // ---------- Keyboard: while a panel is open, it gets the keys (the app's shortcuts wait) ----------
  const openPanels = new Set();
  function openPanel(layer) { layer.hidden = false; openPanels.add(layer); }
  function closePanel(layer) { layer.hidden = true; openPanels.delete(layer); }
  window.addEventListener('keydown', (e) => {
    if (!openPanels.size) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      const last = [...openPanels].pop();
      if (last === settingsLayer) closeSettings(); else closePanel(last);
    }
    e.stopPropagation();   // keep M, Space, F, G... from firing while a panel is in use
  }, true);

  // =====================================================================================================
  // First start: getting the AI on this computer ready
  // =====================================================================================================
  const setupLayer = $('setupLayer');
  const setupChip = $('setupChip');
  let setup = null;
  let setupDismissed = false;
  const STEP_ICON = { pending: '○', active: '', done: '✓', error: '!', skipped: '–' };

  function needsAttention(state) {
    // Open the big panel only when something is being downloaded, or something went wrong; a normal start (the AI
    // is already installed and just warming up) shows only the small chip.
    return Boolean(state.error) || state.steps.some((s) => s.state === 'active' && /Downloading|Unpacking|Checking the download/.test(s.detail || ''));
  }

  function renderSetup(state) {
    setup = state;
    $('setupSummary').textContent = state.summary || '';
    const list = $('setupSteps');
    list.replaceChildren(...state.steps.map((step) => {
      const li = make('li', `setup-step ${step.state}`);
      const icon = make('span', 'step-icon', STEP_ICON[step.state] ?? '');
      icon.setAttribute('aria-hidden', 'true');
      const body = make('div', 'step-body');
      body.append(make('b', '', step.label), make('span', 'step-detail', step.detail || ''));
      if (step.state === 'active' && typeof step.progress === 'number') {
        const bar = make('i', 'step-bar');
        bar.style.setProperty('--p', `${Math.round(step.progress * 100)}%`);
        bar.setAttribute('role', 'progressbar');
        bar.setAttribute('aria-valuenow', String(Math.round(step.progress * 100)));
        body.append(bar);
      }
      li.append(icon, body);
      return li;
    }));
    const failed = Boolean(state.error);
    $('setupError').hidden = !failed;
    $('setupErrorText').textContent = state.error || '';
    $('setupHint').textContent = state.hint || '';
    $('setupRetry').hidden = !failed;
    $('setupHide').textContent = state.done ? 'Close' : 'Continue in the background';

    // The small chip in the top bar
    const active = state.steps.find((s) => s.state === 'active');
    if (state.done) {
      setupChip.hidden = true;
    } else {
      setupChip.hidden = false;
      setupChip.classList.toggle('bad', failed);
      setupChip.textContent = failed ? 'AI setup: needs attention'
        : active && typeof active.progress === 'number' ? `AI setup ${Math.round(active.progress * 100)}%`
          : 'AI starting…';
    }
    if (state.done && !setupLayer.hidden) {
      setTimeout(() => closePanel(setupLayer), 1600);   // show the ✓ for a moment, then get out of the way
    } else if (!state.done && !setupDismissed && needsAttention(state)) {
      openPanel(setupLayer);
    } else if (failed && setupLayer.hidden && !setupDismissed) {
      openPanel(setupLayer);
    }
  }

  $('setupHide').addEventListener('click', () => { setupDismissed = true; closePanel(setupLayer); });
  $('setupRetry').addEventListener('click', () => { setupDismissed = false; window.jervisSend({ type: 'setup_retry' }); });
  setupChip.addEventListener('click', () => { setupDismissed = false; if (setup) openPanel(setupLayer); });

  // =====================================================================================================
  // Settings (built from the backend's schema, so a new setting needs no change here)
  // =====================================================================================================
  const settingsLayer = $('settingsLayer');
  let loaded = null;        // the last settings payload from the backend
  let appInfo = null;
  const inputs = {};         // key -> control

  function openSettings() {
    openPanel(settingsLayer);
    $('settingsStatus').textContent = '';
    if (!window.jervisSend({ type: 'get_settings' })) {
      $('settingsBody').replaceChildren(make('p', 'sheet-sub', 'Jervis’s engine isn’t connected yet. Try again in a moment.'));
    }
    ipcRenderer.invoke('app-info').then((info) => { appInfo = info; if (loaded) renderSettings(loaded); }).catch(() => {});
  }
  function closeSettings() {
    if (pendingChanges() && !confirm('Close without saving your changes?')) return;
    closePanel(settingsLayer);
  }

  function control(item, value, payload) {
    const id = `set-${item.key}`;
    let el;
    const option = (v, label) => { const o = make('option', '', label); o.value = v; return o; };
    if (item.type === 'choice') {
      el = make('select');
      item.choices.forEach(([v, label]) => el.append(option(v, label)));
      el.value = value;
    } else if (item.type === 'toggle') {
      el = make('input');
      el.type = 'checkbox';
      el.className = 'switch';
      el.checked = value !== 'off';
    } else if (item.type === 'device') {
      el = make('select');
      el.append(option('', 'System default'));
      (payload.microphones || []).forEach((name) => el.append(option(name, name)));
      if (value && !(payload.microphones || []).includes(value)) el.append(option(value, `${value} (not connected)`));
      el.value = value;
    } else if (item.type === 'voice') {
      el = make('select');
      el.append(option('', 'System default'));
      const voices = (payload.voices || []).slice().sort((a, b) => a[0].localeCompare(b[0]));
      const english = voices.filter(([, lang]) => /^en/i.test(lang));
      const others = voices.filter(([, lang]) => !/^en/i.test(lang));
      english.concat(others).forEach(([name, lang]) => el.append(option(name, `${name} (${lang})`)));
      el.value = value;
    } else {
      el = make('input');
      el.type = item.type === 'secret' ? 'password' : 'text';
      el.autocomplete = 'off';
      el.spellcheck = false;
      if (item.type === 'secret') el.placeholder = value === 'set' ? 'Saved (type to replace)' : 'Not set';
      else el.value = value;
    }
    el.id = id;
    el.dataset.key = item.key;
    el.addEventListener('input', markDirty);
    el.addEventListener('change', markDirty);
    return el;
  }

  function valueOf(el) {
    if (el.type === 'checkbox') return el.checked ? 'on' : 'off';
    return el.value.trim();
  }

  function pendingChanges() {
    if (!loaded) return null;
    const changes = {};
    for (const [key, el] of Object.entries(inputs)) {
      const item = loaded.schema.find((s) => s.key === key);
      const now = valueOf(el);
      if (item.type === 'secret') { if (now) changes[key] = now; continue; }
      if (now !== (loaded.values[key] ?? '')) changes[key] = now;
    }
    return Object.keys(changes).length ? changes : null;
  }
  function markDirty() { $('settingsSave').disabled = !pendingChanges(); $('settingsStatus').textContent = ''; }

  function renderSettings(payload) {
    loaded = payload;
    const advanced = $('settingsAdvanced').checked;
    const body = $('settingsBody');
    Object.keys(inputs).forEach((k) => delete inputs[k]);
    const sections = new Map();
    for (const item of payload.schema) {
      if (item.advanced && !advanced) continue;
      if (item.key === 'WHATSAPP_READING' && payload.platform !== 'Darwin') continue;   // macOS only
      if (!sections.has(item.section)) sections.set(item.section, []);
      sections.get(item.section).push(item);
    }
    const blocks = [];
    for (const [name, items] of sections) {
      const section = make('section', 'set-section');
      section.append(make('h3', '', name));
      for (const item of items) {
        const row = make('div', `set-row ${item.type}`);
        const label = make('label', '', item.label);
        label.htmlFor = `set-${item.key}`;
        const input = control(item, payload.values[item.key] ?? '', payload);
        inputs[item.key] = input;
        const text = make('div', 'set-text');
        text.append(label);
        if (item.help) text.append(make('small', '', item.help));
        row.append(text, input);
        section.append(row);
      }
      blocks.push(section);
    }
    // Things only the window can do
    const system = make('section', 'set-section');
    system.append(make('h3', '', 'This computer'));
    if (appInfo && appInfo.packaged) {
      const row = make('div', 'set-row toggle');
      const text = make('div', 'set-text');
      const label = make('label', '', 'Start Jervis when I sign in');
      label.htmlFor = 'set-login';
      text.append(label, make('small', '', 'He starts in the background, listening for “Hey Jervis”.'));
      const box = make('input');
      box.type = 'checkbox'; box.className = 'switch'; box.id = 'set-login'; box.checked = Boolean(appInfo.openAtLogin);
      box.addEventListener('change', () => ipcRenderer.invoke('set-open-at-login', box.checked).then((on) => { box.checked = on; }));
      row.append(text, box);
      system.append(row);
    }
    const tools = make('div', 'set-tools');
    const folder = make('button', 'ghost', 'Open data folder');
    folder.type = 'button';
    folder.addEventListener('click', () => ipcRenderer.invoke('open-path', 'data'));
    const logs = make('button', 'ghost', 'Open log files');
    logs.type = 'button';
    logs.addEventListener('click', () => ipcRenderer.invoke('open-path', 'logs'));
    const restart = make('button', 'ghost', 'Restart Jervis’s engine');
    restart.type = 'button';
    restart.addEventListener('click', () => ipcRenderer.send('restart-backend'));
    tools.append(folder, logs, restart);
    system.append(tools);
    if (appInfo) system.append(make('small', 'set-version', `Jervis ${appInfo.version}${appInfo.packaged ? '' : ' (running from source)'}`));
    blocks.push(system);
    body.replaceChildren(...blocks);
    $('settingsSave').disabled = true;
  }

  $('settingsBtn').addEventListener('click', openSettings);
  $('settingsClose').addEventListener('click', closeSettings);
  $('settingsAdvanced').addEventListener('change', () => { if (loaded) renderSettings(loaded); });
  $('settingsSave').addEventListener('click', () => {
    const values = pendingChanges();
    if (!values) return;
    $('settingsSave').disabled = true;
    $('settingsStatus').textContent = 'Saving…';
    if (!window.jervisSend({ type: 'set_settings', values })) {
      $('settingsStatus').textContent = 'Jervis’s engine isn’t connected; your changes weren’t saved.';
      $('settingsSave').disabled = false;
    }
  });

  // =====================================================================================================
  // Engine banner: the backend starting, restarting, or failing; microphone problems
  // =====================================================================================================
  const banner = $('engineBanner');
  let bannerAction = null;
  function showBanner(text, kind = 'info', actionLabel = '', action = null) {
    if (!text) { banner.hidden = true; return; }
    banner.hidden = false;
    banner.className = `engine-banner ${kind}`;
    $('engineText').textContent = text;
    const button = $('engineAction');
    button.hidden = !actionLabel;
    button.textContent = actionLabel;
    bannerAction = action;
  }
  $('engineAction').addEventListener('click', () => bannerAction && bannerAction());

  let engineState = 'starting';
  let micMessage = '';
  function refreshBanner() {
    if (engineState === 'failed') showBanner(lastEngineDetail || 'Jervis’s engine stopped.', 'bad', 'Restart', () => ipcRenderer.send('restart-backend'));
    else if (engineState === 'restarting') showBanner(lastEngineDetail || 'Restarting Jervis’s engine…', 'warn');
    else if (micMessage) showBanner(micMessage, 'warn', 'Settings', openSettings);
    else showBanner('');
  }
  let lastEngineDetail = '';
  ipcRenderer.on('backend-state', (_event, { state, detail }) => {
    engineState = state;
    lastEngineDetail = detail || '';
    refreshBanner();
  });

  // =====================================================================================================
  // Messages from the backend
  // =====================================================================================================
  window.addEventListener('jervis-message', (event) => {
    const data = event.detail || {};
    if (data.type === 'setup' && data.data) renderSetup(data.data);
    else if (data.type === 'settings') renderSettings(data);
    else if (data.type === 'settings_devices' && loaded) {
      // Fresher microphone and voice lists: rebuild just those two lists, keeping what's selected.
      loaded.microphones = data.microphones;
      loaded.voices = data.voices;
      for (const key of ['JERVIS_MIC', 'JERVIS_VOICE']) {
        const old = inputs[key];
        if (!old) continue;
        const item = loaded.schema.find((s) => s.key === key);
        const fresh = control(item, valueOf(old), loaded);
        fresh.value = old.value;
        old.replaceWith(fresh);
        inputs[key] = fresh;
      }
    }
    else if (data.type === 'settings_saved') {
      $('settingsStatus').textContent = data.restart ? 'Saved. Restarting Jervis’s engine to apply it…' : 'Saved.';
      if (loaded) window.jervisSend({ type: 'get_settings' });
    } else if (data.type === 'settings_error') {
      $('settingsStatus').textContent = data.message || 'Couldn’t save.';
      $('settingsSave').disabled = false;
    } else if (data.type === 'mic' && data.data) {
      micMessage = data.data.ok ? '' : data.data.message;
      refreshBanner();
    }
  });
  // =====================================================================================================
  // Computer control: the question before Jervis starts, and relaying the overlay's buttons (see main.js)
  // =====================================================================================================
  const CONTROL_ACTIVE = new Set(['starting', 'observing', 'thinking', 'acting', 'waiting', 'paused']);
  const controlLayer = $('controlLayer');
  for (const key of document.querySelectorAll('.control-key')) key.textContent = process.platform === 'darwin' ? '⌃⌥Q' : 'Ctrl+Alt+Q';
  let controlStateName = '';
  let controlAskId = null;
  function answerControl(allow) {
    if (controlAskId) window.jervisSend({ type: 'control_answer', id: controlAskId, allow });
    controlAskId = null;
    closePanel(controlLayer);
  }
  $('controlAllow').addEventListener('click', () => answerControl(true));
  $('controlDeny').addEventListener('click', () => answerControl(false));
  controlLayer.addEventListener('keydown', (e) => { if (e.key === 'Escape') answerControl(false); });
  ipcRenderer.on('control-relay', (_event, message) => window.jervisSend(message));
  // Whether the window is open or closed (hidden in the tray), for the engine: see set_window_visible in app.py.
  let windowVisible = true;
  ipcRenderer.on('window-visibility', (_event, visible) => {
    windowVisible = Boolean(visible);
    window.jervisSend({ type: 'window_visibility', visible: windowVisible });
  });
  window.addEventListener('jervis-connected', () => window.jervisSend({ type: 'window_visibility', visible: windowVisible }));
  window.addEventListener('jervis-message', (event) => {
    const data = event.detail || {};
    if (data.type === 'control' && data.data) {
      controlStateName = data.data.state;
      ipcRenderer.send('control-event', data);
    } else if (data.type === 'control_confirm') {
      ipcRenderer.send('control-event', data);
      if (CONTROL_ACTIVE.has(controlStateName)) return;   // the overlay asks while Jervis is working
      controlAskId = data.id;
      $('controlQuestion').textContent = data.question;
      openPanel(controlLayer);
      $('controlAllow').focus();
    } else if (data.type === 'control_confirm_done') {
      ipcRenderer.send('control-event', data);
      if (data.id === controlAskId) { controlAskId = null; closePanel(controlLayer); }
    }
  });

  window.addEventListener('jervis-connected', () => {
    if (engineState !== 'failed') { engineState = 'running'; refreshBanner(); }
    if (!settingsLayer.hidden) window.jervisSend({ type: 'get_settings' });
  });
});
