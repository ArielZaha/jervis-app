// Scene 7: the 3D Earth and the journey between two cities. The flight itself is filmed as a smooth time-lapse.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'What is the distance between Tokyo and New York?');
    await shot.hold(2600);
    shot.mark('fast');
    await shot.speed(2.6, 36);
    await shot.hold(5200);
    await shot.speed(1, 36);
    shot.mark('slow');
    await shot.hold(4500);
    await hush(shot);
    await shot.hold(400);
  },
});
