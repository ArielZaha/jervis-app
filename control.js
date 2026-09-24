// The overlay shown while Jervis uses the mouse and keyboard: what he is doing, and how to stop him.
const ACTIVE = new Set(['starting', 'observing', 'thinking', 'acting', 'waiting', 'paused']);
const ENDED_BADGE = { completed: 'Done', stopped: 'Stopped', error: 'Stopped' };
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
$('shortcut').textContent = params.get('shortcut') || 'Ctrl+Alt+Q';

let state = 'starting';
let questionId = null;

function badgeText() {
  if (questionId) return 'Needs your OK';
  if (ACTIVE.has(state)) return state === 'paused' ? 'AI control paused' : 'AI control active';
  return ENDED_BADGE[state] || 'Stopped';
}

function render(data) {
  state = data.state || state;
  document.body.dataset.state = state;
  const active = ACTIVE.has(state);
  document.body.toggleAttribute('data-ended', !active);
  $('badge').textContent = badgeText();
  if (!questionId) $('detail').textContent = data.detail || '';
  $('step').textContent = active && data.step ? `Step ${data.step} of ${data.maxSteps} · ${data.goal || ''}` : (data.goal || '');
  $('pause').textContent = state === 'paused' ? 'Continue' : 'Pause';
  $('controls').hidden = !active || Boolean(questionId);
}

function ask(message) {
  questionId = message.id;
  $('badge').textContent = badgeText();
  $('detail').textContent = message.question;
  $('question').hidden = false;
  $('controls').hidden = true;
}

function unask(message) {
  if (message.id && message.id !== questionId) return;
  questionId = null;
  $('badge').textContent = badgeText();
  $('question').hidden = true;
  $('controls').hidden = !ACTIVE.has(state);
}

window.control.onEvent((message) => {
  if (message.type === 'control') render(message.data || {});
  else if (message.type === 'control_confirm') ask(message);
  else if (message.type === 'control_confirm_done') unask(message);
});

$('pause').addEventListener('click', () => window.control.act(state === 'paused' ? 'resume' : 'pause'));
$('stop').addEventListener('click', () => window.control.act('stop'));
$('allow').addEventListener('click', () => { if (questionId) window.control.answer(questionId, true); unask({}); });
$('deny').addEventListener('click', () => { if (questionId) window.control.answer(questionId, false); unask({}); });

// The window lets clicks pass through to the app underneath, except over the bar itself.
$('bar').addEventListener('mouseenter', () => window.control.hovering(true));
$('bar').addEventListener('mouseleave', () => window.control.hovering(false));
