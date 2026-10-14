// Scene 9: the same app on an Android phone, working on its own: the 3D Earth, on the phone.
const { phone, send, shown } = require('./_phone');
module.exports = phone('android', {
  async run(shot) {
    await shot.wait(shown('chooseView'), { timeout: 40000 });
    await shot.wait(`!document.getElementById('choosePhone').disabled`, { timeout: 120000 }).catch(() => {});
    await shot.click('#choosePhone');
    await shot.wait(shown('chatView'));
    await shot.wait(`document.getElementById('app').dataset.brain === 'ready'`, { timeout: 120000 });
    await shot.frame(30);
    shot.start();
    await shot.hold(700);
    shot.note('globe', await send(shot, 'Distance between Paris and Rome'));
    await shot.until(shown('earthLayer'), { max: 8000 }).catch(() => {});
    shot.mark('globe');
    await shot.hold(8000);
  },
});
