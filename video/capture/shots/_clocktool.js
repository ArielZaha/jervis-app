// Not footage: a time question worded so that only the AI can route it, to see the world_clock tool's result come
// back through the AI and the window open.  LOOK=next|classic
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  size: [1440, 810],
  async run(shot) {
    const wallIn = (ms, tz) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz }).format(ms).replace(/ /g, ' ');
    await ready(shot);
    const reply = await ask(shot, 'I wonder what the time is in Lisbon at this hour', { filmed: false, cps: 300 });
    await shot.frame(40); await hush(shot);
    const open = await shot.js('window.clockOpen()');
    const city = await shot.js(`document.getElementById('wcCity').textContent`);
    const said = [0, -60000, 60000].some((d) => reply.replace(/ /g, ' ').includes(wallIn(Date.now() + d, 'Europe/Lisbon')));
    console.log(`${open && city === 'Lisbon' ? 'PASS' : 'FAIL'}  The AI called world_clock and the window opened on Lisbon  — ${city}`);
    console.log(`${said ? 'PASS' : 'FAIL'}  The AI's answer carries the tool's real time (${wallIn(Date.now(), 'Europe/Lisbon')})  — ${reply.replace(/\n+/g, ' ')}`);
  },
});
