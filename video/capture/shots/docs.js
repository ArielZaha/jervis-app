// Scene 5: writing a document, then changing it. (The browser is a stand-in; the story and the replies are Jarvis's.)
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Write a short story about exploring space in Google Docs');
    shot.note('first', (await shot.ctrl('/doc')).doc);
    await shot.hold(3000);
    await hush(shot);
    await shot.hold(600);
    await ask(shot, 'Make it shorter');
    shot.note('shorter', (await shot.ctrl('/doc')).doc);
    await shot.hold(3000);
    await hush(shot);
    await shot.hold(600);
  },
});
