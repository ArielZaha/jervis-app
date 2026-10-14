// Scene 6 (end): an equation solved step by step, in the conversation.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Solve x^2 - 5x + 6 = 0');
    await shot.hold(5500);
    await hush(shot);
    await shot.hold(500);
  },
});
