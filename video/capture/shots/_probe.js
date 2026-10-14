// Not footage: asks the real engine each line the film wants to show and writes down what it answers.
const fs = require('fs');
const path = require('path');
const { desktop, ready, ask, hush } = require('./_lib');
const LINES = (process.env.PROBE || '').split('|').filter(Boolean);
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    const out = [];
    for (const [i, line] of LINES.entries()) {
      let reply;
      try { reply = await ask(shot, line, { filmed: false, cps: 200 }); } catch (e) { reply = 'ERROR ' + e.message; }
      await shot.frame(45);
      await shot.still(`probe_${process.env.PROBE_TAG || ''}${i}`);
      out.push(`> ${line}\n${reply}\n  opened: ${JSON.stringify((await shot.ctrl('/state')).actions.slice(-4))}`);
      await hush(shot).catch(() => {});
      await shot.frame(10);
    }
    fs.writeFileSync(path.join(__dirname, '../../cache.nosync/probe.txt'), out.join('\n\n') + '\n');
  },
});
