// Coding Mode: the window where Jarvis writes real code. On the left, only what to build (Jarvis chooses the language,
// the files and where the project folder goes, as a person you asked would); on the right, the work as it really happens (planning, writing, checking, saving), the files that now
// exist, the output of every check and test, and what to do next.
//
// Nothing here writes or runs code: the engine (coder.py, through app.py) does, and this window only shows what the
// engine reports, in the engine's own words. A step lights up when the engine says it began; there is no timer
// pretending to make progress. "Run tests" asks first, because that is the one action that executes the project.
//
// Talks to the rest of Jarvis only through the 'jarvis-message' event and window.jarvisSend (renderer.js).
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const send = (payload) => Boolean(window.jarvisSend?.(payload));
  const STEPS = [['planning', 'Plan'], ['writing', 'Write'], ['checking', 'Check'], ['saving', 'Save']];
  const ICON = {
    code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5M13.5 5l-3 14"/></svg>',
    ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    bad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
    skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 12h12"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 6l-6 6 6 6"/></svg>',
  };
  const EXAMPLES = ['A Python script that sorts my Downloads folder by file type', 'A website for a bakery with a menu and a contact form',
    'A command line to-do list in Rust', 'A SQL query for the ten best customers by revenue'];

  const layer = el('div', 'cd-layer');
  layer.id = 'codingLayer';
  layer.hidden = true;
  layer.setAttribute('role', 'dialog');
  layer.setAttribute('aria-modal', 'true');
  layer.setAttribute('aria-labelledby', 'cdTitle');
  layer.innerHTML = `
    <div class="cd-card" tabindex="-1">
      <header class="cd-head">
        <h2 id="cdTitle">Coding Mode</h2>
        <div class="cd-head-actions"><span class="cd-model" title="The AI that writes the code. A CODE_MODEL line in .env chooses another."></span>
          <button type="button" class="ghost cd-close" title="Close (Esc)">Close</button></div>
      </header>
      <div class="cd-body">
        <form class="cd-form" autocomplete="off">
          <label class="cd-field"><span>What should I build?</span>
            <textarea name="request" rows="7" maxlength="4000" placeholder="A small program, a website, a whole project. Say what it should do; Jarvis picks the language and everything else it needs." required></textarea></label>
          <div class="cd-go"><button type="submit" class="cd-primary">Build it</button><p class="cd-note" role="status"></p></div>
          <section class="cd-history" aria-label="Recent projects"><h3>Recent</h3><ol></ol></section>
        </form>
        <section class="cd-work" aria-live="polite">
          <div class="cd-empty">
            <p class="cd-empty-lead">Describe it on the left, or just say it: “Jarvis, write a Python calculator and open it in VS Code.”</p>
            <p class="cd-empty-sub">Jarvis chooses the language and the files, writes them into a new project folder, checks them, and tells you where they are and exactly what was and wasn’t checked. Afterwards you can open the project in VS Code, or get it as a Word document, a note or a zip. Your code is only run when you ask for the tests.</p>
            <ul class="cd-examples"></ul>
          </div>
          <div class="cd-job" hidden>
            <div class="cd-job-head"><div><h3 class="cd-name"></h3><p class="cd-path"></p></div><ol class="cd-steps"></ol></div>
            <p class="cd-step" role="status"></p>
            <p class="cd-error" role="alert" hidden></p>
            <p class="cd-summary"></p>
            <dl class="cd-how"></dl>
            <div class="cd-panes">
              <div class="cd-list-pane">
                <h4>Files <span class="cd-count"></span></h4><ol class="cd-files"></ol>
                <h4 class="cd-checks-title">Checks <span class="cd-checks-sum"></span></h4><ol class="cd-checks"></ol>
                <div class="cd-tests" hidden><h4>Tests <span class="cd-tests-sum"></span></h4><pre class="cd-output"></pre></div>
              </div>
              <div class="cd-view-pane" hidden>
                <div class="cd-view-head"><button type="button" class="cd-back" aria-label="Back to the file list">${ICON.back}</button><b class="cd-view-name"></b>
                  <div class="cd-view-tabs" hidden><button type="button" data-tab="diff">Changes</button><button type="button" data-tab="file">Whole file</button></div></div>
                <pre class="cd-code" tabindex="0"></pre>
              </div>
            </div>
            <div class="cd-next">
              <div class="cd-buttons"></div>
              <form class="cd-follow" autocomplete="off"><input type="text" maxlength="2000" placeholder="Change this project: add a login page, fix the failing test…" aria-label="Change this project"><button type="submit" class="ghost">Apply</button></form>
            </div>
          </div>
        </section>
      </div>
    </div>`;
  document.body.append(layer);
  const card = $('.cd-card', layer), form = $('.cd-form', layer);

  let info = { languages: [], destinations: [], history: [], model: '', projectsDir: '' };
  let job = null, viewing = '', viewTab = 'diff', viewData = null, confirmTests = false, lastRequest = null, closeTimer = 0;

  // ---------- the form ----------
  function drawHistory() {
    const section = $('.cd-history', layer);
    section.hidden = !info.history.length;
    $('ol', section).replaceChildren(...info.history.slice(0, 6).map((p) => {
      const li = el('li'), pick = el('button', 'cd-recent');
      pick.type = 'button';
      pick.append(el('b', '', p.name), el('small', '', [p.language, ago(p.updated || p.created)].filter(Boolean).join(' · ')));
      pick.title = p.path;
      pick.addEventListener('click', () => send({ type: 'code_pick', id: p.id }));
      li.append(pick);
      return li;
    }));
  }
  function ago(seconds) {
    if (!seconds) return '';
    const mins = Math.max(0, Math.round((Date.now() / 1000 - seconds) / 60));
    return mins < 1 ? 'just now' : mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} d ago`;
  }
  function note(message) { $('.cd-note', layer).textContent = message || ''; }
  function drawInfo() {
    $('.cd-model', layer).textContent = info.model ? `AI: ${info.model}` : '';
    drawHistory();
    $('.cd-primary', layer).disabled = Boolean(info.busy);
  }

  // ---------- the work ----------
  const working = () => job && !['done', 'failed'].includes(job.phase);
  function drawJob() {
    $('.cd-empty', layer).hidden = Boolean(job);
    $('.cd-job', layer).hidden = !job;
    $('.cd-primary', layer).disabled = Boolean(working());
    $('.cd-primary', layer).textContent = working() ? 'Working…' : 'Build it';
    if (!job) return;
    $('.cd-name', layer).textContent = job.name || (job.action === 'change' ? 'Changing the project' : 'A new project');
    $('.cd-path', layer).textContent = job.path || '';
    const reached = STEPS.findIndex(([key]) => key === (job.phase === 'fixing' ? 'checking' : job.phase));
    $('.cd-steps', layer).replaceChildren(...STEPS.map(([key, label], i) => {
      const li = el('li', '', label);
      const done = job.phase === 'done' ? (key !== 'saving' || Boolean(job.delivered && job.delivered.ok) || !job.destination) : reached > i;
      const unsent = job.phase === 'done' && key === 'saving' && job.delivered && job.delivered.ok === false;   // written, but not delivered where asked
      li.dataset.state = done ? 'done' : reached === i && working() ? 'now' : unsent || (job.phase === 'failed' && reached === i) ? 'failed' : 'wait';
      return li;
    }));
    $('.cd-step', layer).textContent = working() ? (job.step || 'Working') + '…' : '';
    const error = $('.cd-error', layer);
    error.hidden = !job.error;
    error.textContent = job.error || '';
    $('.cd-summary', layer).textContent = job.summary || '';
    const how = [['Run it with', job.run], ['Test it with', job.test], ['Needs', job.needs], ['Sent to', job.delivered && job.delivered.message]].filter(([, v]) => v);
    $('.cd-how', layer).replaceChildren(...how.flatMap(([k, v]) => [el('dt', '', k), el('dd', k === 'Sent to' ? '' : 'cd-mono', v)]));
    const files = job.files || [];
    $('.cd-count', layer).textContent = files.length ? String(files.length) : '';
    $('.cd-files', layer).replaceChildren(...files.filter((f) => f.status !== 'unchanged' || files.length <= 14).map((f) => {
      const li = el('li'), open = el('button', 'cd-file');
      open.type = 'button';
      open.dataset.status = f.status;
      const label = { planned: 'planned', written: 'new', changed: 'changed', unchanged: '', failed: 'not written' }[f.status] ?? f.status;
      open.append(el('span', 'cd-file-name', f.path), el('span', 'cd-file-meta', [label, f.lines ? `${f.lines} lines` : ''].filter(Boolean).join(' · ')));
      open.disabled = f.status === 'planned' || f.status === 'failed';
      open.title = f.error || f.purpose || '';
      open.addEventListener('click', () => view(f.path));
      li.append(open);
      return li;
    }));
    const checks = job.checks || [];
    $('.cd-checks-title', layer).hidden = !checks.length;
    const failed = checks.filter((c) => c.status === 'failed').length, skipped = checks.filter((c) => c.status === 'skipped').length;
    $('.cd-checks-sum', layer).textContent = checks.length ? [`${checks.length - failed - skipped} passed`, failed ? `${failed} failed` : '', skipped ? `${skipped} not checked` : ''].filter(Boolean).join(' · ') : '';
    $('.cd-checks', layer).replaceChildren(...checks.map((c) => {
      const li = el('li', 'cd-check');
      li.dataset.status = c.status;
      const mark = el('i'); mark.innerHTML = c.status === 'ok' ? ICON.ok : c.status === 'failed' ? ICON.bad : ICON.skip;
      li.append(mark, el('span', 'cd-check-file', c.file), el('span', 'cd-check-tool', c.tool));
      if (c.output) li.append(el('pre', 'cd-output', c.output));
      return li;
    }));
    const tests = job.tests || {}, box = $('.cd-tests', layer);
    box.hidden = !tests.status;
    $('.cd-tests-sum', layer).textContent = { passed: 'passed', failed: 'failed', not_run: 'not run', running: 'running…' }[tests.status] || '';
    $('.cd-tests-sum', layer).dataset.status = tests.status || '';
    $('.cd-output', box).textContent = tests.status === 'running' ? '' : [tests.command ? `$ ${tests.command}${tests.sandboxed ? '   (sandboxed: no network, writes only inside the project)' : ''}` : '', tests.output || ''].filter(Boolean).join('\n\n');
    drawButtons();
    if (viewing && !files.some((f) => f.path === viewing)) closeView();
  }

  function drawButtons() {
    const bar = $('.cd-buttons', layer), finished = job && job.phase === 'done' && job.path;
    const button = (label, action, cls = 'ghost') => { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', action); return b; };
    const items = [];
    if (finished) {
      const can = (key) => (info.destinations.find((d) => d.key === key) || {}).available;
      if (can('vscode')) items.push(button('Open in VS Code', () => send({ type: 'code_deliver', destination: 'vscode' })));
      items.push(button('Show the folder', () => send({ type: 'code_deliver', destination: 'local' })));
      for (const [key, label] of [['word', 'Make a Word document'], ['notes', 'Copy to Notes'], ['gdrive', 'Send to Google Drive'], ['zip', 'Make a zip']]) {
        if (can(key)) items.push(button(label, () => send({ type: 'code_deliver', destination: key })));
      }
      if (!can('gdrive') && info.drive === 'ready') items.push(button('Connect Google Drive', () => { if (send({ type: 'code_connect_drive' })) note('A browser tab is opening for the Google sign-in…'); }));
      if (confirmTests) {
        const ask = el('span', 'cd-confirm', info.sandbox ? 'This runs the project’s own code, in a sandbox without network. Run it?'
          : 'This runs the project’s own code on this computer (with a time limit and none of your keys, but no sandbox here). Run it?');
        items.push(ask, button('Run the tests', () => { confirmTests = false; send({ type: 'code_tests' }); }, 'cd-primary small'), button('Not now', () => { confirmTests = false; drawButtons(); }));
      } else items.push(button('Run tests…', () => { confirmTests = true; drawButtons(); }));
      items.push(button('Check again', () => send({ type: 'code_check' })));
    }
    if (job && job.phase === 'failed' && lastRequest) items.push(button('Try again', () => { if (send(lastRequest)) note(''); }, 'cd-primary small'));
    bar.replaceChildren(...items);
    $('.cd-follow', layer).hidden = !finished;
  }

  // ---------- one file ----------
  function view(path) {
    viewing = path;
    viewData = null;
    viewTab = (job.changed || []).includes(path) ? 'diff' : 'file';
    $('.cd-view-pane', layer).hidden = false;
    $('.cd-list-pane', layer).hidden = true;
    $('.cd-view-name', layer).textContent = path;
    $('.cd-code', layer).textContent = 'Opening…';
    if (!send({ type: 'code_file', path })) $('.cd-code', layer).textContent = 'Jarvis’s engine isn’t connected.';
  }
  function closeView() {
    viewing = '';
    $('.cd-view-pane', layer).hidden = true;
    $('.cd-list-pane', layer).hidden = false;
  }
  function drawView() {
    if (!viewData) return;
    const tabs = $('.cd-view-tabs', layer), code = $('.cd-code', layer);
    tabs.hidden = !viewData.diff;
    for (const b of tabs.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.tab === viewTab));
    if (viewData.error) { code.textContent = viewData.error; return; }
    if (viewTab === 'diff' && viewData.diff) {
      code.replaceChildren(...viewData.diff.split('\n').map((line) => {
        const kind = line.startsWith('+++') || line.startsWith('---') ? 'meta' : line.startsWith('@@') ? 'hunk' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
        return el('span', kind ? `cd-diff-${kind}` : '', line + '\n');
      }));
    } else code.textContent = viewData.content;
    code.scrollTop = 0;
  }

  // ---------- open, close ----------
  function open(data) {
    clearTimeout(closeTimer);
    layer.classList.remove('closing');
    if (data) { info = { ...info, ...data }; if (data.job) job = data.job; if (data.project) job = { ...data.project, phase: 'done', changed: [] }; }
    drawInfo();
    drawJob();
    if (layer.hidden) {
      window.hideGraph?.(); window.hideGlobe?.(); window.hidePlanet?.(); window.hideClock?.(); window.weatherPanel?.close?.();
      layer.hidden = false;
      (form.elements.request.value ? card : form.elements.request).focus({ preventScroll: true });
      send({ type: 'code_window', open: true });
    }
  }
  function close() {
    if (layer.hidden || layer.classList.contains('closing')) return;
    layer.classList.add('closing');
    closeTimer = setTimeout(() => { layer.hidden = true; layer.classList.remove('closing'); send({ type: 'code_window', open: false }); }, 200);
  }

  // ---------- from the backend ----------
  window.addEventListener('jarvis-message', (event) => {
    const msg = event.detail || {};
    if (msg.type === 'coding_open') open(msg.data || {});
    else if (msg.type === 'close_coding') close();
    else if (msg.type === 'coding_info') { info = { ...info, ...(msg.data || {}) }; drawInfo(); drawButtons(); }
    else if (msg.type === 'coding' && msg.data) {
      const fresh = !job || job.id !== msg.data.id;
      job = msg.data;
      if (fresh) { closeView(); confirmTests = false; }
      if (job.phase === 'done' || job.phase === 'failed') { note(''); send({ type: 'code_info' }); }
      if (!layer.hidden) drawJob();
    } else if (msg.type === 'coding_note') note(msg.message);
    else if (msg.type === 'coding_file' && msg.path === viewing) { viewData = msg; drawView(); }
  });

  // ---------- controls ----------
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const request = form.elements.request.value.trim();
    if (request.split(/\s+/).length < 2) { note('Say what to build, in a sentence or two.'); form.elements.request.focus(); return; }
    lastRequest = { type: 'code_start', request };
    if (!send(lastRequest)) { note('Jarvis’s engine isn’t connected, so I can’t start.'); return; }
    note('');
  });
  form.elements.request.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) form.requestSubmit(); });
  $('.cd-follow', layer).addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('.cd-follow input', layer), request = input.value.trim();
    if (request.split(/\s+/).length < 2 || !job) return;
    lastRequest = { type: 'code_change', id: job.id, request };
    if (send(lastRequest)) input.value = '';
  });
  $('.cd-back', layer).addEventListener('click', closeView);
  $('.cd-view-tabs', layer).addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { viewTab = b.dataset.tab; drawView(); } });
  $('.cd-examples', layer).replaceChildren(...EXAMPLES.map((text) => {
    const li = el('li'), b = el('button', 'cd-example', text);
    b.type = 'button';
    b.addEventListener('click', () => { form.elements.request.value = text; form.elements.request.focus(); });
    li.append(b);
    return li;
  }));
  $('.cd-close', layer).addEventListener('click', close);
  layer.addEventListener('mousedown', (e) => { if (e.target === layer) close(); });
  window.addEventListener('keydown', (e) => {   // capture: before the window's own Escape (which leaves full screen)
    if (e.key !== 'Escape' || layer.hidden) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (viewing) closeView(); else close();
  }, true);

  // The way in from the top bar.
  const settings = document.getElementById('settingsBtn');
  if (settings) {
    const button = el('button', 'icon-btn');
    button.type = 'button'; button.id = 'codeBtn'; button.title = 'Coding Mode'; button.setAttribute('aria-label', 'Coding Mode'); button.innerHTML = ICON.code;
    button.addEventListener('click', () => { open(); send({ type: 'code_info' }); });
    settings.before(button);
  }

  window.hideCoding = () => { if (!layer.hidden) close(); };
  window.codingOpen = () => !layer.hidden && !layer.classList.contains('closing');
})();
