// Showcase, sequence 2a: one spoken thread of mathematics. An equation solved and drawn, a second function laid over
// it, and a question about the two.
const { desktop, ready, say } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(300);
    await say(shot, 'Solve x squared minus five x plus six equals zero and draw the function', { listenMs: 2600 });
    await shot.speak({ most: 4200 });
    await shot.hold(300);
    await say(shot, 'Compare x squared and x plus one', { listenMs: 1700 });
    await shot.speak({ most: 4600 });
    await shot.hold(300);
    await say(shot, 'Where do they meet', { listenMs: 1000 });
    await shot.speak({ most: 5000 });
    await shot.hold(1200);
  },
});
