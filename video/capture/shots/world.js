// Showcase, sequence 2b: the Earth and beyond, in one spoken thread. A journey, a sunrise, a planet.
const { desktop, ready, say } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(300);
    await say(shot, 'What is the distance between Tokyo and New York', { listenMs: 1900 });
    await shot.speak({ most: 2600 });
    shot.mark('fast');
    await shot.speed(3, 30);
    await shot.hold(4200);
    await shot.speed(1, 30);
    shot.mark('slow');
    await shot.hold(2200);
    await say(shot, 'Show sunrise over Tokyo', { listenMs: 1200 });
    await shot.speak({ most: 5200 });
    await shot.hold(400);
    await say(shot, 'Tell me about Saturn', { listenMs: 1100 });
    await shot.speak({ most: 6000 });
    await shot.hold(1500);
  },
});
