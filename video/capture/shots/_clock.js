// Not footage: drives the world clock through the real window and engine, checks what it shows against the time
// zone database, and takes stills.  LOOK=next|classic
const { desktop, ready, ask, say, hush } = require('./_lib');
const tag = process.env.LOOK || 'classic';
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok, detail: String(detail) }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); };
const wallIn = (ms, tz, hour12) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12, timeZone: tz }).format(ms).replace(/ /g, ' ');
module.exports = desktop({
  size: (process.env.SIZE || '1440x810').split('x').map(Number),
  async run(shot) {
    const text = (sel) => shot.js(`(document.querySelector(${JSON.stringify(sel)})?.textContent || '').trim()`);
    const rows = () => shot.js(`[...document.querySelectorAll('.wc-row')].map((r) => r.querySelector('.wc-row-name b').textContent + ' ' + r.querySelector('.wc-row-time').textContent)`);
    const pageNow = () => shot.js('Date.now()');
    // What Jarvis says comes from the engine, which runs on the real clock (the page's clock here is hand-driven).
    const saysTimeIn = (reply, tz) => [0, -60000, 60000].some((d) => reply.includes(wallIn(Date.now() + d, tz, true)));
    const settle = async (n = 20) => { await shot.frame(n); await hush(shot); await shot.frame(6); };
    await ready(shot);
    await shot.js(`localStorage.removeItem('jarvis-clock-24h'); localStorage.removeItem('jarvis-clock-compact'); localStorage.removeItem('jarvis-clock-recent')`);

    // 1. Tokyo
    let reply = await ask(shot, 'What time is it in Tokyo?', { filmed: false, cps: 300 });
    await shot.wait('window.clockOpen()', { timeout: 15000 });
    await settle(40);
    let now = await pageNow();
    let shown = `${await text('.wc-hm')} ${await text('.wc-half')}`;
    check('Tokyo: the window opened and shows Tokyo', (await text('#wcCity')) === 'Tokyo' && (await text('.wc-country')) === 'Japan');
    check('Tokyo: the large clock is the time zone database’s time', shown === wallIn(now, 'Asia/Tokyo', true), `${shown} vs ${wallIn(now, 'Asia/Tokyo', true)}`);
    check('Tokyo: Jarvis says that same time', saysTimeIn(reply, 'Asia/Tokyo'), reply);
    check('Tokyo: the reply says the clock is on screen', /world clock is on your screen/.test(reply), reply);
    check('Tokyo: zone line', /Japan Standard Time · UTC\+9$/.test(await text('.wc-zone')), await text('.wc-zone'));
    check('Tokyo: no daylight saving', /Not used here/.test(await text('.wc-facts')), await text('.wc-facts'));
    await shot.still(`clock_${tag}_1_tokyo`);

    // 8. the clock runs by itself
    const s0 = Number(await text('.wc-sec'));
    await shot.frame(90);
    const s1 = Number(await text('.wc-sec'));
    check('The seconds move without reopening', (s1 - s0 + 60) % 60 >= 2 && (s1 - s0 + 60) % 60 <= 4, `${s0} -> ${s1} after 3 s`);

    // 7. 12 / 24 hours
    await shot.click('.wc-seg button[data-hours="24"]');
    await shot.frame(4);
    now = await pageNow();
    check('24-hour clock', (await text('.wc-hm')) === wallIn(now, 'Asia/Tokyo', false).replace(/^24/, '00') && (await text('.wc-half')) === '', await text('.wc-hm'));
    check('24-hour choice is kept', (await shot.js(`localStorage.getItem('jarvis-clock-24h')`)) === 'true');
    await shot.click('.wc-seg button[data-hours="12"]');
    await shot.frame(4);
    check('Back to the 12-hour clock', /^(AM|PM)$/.test(await text('.wc-half')));

    // 10. the same request again: one window, one Tokyo
    await ask(shot, 'What time is it in Tokyo?', { filmed: false, cps: 300 });
    await settle();
    check('Asked again: still one window and one Tokyo', (await shot.js(`document.querySelectorAll('.wc-layer').length`)) === 1 && (await rows()).length === 2, JSON.stringify(await rows()));

    // 2. New York (daylight saving)
    reply = await ask(shot, 'What time is it in New York?', { filmed: false, cps: 300 });
    await settle(30);
    now = await pageNow();
    check('New York replaces Tokyo in the large clock', (await text('#wcCity')) === 'New York');
    check('New York: time', `${await text('.wc-hm')} ${await text('.wc-half')}` === wallIn(now, 'America/New_York', true), await text('.wc-hm'));
    check('New York: daylight saving is reported from the zone’s rules', /Daylight saving(On now|Off now)/.test(await text('.wc-facts')), await text('.wc-facts'));
    await shot.still(`clock_${tag}_2_newyork`);

    // 3 + 4. two places, a different calendar day
    reply = await ask(shot, 'Compare the time in Israel and Los Angeles.', { filmed: false, cps: 300 });
    await settle(30);
    now = await pageNow();
    const list = await rows();
    check('Two places: rows are You, Israel, Los Angeles', list.length === 3 && /^Israel/.test(list[1]) && /^Los Angeles/.test(list[2]), JSON.stringify(list));
    check('Two places: each row has its own time', list[1].endsWith(wallIn(now, 'Asia/Jerusalem', true)) && list[2].endsWith(wallIn(now, 'America/Los_Angeles', true)), JSON.stringify(list));
    check('Two places: Jarvis gives the difference', /Israel is \d+ hours ahead of Los Angeles/.test(reply), reply);
    const laDay = await shot.js(`document.querySelectorAll('.wc-row-time')[2].dataset.day`);
    const dayOf = (tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(now);
    check('Los Angeles: the day tag matches the calendar', (laDay === 'yesterday') === (dayOf('America/Los_Angeles') < dayOf(await shot.js('Intl.DateTimeFormat().resolvedOptions().timeZone'))), `tag "${laDay}"`);
    await shot.still(`clock_${tag}_3_compare`);

    // the timeline: another moment
    await shot.js(`(() => { const s = document.querySelector('.wc-strip').getBoundingClientRect();
      document.querySelector('.wc-strip').dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: s.left + s.width * 0.75, clientY: s.top + 4 })); })()`);
    await shot.frame(3);
    check('Timeline: pointing six hours ahead shows that moment', (await text('.wc-moment')) === 'In 6 h', await text('.wc-moment'));
    check('Timeline: every row moved to that moment', (await rows())[1].endsWith(wallIn(now + 6 * 3600000, 'Asia/Jerusalem', true)), JSON.stringify(await rows()));
    await shot.still(`clock_${tag}_4_scrub`);
    await shot.js(`document.querySelector('.wc-compare').dispatchEvent(new PointerEvent('pointerleave'))`);
    await shot.frame(3);
    check('Timeline: leaving returns to now', (await text('.wc-moment')) === 'Now');

    // adding and removing in the window
    const add = async (name) => { await shot.js(`(() => { const f = document.querySelector('.wc-add'); f.querySelector('input').value = ${JSON.stringify(name)}; f.requestSubmit(); })()`); };
    await add('Kathmandu');
    await shot.wait(`document.querySelectorAll('.wc-row').length === 4`, { timeout: 20000 });
    await shot.frame(10);
    now = await pageNow();
    check('Add a city: Kathmandu joins and becomes the large clock', (await text('#wcCity')) === 'Kathmandu' && /UTC\+5:45$/.test(await text('.wc-zone')), `${await text('#wcCity')} · ${await text('.wc-zone')}`);
    check('Kathmandu: time', `${await text('.wc-hm')} ${await text('.wc-half')}` === wallIn(now, 'Asia/Kathmandu', true));
    // 5. an ambiguous name
    await add('Valencia');
    await shot.wait(`document.querySelectorAll('.wc-note button').length === 2`, { timeout: 20000 });
    check('Ambiguous name: the window asks which one', /Which Valencia\?/.test(await text('.wc-note')), await text('.wc-note'));
    await shot.still(`clock_${tag}_5_ambiguous`);
    await shot.js(`[...document.querySelectorAll('.wc-note button')].find((b) => /Spain/.test(b.textContent)).click()`);
    await shot.frame(10);
    check('Ambiguous name: choosing Spain adds Valencia on Madrid time', (await text('#wcCity')) === 'Valencia' && /UTC\+[12]$/.test(await text('.wc-zone')), await text('.wc-zone'));
    // 6. a place that does not exist
    await add('Zzyzxqq Flarb');
    await shot.wait(`/couldn.t find/.test(document.querySelector('.wc-note').textContent)`, { timeout: 20000 });
    check('Unknown place: said plainly, nothing added', (await rows()).length === 5, await text('.wc-note'));
    await shot.js(`document.querySelector('.wc-row:nth-child(2) .wc-remove').click()`);
    await shot.frame(6);
    check('Remove: Israel is gone', (await rows()).length === 4 && !(await rows()).some((r) => /^Israel/.test(r)), JSON.stringify(await rows()));
    await shot.click('.wc-copy');
    await shot.frame(4);
    check('Copy: the time was put on the clipboard', /Copied/.test(await text('.wc-copy')) && /in Valencia \(UTC/.test(await shot.js(`document.querySelector('.wc-copy').dataset.copied`)), await shot.js(`document.querySelector('.wc-copy').dataset.copied`));
    await shot.js(`document.querySelectorAll('.wc-pick')[0].click()`);
    await shot.frame(6);
    check('Pick a row: your own time goes to the large clock', /time$/i.test(await text('#wcCity')) || (await text('.wc-country')) === 'Your time', await text('#wcCity'));

    // compact
    await shot.click('.wc-view');
    await shot.frame(20);
    check('Compact: only the times', (await shot.js(`getComputedStyle(document.querySelector('.wc-facts')).display`)) === 'none' && (await text('.wc-view')) === 'Details');
    await shot.still(`clock_${tag}_6_compact`);
    await shot.click('.wc-view');
    await shot.frame(8);

    // spoken follow-ups while it is open
    reply = await ask(shot, 'and in London?', { filmed: false, cps: 300 });
    await settle();
    check('"and in London?" adds London', /London/.test(reply) && (await rows()).some((r) => /^London/.test(r)), reply);
    reply = await ask(shot, 'remove Kathmandu', { filmed: false, cps: 300 });
    await settle();
    check('"remove Kathmandu" takes it off', /Removed Kathmandu/.test(reply) && !(await rows()).some((r) => /^Kathmandu/.test(r)), reply);

    // 9. close and open again
    await shot.click('.wc-close');
    await shot.frame(20);
    check('Close: the window is gone', (await shot.js('window.clockOpen()')) === false && (await shot.js(`document.getElementById('clockLayer').hidden`)) === true);
    const frozen = await text('.wc-sec');
    await shot.frame(90);
    check('Closed: its timer has stopped', (await text('.wc-sec')) === frozen);
    reply = await ask(shot, 'what time is it there?', { filmed: false, cps: 300 });
    await settle();
    check('"What time is it there?" reopens it for the last place', (await shot.js('window.clockOpen()')) === true && /It's \d+:\d\d [AP]M in /.test(reply), reply);

    // an unresolvable and a many-zone place, asked aloud
    reply = await ask(shot, 'What time is it in Zzyzxqq Flarb?', { filmed: false, cps: 300 });
    await settle();
    check('Unknown place asked: no time is claimed', /couldn't find a place called/.test(reply) && !/It's \d/.test(reply), reply);
    reply = await ask(shot, 'What time is it in the USA?', { filmed: false, cps: 300 });
    await settle();
    check('A country with several zones: asks which city', /more than one time zone/.test(reply), reply);
    reply = await ask(shot, 'What time is it in Valencia?', { filmed: false, cps: 300 });
    await settle();
    check('Ambiguous place asked: asks which one', /Which Valencia do you mean/.test(reply), reply);
    reply = await ask(shot, 'the one in Venezuela', { filmed: false, cps: 300 });
    await settle();
    now = await pageNow();
    check('…and the answer settles it', saysTimeIn(reply, 'America/Caracas'), reply);

    // 12. the voice path
    await say(shot, 'What time is it in Tokyo, and is it daytime there?');
    await shot.wait(`document.getElementById('wcCity').textContent === 'Tokyo'`, { timeout: 30000 });
    await settle(30);
    reply = await shot.js(`[...document.querySelectorAll('#chatLog .msg.jarvis')].pop().innerText`);
    check('Spoken request: answered and shown', /in Tokyo/.test(reply) && /It's (daytime|night) there/.test(reply), reply);

    // around the world
    reply = await ask(shot, 'Show me the current time around the world.', { filmed: false, cps: 300 });
    await settle(40);
    check('Around the world: six places and you', (await rows()).length === 7, JSON.stringify(await rows()));
    await shot.still(`clock_${tag}_7_world`);

    // another window takes its place, and it takes theirs
    await ask(shot, 'Tell me about Saturn', { filmed: false, cps: 300 });
    await settle(40);
    check('Another window opening closes the clock', (await shot.js('window.clockOpen()')) === false);

    // fixed moments, against the zone rules
    const m = 'window.worldClock.math';
    check('Fixed: New York, a second before clocks go forward (2026-03-08 06:59 UTC)', (await shot.js(`${m}.offsetMinutes(Date.UTC(2026,2,8,6,59), 'America/New_York')`)) === -300);
    check('Fixed: New York, after (07:00 UTC) is UTC−4, daylight saving on', (await shot.js(`${m}.offsetMinutes(Date.UTC(2026,2,8,7,0), 'America/New_York')`)) === -240 && (await shot.js(`${m}.daylightSaving(Date.UTC(2026,2,8,7,0), 'America/New_York')`)) === 'on');
    check('Fixed: New York, 2026-11-01 06:00 UTC is back on UTC−5', (await shot.js(`${m}.offsetMinutes(Date.UTC(2026,10,1,6,0), 'America/New_York')`)) === -300 && (await shot.js(`${m}.daylightSaving(Date.UTC(2026,10,1,6,0), 'America/New_York')`)) === 'off');
    check('Fixed: London in January UTC+0, in July UTC+1', (await shot.js(`${m}.offsetMinutes(Date.UTC(2026,0,15,12), 'Europe/London')`)) === 0 && (await shot.js(`${m}.offsetMinutes(Date.UTC(2026,6,15,12), 'Europe/London')`)) === 60);
    check('Fixed: Sydney daylight saving is in January (southern summer)', (await shot.js(`${m}.daylightSaving(Date.UTC(2026,0,15,12), 'Australia/Sydney')`)) === 'on' && (await shot.js(`${m}.daylightSaving(Date.UTC(2026,6,15,12), 'Australia/Sydney')`)) === 'off');
    check('Fixed: Tokyo never changes', (await shot.js(`${m}.daylightSaving(Date.UTC(2026,6,15,12), 'Asia/Tokyo')`)) === 'none');
    check('Fixed: 07:00 in Tel Aviv on 2026-10-13 is still the 12th in Los Angeles', await shot.js(`(() => { const t = ${m}.instantOf('Asia/Jerusalem', 2026, 10, 13, 7); const a = ${m}.wall(t, 'Asia/Jerusalem'), b = ${m}.wall(t, 'America/Los_Angeles'); return a.day === 13 && b.day === 12 && b.hour === 21; })()`));
    check('Fixed: labels', (await shot.js(`[${m}.utcLabel(345), ${m}.utcLabel(-210), ${m}.utcLabel(0), ${m}.utcLabel(540)].join(' ')`)) === 'UTC+5:45 UTC−3:30 UTC+0 UTC+9');
    const sun = await shot.js(`(() => { const e = ${m}.sunEvents(35.68, 139.69, 2026, 10, 13); const w = (ms) => { const p = ${m}.wall(ms, 'Asia/Tokyo'); return p.hour * 60 + p.minute; }; return [w(e.sunrise), w(e.sunset)]; })()`);
    check('Fixed: Tokyo sunrise and sunset on 2026-10-13 (about 05:46 and 17:08)', Math.abs(sun[0] - (5 * 60 + 46)) <= 3 && Math.abs(sun[1] - (17 * 60 + 8)) <= 3, `${Math.floor(sun[0] / 60)}:${String(sun[0] % 60).padStart(2, '0')} and ${Math.floor(sun[1] / 60)}:${String(sun[1] % 60).padStart(2, '0')}`);
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length} of ${results.length} checks passed` + (failed.length ? `; FAILED: ${failed.map((r) => r.name).join(' | ')}` : ''));
  },
});
