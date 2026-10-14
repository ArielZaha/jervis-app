// Trailer, the awakening: Jarvis asleep (he was told goodnight), then his name is said and he wakes and greets.
const { desktop, ready, replies, stateIs } = require('./_lib');
module.exports = desktop({
  backend: { DEMO_WAKE: 'on' },
  async run(shot) {
    await ready(shot);
    // put him to sleep the way a person does (not filmed)
    await shot.ctrl('/say?text=' + encodeURIComponent('Goodnight Jarvis'));
    await shot.wait(stateIs('listening'), { timeout: 20000 });
    await shot.ctrl('/heard');
    await shot.wait(`document.getElementById('appShell').dataset.state === 'speaking'`, { timeout: 30000 });
    await shot.ctrl('/hush');
    await shot.wait(stateIs('sleeping'), { timeout: 30000 });
    await shot.frame(90);
    shot.start();
    shot.mark('asleep');
    await shot.hold(6500);
    const before = await shot.js(replies);
    await shot.ctrl('/say?text=' + encodeURIComponent('Hey Jarvis'));
    shot.mark('called');
    await shot.hold(1100);
    await shot.ctrl('/heard');
    await shot.until(`${replies} > ${before}`, { max: 30000 });
    shot.mark('awake');
    await shot.speak();
    await shot.hold(8000);
  },
});
