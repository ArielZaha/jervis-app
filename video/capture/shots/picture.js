// Scene 8: making a picture, then understanding an attached one.
const path = require('path');
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Generate an image of a lighthouse at sunset', { timeout: 240000 });
    await shot.wait(`[...document.querySelectorAll('#chatLog img')].some((i) => i.complete && i.naturalWidth > 0)`, { timeout: 60000 });
    shot.mark('picture');
    await shot.hold(3800);
    await hush(shot);
    await shot.hold(500);
    await shot.attach('#imageFileInput', path.join(__dirname, '../../assets/images/bicycle.jpg'));
    await shot.wait(`!document.getElementById('attachPreview').hidden`, { timeout: 15000 });
    shot.mark('attached');
    await shot.hold(900);
    await ask(shot, 'What is this?', { timeout: 120000 });
    await shot.hold(4200);
    await hush(shot);
    await shot.hold(500);
  },
});
