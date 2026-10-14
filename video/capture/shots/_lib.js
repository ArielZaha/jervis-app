// Things several shots do with the real Jarvis window.
const WS = `ws://127.0.0.1:${process.env.PORT || 18940}`;
// LOOK=next records the window's new look; the three films were made with the classic one.
const desktop = (extra) => ({ kind: 'desktop', file: 'index.html', query: { ws: WS, ui: process.env.LOOK || 'classic' }, size: [1440, 810], backend: true, ...extra });

const replies = `document.querySelectorAll('#chatLog .msg.jarvis').length`;
const stateIs = (name) => `document.getElementById('appShell').dataset.state === '${name}'`;

// The window is connected to a freshly started engine, which greets ("Good evening, Sir") as it does on a normal start.
async function ready(shot, { greeting = true } = {}) {
  await shot.wait(`document.getElementById('connectionText').textContent.trim() === 'Connected'`, { timeout: 40000 });
  if (greeting) {
    await shot.wait(`${replies} > 0`, { timeout: 40000 });
    await shot.ctrl('/hush');
    await shot.wait(stateIs('idle'));
  }
  await shot.frame(20);
}

// Type a request and send it; resolves when Jarvis's reply is on screen. `filmed` keeps the camera rolling while
// he thinks (the page's own time); otherwise the thinking is skipped, as an editor would cut it.
async function ask(shot, text, { filmed = true, cps = 17, timeout = 90000 } = {}) {
  const before = await shot.js(replies);
  await shot.type('#typeInput', text, { cps });
  await shot.hold(260);
  shot.mark(`sent:${text}`);
  await shot.js(`document.getElementById('typeForm').requestSubmit()`);
  if (filmed) await shot.hold(500);
  await shot.wait(`${replies} > ${before}`, { timeout });
  shot.mark(`reply:${text}`);
  return shot.js(`[...document.querySelectorAll('#chatLog .msg.jarvis')].pop().innerText`);
}

// Say something to Jarvis out loud (staged: the phrase goes in where the microphone's text does, and the orb is fed
// a voice-shaped level, as the microphone meter feeds it while someone talks). The orb listens for `listenMs`, then
// he answers. Word it the way speech-to-text would: "x squared", not "x^2".
async function say(shot, text, { listenMs = 1500, timeout = 90000 } = {}) {
  const before = await shot.js(replies);
  await shot.ctrl('/say?text=' + encodeURIComponent(text));
  await shot.until(stateIs('listening'), { max: 6000 });
  shot.mark(`listening:${text}`);
  for (let i = 0; i < listenMs / (1000 / 30); i++) {
    const t = i / 30;
    const level = Math.max(0, 0.55 + 0.35 * Math.sin(t * 9.1) * Math.sin(t * 3.3 + 1) + 0.2 * Math.sin(t * 23));
    await shot.js(`window.setOrbLevel && window.setOrbLevel(${(t % 1.7 > 1.45 ? 0.05 : level).toFixed(3)})`);
    await shot.frame(1);
  }
  await shot.js(`window.setOrbLevel && window.setOrbLevel(0)`);
  await shot.ctrl('/heard');
  shot.mark(`heard:${text}`);
  await shot.hold(300);
  await shot.wait(`${replies} > ${before}`, { timeout });
  shot.mark(`reply:${text}`);
}

async function hush(shot) {
  await shot.ctrl('/hush');
  await shot.wait(`!(${stateIs('speaking')})`);
}

module.exports = { WS, desktop, ready, ask, say, hush, replies, stateIs };
