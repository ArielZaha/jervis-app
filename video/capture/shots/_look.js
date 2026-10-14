// Not footage: stills of the window's look in its main states, for checking a design.  LOOK=next|classic, SIZE=1440x810
const { desktop, ready, ask, say, hush, stateIs } = require('./_lib');
const [W, H] = (process.env.SIZE || '1440x810').split('x').map(Number);
const tag = `${process.env.LOOK || 'classic'}_${W}`;
module.exports = desktop({
  size: [W, H],
  async run(shot) {
    await ready(shot);
    await shot.frame(40);
    await shot.still(`look_${tag}_1_ready`);
    await ask(shot, 'Set a timer for 10 minutes', { filmed: false, cps: 200 });
    await shot.frame(30); await hush(shot); await shot.frame(10);
    await ask(shot, 'Solve x^2 - 5x + 6 = 0', { filmed: false, cps: 200 });
    await shot.frame(40);
    await shot.still(`look_${tag}_2_speaking`);
    await hush(shot); await shot.frame(10);
    await shot.ctrl('/say?text=' + encodeURIComponent('graph sine of x over x'));
    await shot.wait(stateIs('listening'));
    await shot.js(`window.setOrbLevel && window.setOrbLevel(.7)`);
    await shot.frame(40);
    await shot.still(`look_${tag}_3_listening`);
    await shot.ctrl('/heard');
    await shot.wait(`!document.getElementById('graphLayer').hidden`, { timeout: 60000 });
    await shot.frame(70);
    await shot.still(`look_${tag}_4_graph`);
    await hush(shot);
    await shot.js(`window.hideGraph()`);
    await shot.click('#settingsBtn');
    await shot.frame(50);
    await shot.still(`look_${tag}_5_settings`);
    await shot.click('#settingsClose');
    await shot.frame(20);
    await ask(shot, 'What is the distance between Tokyo and New York?', { filmed: false, cps: 200 });
    await shot.frame(120);
    await shot.still(`look_${tag}_6_globe`);
    await hush(shot);
    await shot.js(`window.hideGlobe()`);
    await ask(shot, 'What is the weather in Paris this week?', { filmed: false, cps: 200 });
    await shot.frame(150);
    await shot.still(`look_${tag}_7_weather`);
    await hush(shot);
    await shot.click('.wx-close');
    await shot.frame(30);
    await shot.ctrl('/ui?json=' + encodeURIComponent(JSON.stringify({ type: 'timer_done', data: { label: 'Tea', seconds: 300, count: 1 } })));
    await shot.frame(50);
    await shot.still(`look_${tag}_8_alert`);
  },
});
