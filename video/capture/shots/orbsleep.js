// Trailer, the opening: the orb alone, asleep, then waking and hearing a voice (the orb's own states, on black).
module.exports = {
  kind: 'page', file: 'video/capture/pages/orb.html', size: [1440, 810],
  async run(shot) {
    const state = (name) => shot.js(`window.setOrbState('${name}')`);
    await state('sleeping');
    await shot.frame(150);
    shot.start();
    shot.mark('asleep'); await shot.hold(12000);
    shot.mark('wake'); await state('idle'); await shot.hold(2500);
    shot.mark('listening'); await state('listening');
    for (let i = 0; i < 90; i++) {
      const t = i / 30;
      await shot.js(`window.setOrbLevel(${Math.max(0, 0.55 + 0.35 * Math.sin(t * 9.1) * Math.sin(t * 3.3 + 1) + 0.2 * Math.sin(t * 23)).toFixed(3)})`);
      await shot.frame(1);
    }
    await shot.js(`window.setOrbLevel(0)`);
    shot.mark('speaking'); await state('speaking'); await shot.hold(4000);
  },
};
