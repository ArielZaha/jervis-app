// Scene 10: Settings — which AI answers (the local one is a choice), and the computer-control permission.
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  backend: { DEMO_AI: 'ollama' },   // Settings then shows the local AI as the one chosen (it is one of the three choices)
  async run(shot) {
    await ready(shot, { greeting: false });
    shot.start();
    await shot.hold(700);
    await shot.click('#settingsBtn');
    shot.mark('open');
    await shot.hold(3500);
    // scroll the settings sheet down slowly to the computer-control section
    const scroller = `(document.querySelector('#settingsLayer .settings-body') || document.querySelector('#settingsLayer .sheet-card'))`;
    for (let i = 0; i < 75; i++) { await shot.js(`${scroller}.scrollTop += 7`); await shot.frame(1); }
    shot.mark('scrolled');
    await shot.hold(3500);
  },
});
