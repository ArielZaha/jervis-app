// Showcase, sequence 1: "Hey Jarvis", then one spoken sentence that does two things: a timer and the weather window.
const { desktop, say, replies } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await shot.wait(`document.getElementById('connectionText').textContent.trim() === 'Connected'`, { timeout: 40000 });
    await shot.wait(`${replies} > 0`, { timeout: 40000 });
    await shot.ctrl('/hush');
    await shot.frame(40);
    shot.start();
    await shot.hold(600);
    await say(shot, 'Hey Jarvis', { listenMs: 900 });
    await shot.speak();
    await shot.hold(250);
    await say(shot, 'Set a timer for twenty minutes and show me the weather in Paris', { listenMs: 2600 });
    await shot.js('__clock.resync()');   // the timer starts now: the page's clock and the engine's agree from here
    shot.mark('result');
    await shot.speak({ most: 7500 });
    await shot.click('.wx-close');   // back to the main window: the timer he also started is counting down there
    await shot.hold(500);
    shot.mark('timer');
    await shot.hold(3500);
  },
});
