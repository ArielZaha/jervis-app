// The real control bar and glowing edge (control.html), through the states the engine reports during a task:
// looking, deciding, paused by the user, resumed. The words are the engine's own (computer_use.py).
module.exports = {
  kind: 'page', file: 'control.html', query: { shortcut: '⌃⌥Q' }, preload: 'preload-control.js', size: [1440, 810],
  async run(shot) {
    const goal = 'turn on dark mode in Chrome';
    const report = (state, detail, step) => shot.js(`window.__controlEvent(${JSON.stringify(
      { type: 'control', data: { state, detail, goal, step, maxSteps: 25 } })})`);
    await report('starting', 'Getting ready…', 0);
    await shot.frame(10);
    shot.start();
    await shot.hold(900);
    shot.mark('observing'); await report('observing', 'Looking at the screen…', 1); await shot.hold(1500);
    shot.mark('thinking');  await report('thinking', 'Deciding what to do next…', 1); await shot.hold(1500);
    shot.mark('pause');     await shot.click('#pause');
    await report('paused', 'Paused. Say “continue” or press Resume.', 1); await shot.hold(2000);
    shot.mark('resume');    await shot.click('#pause');
    await report('observing', 'Looking at the screen…', 2); await shot.hold(1400);
    shot.mark('stop');      await shot.click('#stop');
    await shot.js(`window.__controlEvent(${JSON.stringify({ type: 'control', data: { state: 'stopped', detail: 'Stopped. You have control again.', goal: '', step: 0, maxSteps: 0 } })})`); await shot.hold(3200);
  },
};
