// Scene 9: the phone app. First with the computer doing the work, then switched to the phone doing it itself.
const { phone, send, shown } = require('./_phone');
module.exports = phone('phone', {
  async run(shot) {
    await shot.wait(shown('chooseView'), { timeout: 40000 });
    await shot.wait(`!document.getElementById('choosePhone').disabled`, { timeout: 120000 }).catch(() => {});
    await shot.frame(30);
    shot.start();
    shot.mark('choose');
    await shot.hold(2200);
    await shot.click('#chooseComputer');
    await shot.until(shown('chatView'), { max: 6000 });
    shot.mark('computer');
    await shot.hold(1500);
    shot.note('computer', await send(shot, 'Play Radiohead on Spotify'));
    await shot.hold(3000);
    await shot.ctrl('/hush');
    shot.mark('switch');
    await shot.click('#modeSwitch button[data-mode="phone"]');
    await shot.hold(1600);
    await shot.wait(`document.getElementById('app').dataset.brain === 'ready'`, { timeout: 120000 });
    shot.note('phone', await send(shot, 'Open Spotify'));
    await shot.hold(2800);
    shot.note('graph', await send(shot, 'Graph x^2 - 4'));
    await shot.until(shown('graphLayer'), { max: 8000 }).catch(() => {});
    shot.mark('graph');
    await shot.hold(5200);
  },
});
