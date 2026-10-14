// Scene 2-3: Jarvis greets, hears "Hey Jarvis", then two typed requests: music and a trailer.
const { desktop, ask, say, hush, replies } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await shot.wait(`document.getElementById('connectionText').textContent.trim() === 'Connected'`, { timeout: 40000 });
    shot.start();
    await shot.until(`${replies} > 0`, { max: 30000 });
    shot.mark('greeting');
    await shot.hold(2300);
    await hush(shot);
    await shot.hold(2200);
    await say(shot, 'Hey Jarvis', { listenMs: 1500 });
    await shot.hold(1700);
    await hush(shot);
    await shot.hold(700);
    await ask(shot, 'Play Radiohead on Spotify');
    await shot.hold(3200);
    await hush(shot);
    await shot.hold(700);
    await ask(shot, 'Show me the trailer for Wednesday');
    await shot.hold(4200);
    await hush(shot);
    await shot.hold(6500);
  },
});
