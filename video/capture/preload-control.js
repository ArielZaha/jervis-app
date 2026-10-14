// For filming control.html (the bar shown while Jarvis uses the mouse and keyboard): the hand-driven clock, and the
// small bridge the real window gets from control-preload.js. Events are fed in by the shot.
require('./clock.js');
window.control = {
  onEvent: (callback) => { window.__controlEvent = callback; },
  act: (action) => { (window.__controlActs = window.__controlActs || []).push(action); },
  answer: () => {}, hovering: () => {},
};
window.addEventListener('DOMContentLoaded', () => {
  // The bar floats over whatever is on the screen. Here: a plain dark desktop, nothing pretending to be an app.
  const style = document.createElement('style');
  style.textContent = `html { background:
    radial-gradient(1200px 700px at 22% 18%, #16233f 0%, transparent 60%),
    radial-gradient(1000px 800px at 85% 90%, #231a3d 0%, transparent 62%), #070a12; }`;
  document.head.appendChild(style);
});
