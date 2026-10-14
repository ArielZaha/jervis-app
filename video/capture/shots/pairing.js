// Scene 10: "Connect my phone" — the pairing code on the computer (a one-time code of this throwaway demo engine).
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  relay: true,
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await shot.type('#typeInput', 'Connect my phone');
    await shot.hold(260);
    shot.mark('sent');
    await shot.js(`document.getElementById('typeForm').requestSubmit()`);
    await shot.hold(300);
    await shot.wait(`!document.getElementById('phonePairingLayer').hidden`, { timeout: 60000 });
    shot.mark('code');
    await shot.hold(6000);
  },
});
