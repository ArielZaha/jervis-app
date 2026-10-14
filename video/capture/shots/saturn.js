// Scene 7: Saturn in 3D.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Tell me about Saturn');
    await shot.hold(9000);
    await hush(shot);
    await shot.hold(400);
  },
});
