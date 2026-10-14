// Not footage: drives Coding Mode through the real window and engine with the real AI, checks what it shows, and takes
// stills. The demo engine is sandboxed: apps are not really opened and outside tools are stand-ins, so this proves the
// window, the wiring and the AI's real answers, not VS Code or the test runner (those are tested outside the sandbox).
const fs = require('fs');
const path = require('path');
const { desktop, ready, ask, say, hush } = require('./_lib');
const tag = process.env.LOOK || 'classic';
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + String(detail).replace(/\s+/g, ' ').slice(0, 260) : ''}`); };
const PROJECTS = path.join(__dirname, '..', '..', 'cache.nosync', 'data', 'projects');
module.exports = desktop({
  size: (process.env.SIZE || '1440x810').split('x').map(Number),
  async run(shot) {
    const text = (sel) => shot.js(`(document.querySelector(${JSON.stringify(sel)})?.textContent || '').trim()`);
    const phase = () => shot.js(`(() => { const s = [...document.querySelectorAll('.cd-steps li')].map((l) => l.dataset.state); return s.join(','); })()`);
    const finished = `(() => { const b = document.querySelector('.cd-primary'); return b && b.textContent === 'Build it' && !document.querySelector('.cd-job').hidden && !document.querySelector('.cd-step').textContent; })()`;
    await ready(shot);

    // the way in, and what the form offers
    await shot.click('#codeBtn');
    await shot.wait('window.codingOpen()', { timeout: 10000 });
    await shot.wait(`/^AI: /.test(document.querySelector('.cd-model').textContent)`, { timeout: 10000 });
    await shot.frame(20);
    check('The top-bar button opens Coding Mode', await shot.js('window.codingOpen()'));
    check('The form is only a description: no language or destination to pick', await shot.js(`!document.getElementById('cdLang') && !document.querySelector('.cd-dest-row') && document.querySelectorAll('.cd-form input').length === 0`));
    check('The model in use is shown', (await text('.cd-model')) === 'AI: openai/gpt-oss-120b', await text('.cd-model'));
    await shot.still(`coding_${tag}_1_empty`);

    // a real build, from the form
    await shot.js(`(() => { const f = document.querySelector('.cd-form'); f.elements.request.value = 'A word counter: a script that counts the words in a text file, with unit tests'; f.requestSubmit(); })()`);
    await shot.wait(`!document.querySelector('.cd-job').hidden`, { timeout: 20000 });
    await shot.wait(`document.querySelectorAll('.cd-file').length > 0`, { timeout: 60000 });
    await shot.frame(6);
    check('While working: a step is lit and the button says Working…', /now/.test(await phase()) && (await text('.cd-primary')) === 'Working…', `${await phase()} · ${await text('.cd-step')}`);
    await shot.still(`coding_${tag}_2_working`);
    await shot.wait(finished, { timeout: 240000 });
    await shot.frame(20); await hush(shot);
    const folder = path.join(PROJECTS, fs.readdirSync(PROJECTS)[0]);
    const made = fs.existsSync(folder) ? fs.readdirSync(folder, { recursive: true }).map(String).filter((p) => /\.\w+$/.test(p)) : [];
    check('The project folder exists with real files', made.some((p) => p.endsWith('.py')), `${folder}: ${made.join(', ')}`);
    check('The window lists the files that exist', (await shot.js(`document.querySelectorAll('.cd-file[data-status="written"]').length`)) >= 1 && (await text('.cd-name')) === path.basename(folder), await text('.cd-files'));
    check('Checks ran and are listed', (await shot.js(`document.querySelectorAll('.cd-check').length`)) >= 1, await text('.cd-checks-sum'));
    check('Plan, Write and Check are done', (await phase()).startsWith('done,done,done'), await phase());
    const spoke = await shot.js(`[...document.querySelectorAll('#chatLog .msg.jarvis')].pop().innerText`);
    check('Jarvis says what happened and what was not run', /I wrote /.test(spoke) && /haven't run it/.test(spoke) && spoke.includes(`It's in ${folder}.`), spoke);
    await shot.still(`coding_${tag}_3_done`);

    // one file
    await shot.js(`document.querySelector('.cd-file[data-status="written"]').click()`);
    await shot.wait(`document.querySelector('.cd-code').textContent.length > 20 && document.querySelector('.cd-code').textContent !== 'Opening…'`, { timeout: 10000 });
    await shot.frame(6);
    const shownName = await text('.cd-view-name');
    check('A file opens with its real content', (await text('.cd-code')) === fs.readFileSync(path.join(folder, shownName), 'utf8').trim(), shownName);
    await shot.still(`coding_${tag}_4_file`);
    await shot.click('.cd-back');

    // a follow-up changes the same project and shows the difference
    await shot.js(`(() => { const f = document.querySelector('.cd-follow'); f.querySelector('input').value = 'Add a --top option that prints the ten most common words'; f.requestSubmit(); })()`);
    await shot.wait(`document.querySelector('.cd-primary').textContent === 'Working…'`, { timeout: 20000 });
    await shot.wait(finished, { timeout: 240000 });
    await shot.frame(20); await hush(shot);
    const changed = await shot.js(`document.querySelectorAll('.cd-file[data-status="changed"]').length`);
    check('Follow-up: files of the same project are marked changed', changed >= 1 && fs.readdirSync(PROJECTS).filter((d) => !d.endsWith('.zip')).length === 1, `${changed} changed; projects: ${fs.readdirSync(PROJECTS).join(', ')}`);
    await shot.js(`document.querySelector('.cd-file[data-status="changed"]').click()`);
    await shot.wait(`document.querySelectorAll('.cd-diff-add').length > 0`, { timeout: 10000 });
    check('The changes are shown as a difference', (await shot.js(`document.querySelectorAll('.cd-diff-add').length`)) > 0 && !(await shot.js(`document.querySelector('.cd-view-tabs').hidden`)));
    await shot.still(`coding_${tag}_5_diff`);
    await shot.click('.cd-back');

    // tests are only run after a second, explicit click
    await shot.js(`[...document.querySelectorAll('.cd-buttons button')].find((b) => b.textContent === 'Run tests…').click()`);
    await shot.frame(4);
    check('Run tests asks first', /runs the project.s own code/.test(await text('.cd-confirm')) && (await shot.js(`document.querySelector('.cd-tests').hidden`)), await text('.cd-confirm'));
    await shot.js(`[...document.querySelectorAll('.cd-buttons button')].find((b) => b.textContent === 'Run the tests').click()`);
    await shot.wait(`!document.querySelector('.cd-tests').hidden && document.querySelector('.cd-tests-sum').textContent !== 'running…'`, { timeout: 60000 });
    check('…and then the result panel appears', /passed|failed|not run/.test(await text('.cd-tests-sum')), await text('.cd-tests-sum'));

    // sending it somewhere else, and a place that can't be used
    await shot.js(`[...document.querySelectorAll('.cd-buttons button')].find((b) => b.textContent === 'Make a zip').click()`);
    await shot.wait(`/\\.zip/.test(document.querySelector('.cd-note').textContent)`, { timeout: 20000 });
    check('Make a zip: a real archive beside the project', fs.readdirSync(PROJECTS).some((d) => d.endsWith('.zip')), await text('.cd-note'));
    await shot.click('.cd-close');
    await shot.frame(16);
    check('Close', (await shot.js('window.codingOpen()')) === false);

    // by voice, with a destination: one sentence does it all
    await say(shot, 'Jarvis, write a bash script that prints the date and put the code in Word.');
    await shot.wait('window.codingOpen()', { timeout: 30000 });
    await shot.wait(finished, { timeout: 240000 });
    await shot.frame(30); await hush(shot);
    const voice = await shot.js(`[...document.querySelectorAll('#chatLog .msg.jarvis')].pop().innerText`);
    const docx = fs.readdirSync(PROJECTS, { recursive: true }).map(String).filter((p) => p.endsWith('.docx'));
    check('Spoken request: written, and a real .docx made', /I wrote /.test(voice) && /Word document/.test(voice) && docx.length === 1, `${voice} | ${docx.join(', ')}`);
    await shot.still(`coding_${tag}_6_voice`);

    console.log(`\n${results.filter(Boolean).length} of ${results.length} checks passed`);
  },
});
