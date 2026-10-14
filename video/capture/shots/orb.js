// The orb alone, through its states: resting, listening to a voice, thinking, speaking, resting.
module.exports = {
  kind: 'page', file: 'video/capture/pages/orb.html', size: [1440, 810],
  async run(shot) {
    const state = (name) => shot.js(`window.setOrbState('${name}')`);
    // a voice-like level: syllables with small gaps, as the microphone meter gives while someone talks
    const voice = async (ms) => {
      for (let i = 0; i < ms / (1000 / 30); i++) {
        const t = i / 30;
        const level = Math.max(0, 0.55 + 0.35 * Math.sin(t * 9.1) * Math.sin(t * 3.3 + 1) + 0.2 * Math.sin(t * 23));
        await shot.js(`window.setOrbLevel(${(t % 1.7 > 1.45 ? 0.05 : level).toFixed(3)})`);
        await shot.frame(1);
      }
      await shot.js(`window.setOrbLevel(0)`);
    };
    await shot.frame(90);            // let it settle before the camera rolls
    shot.start();
    shot.mark('idle');      await shot.hold(7000);
    shot.mark('listening'); await state('listening'); await voice(3200);
    shot.mark('thinking');  await state('thinking');  await shot.hold(3000);
    shot.mark('speaking');  await state('speaking');  await shot.hold(5000);
    shot.mark('rest');      await state('idle');      await shot.hold(9000);
  },
};
