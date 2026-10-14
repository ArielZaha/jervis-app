// Things the phone shots share. The phone app is the real phone_client.html, served by the real relay, paired with
// the demo engine through the real one-time pairing link (what the QR code on the computer holds).
const you = `document.querySelectorAll('.row.you').length`;
const shown = (id) => `!document.getElementById('${id}').hidden`;
const answered = `(() => { const rows = [...document.querySelectorAll('#thread > .row')]; const mine = rows.map((r) => r.classList.contains('you')).lastIndexOf(true);
  return !document.querySelector('.typing') && rows.slice(mine + 1).some((r) => r.classList.contains('jarvis') && r.querySelector('.text') && r.querySelector('.text').innerText.trim()); })()`;

const phone = (kind, extra) => ({
  kind, size: kind === 'android' ? [412, 916] : [394, 852], backend: true, relay: true,
  open: async ({ ctrl, sleep }) => { await sleep(2500); return (await ctrl('/pair')).pairUrl; },
  ...extra,
});

// Type into the message box and send; resolves when Jarvis has answered.
async function send(shot, text, { timeout = 90000 } = {}) {
  const before = await shot.js(you);
  await shot.type('#input', text, { cps: 16 });
  await shot.hold(300);
  shot.mark(`sent:${text}`);
  await shot.js(`document.getElementById('composer').requestSubmit()`);
  await shot.until(`${you} > ${before}`, { max: 8000 });
  await shot.hold(350);
  await shot.wait(answered, { timeout });
  shot.mark(`reply:${text}`);
  return shot.js(`[...document.querySelectorAll('.row.jarvis')].pop().innerText`);
}
module.exports = { phone, send, shown, answered };
