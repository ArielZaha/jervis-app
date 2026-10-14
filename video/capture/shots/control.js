// Scene 4: a request that needs the mouse and keyboard. Jarvis asks first; the film shows the question and "Allow".
// (backend.py holds the task back after the click: nothing on this computer is really controlled.)
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(500);
    await shot.type('#typeInput', 'Use my computer to turn on dark mode in Chrome');
    await shot.hold(260);
    shot.mark('sent');
    await shot.js(`document.getElementById('typeForm').requestSubmit()`);
    await shot.hold(400);
    await shot.wait(`!document.getElementById('controlLayer').hidden`, { timeout: 60000 });
    shot.mark('asked');
    await shot.hold(4200);
    shot.mark('allow');
    await shot.click('#controlAllow');
    await shot.hold(1400);
  },
});
