// Not footage: stills of every feature window in one go, for checking a design.  LOOK=next|classic, SIZE=1440x810
const { desktop, ready, ask, hush } = require('./_lib');
const [W, H] = (process.env.SIZE || '1440x810').split('x').map(Number);
const tag = `${process.env.LOOK || 'classic'}_${W}`;
module.exports = desktop({
  size: [W, H],
  async run(shot) {
    const quick = async (text, frames = 40) => { await ask(shot, text, { filmed: false, cps: 300 }); await shot.frame(frames); await hush(shot); await shot.frame(8); };
    await ready(shot);
    await shot.frame(30);
    await quick("What's 15% of 80?");
    await quick('Set a timer for 10 minutes');
    await quick('Will it rain tomorrow in London?', 120);
    await shot.js(`document.querySelector('.wx-close')?.click()`);
    await shot.frame(30);
    await shot.still(`tour_${tag}_1_talk`);
    await quick('How many moons does Saturn have?', 150);
    await shot.still(`tour_${tag}_2_planet`);
    await shot.js(`window.hidePlanet && window.hidePlanet()`);
    await quick('Solve x^2 - 5x + 6 = 0', 60);
    await shot.still(`tour_${tag}_3_steps`);
    await quick('Compare sin(x) and cos(x)', 90);
    await shot.still(`tour_${tag}_4_graph`);
    await shot.js(`window.hideGraph && window.hideGraph()`);
    await quick('Which is farther from Tel Aviv, London or New York?', 150);
    await shot.still(`tour_${tag}_5_globe`);
    await shot.js(`window.hideGlobe && window.hideGlobe()`);
    await quick('What is the weather in Paris this weekend?', 170);
    await shot.still(`tour_${tag}_6_weather`);
    await shot.js(`document.querySelector('.wx-close')?.click()`);
    await shot.frame(30);
    await shot.ctrl('/ui?json=' + encodeURIComponent(JSON.stringify({ type: 'timer_done', data: { label: 'Tea', seconds: 300, count: 1 } })));
    await shot.frame(50);
    await shot.still(`tour_${tag}_7_alert`);
  },
});
