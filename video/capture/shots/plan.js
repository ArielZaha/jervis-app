// Scene 8: a timer, then a calendar event (Jarvis asks about a reminder first, as he really does).
const { desktop, ready, ask, hush } = require('./_lib');
module.exports = desktop({
  async run(shot) {
    await ready(shot);
    shot.start();
    await shot.hold(400);
    await ask(shot, 'Set a timer for 10 minutes');
    await shot.hold(3200);
    await hush(shot);
    await shot.hold(500);
    await ask(shot, 'Add a dentist appointment tomorrow at 5pm');
    await shot.hold(2800);
    await hush(shot);
    await shot.hold(400);
    await ask(shot, '1 hour before');
    await shot.hold(3400);
    await hush(shot);
    await shot.hold(500);
  },
});
