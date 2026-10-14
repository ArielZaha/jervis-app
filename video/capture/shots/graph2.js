// Scene 6: two functions on one graph, where they meet and the area between them.
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Compare y = x^2 and y = x + 1');
    await shot.hold(9000);
    await hush(shot);
    await shot.hold(400);
  },
});
