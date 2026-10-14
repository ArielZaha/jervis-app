// Scene 8: the weather window.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'What is the weather in Paris this week?');
    await shot.wait(`document.querySelector('.maplibregl-canvas, .wx-map canvas') !== null`, { timeout: 20000 }).catch(() => {});
    await shot.hold(7000);
    await hush(shot);
    await shot.hold(400);
  },
});
