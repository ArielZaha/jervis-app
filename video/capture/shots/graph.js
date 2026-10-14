// Scene 6: one function, drawn and described.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Graph y = x^2 - 4');
    await shot.hold(8000);
    await hush(shot);
    await shot.hold(400);
  },
});
