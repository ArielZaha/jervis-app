// Not footage: the short check of Coding Mode with the real AI: the form is only a description, a request with no
// place named is built straight away, a named place is honoured, and a bare "write a query" stays in the chat.
const fs = require('fs');
const path = require('path');
const { desktop, ready, ask, hush } = require('./_lib');
const tag = process.env.LOOK || 'classic';
const PROJECTS = path.join(__dirname, '..', '..', 'cache.nosync', 'data', 'projects');
let passed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; passed += ok ? 1 : 0; console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + String(detail).replace(/\s+/g, ' ').slice(0, 300) : ''}`); };
module.exports = desktop({
  size: [1440, 810],
  async run(shot) {
    const text = (sel) => shot.js(`(document.querySelector(${JSON.stringify(sel)})?.textContent || '').trim()`);
    const finished = `(() => { const b = document.querySelector('.cd-primary'); return b && b.textContent === 'Build it' && !document.querySelector('.cd-job').hidden && !document.querySelector('.cd-step').textContent; })()`;
    const last = () => shot.js(`[...document.querySelectorAll('#chatLog .msg.jarvis')].pop().innerText`);
    await ready(shot);
    await shot.click('#codeBtn');
    await shot.wait(`/^AI: /.test(document.querySelector('.cd-model').textContent)`, { timeout: 15000 });
    await shot.frame(20);
    check('The form is only a description: nothing to pick', await shot.js(`!document.getElementById('cdLang') && !document.querySelector('.cd-dest-row') && document.querySelectorAll('.cd-form input').length === 0`));
    check('Code is written by Groq\'s larger model', (await text('.cd-model')) === 'AI: openai/gpt-oss-120b', await text('.cd-model'));
    await shot.still(`coding_${tag}_1_empty`);
    await shot.click('.cd-close');
    await shot.frame(16);

    let reply = await ask(shot, 'Make a snake game', { filmed: false, cps: 300 });
    check('No language, no place: Jarvis starts at once, without a question', /On it/.test(reply) && !/Where should I put it/.test(reply), reply);
    await shot.wait(finished, { timeout: 300000 });
    await shot.frame(30); await hush(shot);
    reply = await last();
    const made = fs.readdirSync(PROJECTS);
    check('It chose a language itself, wrote the project and says where it is', /I wrote /.test(reply) && made.length === 1 && reply.includes(`It's in ${path.join(PROJECTS, made[0])}.`) && (await text('.cd-name')) === made[0], reply);
    check('Nothing was opened unasked', !/open in|It's open/.test(reply));
    console.log('     files: ' + (await shot.js(`[...document.querySelectorAll('.cd-file-name')].map((n) => n.textContent).join(', ')`)) + ' | checks: ' + (await text('.cd-checks-sum')));
    await shot.still(`coding_${tag}_3_done`);
    await shot.click('.cd-close');
    await shot.frame(16);

    reply = await ask(shot, 'Write a bash script that prints the date and open it in VS Code', { filmed: false, cps: 300 });
    await shot.wait(finished, { timeout: 300000 });
    await shot.frame(30); await hush(shot);
    reply = await last();
    check('A place said in the sentence is still honoured', /I wrote /.test(reply) && /open in Visual Studio Code/.test(reply), reply);
    await shot.click('.cd-close');
    await shot.frame(16);
    reply = await ask(shot, 'Write a SQL query that lists the ten best customers by revenue', { filmed: false, cps: 300 });
    await shot.frame(10); await hush(shot);
    check('A bare "write a query" stays an answer in the chat', /SELECT/i.test(reply), reply);
    reply = await ask(shot, 'what is 12 times 12', { filmed: false, cps: 300 });
    check('Other features still answer', /144/.test(reply), reply);
    console.log(`\n${passed} of ${total} checks passed`);
  },
});
