// Not footage: the bottom of the window (command bar, volume, hints) and the left rail, at the size of a 1470x956 screen.
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  size: [1470, 912],
  async run(shot) {
    await ready(shot);
    await shot.frame(30);
    await shot.still('vol_ready');
    await shot.js(`document.getElementById('speakVolSlider').value = 40; document.getElementById('speakVolSlider').dispatchEvent(new Event('input', { bubbles: true }))`);
    await shot.click('#connectBtn');
    await shot.frame(40);
    await shot.still('vol_muted');
  },
});
