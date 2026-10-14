// Scene 8: an ordinary question.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Why is the sky blue?');
    await shot.hold(4500);
    await hush(shot);
    await shot.hold(400);
  },
});
