// Showcase, sequence 3: the phone and the computer, filmed together. What is asked on the phone happens in the
// computer's window (link.desk.mp4 is that window, in step with the phone, frame for frame).
const { phone, send, shown } = require('./_phone');
module.exports = phone('phone', {
  companion: true,
  async run(shot) {
    await shot.wait(shown('chooseView'), { timeout: 40000 });
    await shot.wait(`!document.getElementById('choosePhone').disabled`, { timeout: 120000 }).catch(() => {});
    await shot.click('#chooseComputer');
    await shot.wait(shown('chatView'));
    await shot.wait(`document.getElementById('app').dataset.brain === 'ready'`, { timeout: 120000 }).catch(() => {});
    await shot.desk.js(`document.getElementById('clearBtn').click()`).catch(() => {});
    await shot.frame(40);
    shot.start();
    await shot.hold(500);
    shot.note('mars', await send(shot, 'Show me Mars'));
    await shot.ctrl('/hush');
    shot.mark('mars');
    await shot.hold(4200);
    await shot.js(`document.getElementById('planetClose') && document.getElementById('planetClose').click()`);
    await shot.hold(500);
    shot.note('journey', await send(shot, 'Distance between Paris and Rome'));
    await shot.ctrl('/hush');
    shot.mark('journey');
    await shot.hold(5200);
    await shot.js(`document.getElementById('earthClose') && document.getElementById('earthClose').click()`);
    await shot.hold(400);
    shot.mark('switch');
    await shot.click('#modeSwitch button[data-mode="phone"]');
    await shot.hold(1200);
    shot.note('alone', await send(shot, 'Graph sine of x over x'));
    shot.mark('alone');
    await shot.hold(4500);
  },
});
