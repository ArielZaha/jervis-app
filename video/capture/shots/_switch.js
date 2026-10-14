// Not footage: flips the window's look from Settings and back, and reports what the page says after each flip.
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  query: { ws: `ws://127.0.0.1:${process.env.PORT || 18940}` },   // no ?ui=: what a person gets
  async run(shot) {
    await ready(shot);
    const report = async (label) => console.log(label, await shot.js(`JSON.stringify({ ui: document.documentElement.dataset.ui, saved: localStorage.getItem('jarvis-look'),
      box: document.getElementById('classicLook').checked, cardCut: getComputedStyle(document.querySelector('.card')).clipPath.slice(0, 12),
      orb: document.getElementById('orbCanvas').style.width, font: getComputedStyle(document.body).fontFamily.split(',')[0] })`));
    await report('start   ');
    await shot.click('#settingsBtn'); await shot.frame(20);
    await shot.click('#classicLook'); await shot.frame(40);
    await report('classic ');
    await shot.still('switch_classic');
    await shot.click('#classicLook'); await shot.frame(40);
    await report('new     ');
    await shot.click('#settingsClose'); await shot.frame(30);
    await shot.still('switch_next');
  },
});
