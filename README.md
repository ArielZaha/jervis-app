# Jervis

A voice assistant for your computer: say "Hey Jervis", then ask for music, videos, shows, timers, documents and more,
or have him use the mouse and keyboard for you. His AI runs on your own computer: no account and no API key.
Runs on **Windows 10/11** and **macOS** (Apple silicon). Made by Ariel & Shalev.

## Install

Download the installer from <https://arielzaha.github.io/jervis/> (or the
[latest release](https://github.com/ArielZaha/jervis-app/releases/latest)):

- **Windows:** run `Jervis Setup.exe`. If SmartScreen still says "Windows protected your PC" (a signed installer can
  take a little reputation-building time with Microsoft after each new release), click *More info*, then
  *Run anyway*. No administrator rights needed; Jervis is added to the Start menu and the desktop.
- **macOS:** open the `.dmg`, drag Jervis to Applications, open it. The first time, macOS says it can't check it for
  malware: open *System Settings > Privacy & Security* and click *Open Anyway*.

On the first start Jervis downloads his AI engine ([Ollama](https://ollama.com)), the `llama3.2` model and an offline
speech model (about 3.5 GB on Windows, 2.5 GB on a Mac), with the progress in his window. Everything that doesn't need
the AI works meanwhile. If you already run Ollama, he uses yours. Then say **"Hey Jervis"**.

Everything else is in **Settings** (the gear at the top right): microphone, voice, the wake phrase, which AI answers,
computer control, the weather city, privacy, optional services, and starting when you sign in. Settings, logs,
transcripts and pictures live in `%APPDATA%\Jervis` (Windows) or `~/Library/Application Support/Jervis` (macOS).

## Spotify

Jervis controls the Spotify app on the computer; no keys and no Premium needed. "Play My Favorite Songs on Spotify"
opens Spotify's Quick Search, types the request and presses Shift+Enter (Spotify's own "play the selected result"), then
checks the music changed; your own playlists come first. Pause, resume, next and previous use Spotify's AppleScript on a
Mac and the media keys on Windows; jumping to a minute works on a Mac. On a Mac this needs the Accessibility permission
(without it Jervis opens the search and you press play). Your own Spotify developer keys in Settings, Optional services,
switch to Spotify's online interface instead (Premium).

## Which AI answers

- **By default, the AI on your computer:** `llama3.2` through Ollama for answers and Whisper (via faster-whisper)
  for speech, English and Hebrew (see **Hebrew** below). After the first start both work offline. On computers with
  16 GB of memory he also installs `qwen2.5vl:3b`, so he can look at pictures and the screen (Settings, AI can turn it
  on or off).
- **A stronger local model, when installed:** each job gets the best installed model (`local_llm.model_for`):
  planning, code and computer control use `qwen2.5-coder:7b` (else `qwen2.5:7b`, `llama3.1:8b`, `qwen3:8b`...), and
  chat uses the same one, since an 8 GB GPU holds one 7B model at a time and swapping costs ~4 s (the Settings
  default `OLLAMA_MODEL=llama3.2` doesn't count as a choice; any other value does). Hebrew is translated by DictaLM
  (below). Override with `JERVIS_AGENT_MODEL` / `JERVIS_CHAT_MODEL` / `JERVIS_HEBREW_MODEL` /
  `JERVIS_TRANSLATE_MODEL` / `JERVIS_NLU_MODEL` in `.env`.
  Every call names its context size (16k; 4k for DictaLM so it stays on the GPU), so Ollama never reloads a
  model between chat and commands, and never picks its own 32k-64k default (llama3.2 at 64k: 10 GB, partly on CPU).
- **Understanding what you mean** (`nlu.py`): speech → text → a deterministic rewrite (Hebrew and mixed commands —
  "תיצור קובייה", "תעשה אותה פי שתיים יותר גבוהה", "open Spotify ותפעיל את השיר הזה" — and known speech slips like
  "open blend ever", "spot if I", "make the cube girl") → the command handlers. What they still don't recognise, if
  it reads like a command (or is a short follow-up while working in Blender), goes to the local model as a
  **structured intent** from a closed list (`open_app`, `object_resize`, `undo`, `clarify`...; never code), checked
  against what was actually said, and turned back into the canonical English command for the same handlers.
  Unclear ("make it", "take it to a level") gets one short question, and the answer completes it ("taller").
  Chit-chat never becomes an action. `python nlu_eval.py [--heldout|--fresh] [models...]` scores models on Jervis's
  own language test set (English, Hebrew, mixed, speech slips, follow-ups, noise).
- **Hebrew** (`language.py`, `stt_local.py`): speak Hebrew, English, or both in one sentence ("תפתח Blender
  ותיצור detailed house") — no setting to switch.
  - *Hearing:* on an NVIDIA GPU, Whisper `small` tells the language of each sentence (no mistakes on 60 real
    recordings), Whisper large-v3-turbo writes English, and **ivrit.ai's Whisper large-v3** (Apache-2.0) writes Hebrew,
    mixed-in English words included. Only the model for the language you're speaking stays on the GPU (Hebrew: 1.8 GB,
    English: 1.6 GB); switching language loads the other one in the background (a few seconds; meanwhile the loaded
    one still answers). Measured on real recorded Hebrew (FLEURS): 15.8% word errors (20.6% with background noise),
    vs 17.3% / 26.0% for ivrit.ai's turbo, for ~0.2 s more on a short command. `JERVIS_HEBREW_SPEECH=turbo` (Settings,
    advanced) picks the turbo. Recordings are resampled properly (libswresample) before Whisper hears them. Without a
    usable GPU: `small` (Hebrew, weaker) + `base.en`. Settings, Voice, "Languages I speak: English only" goes back to
    `base.en` alone.
  - *Understanding:* a Hebrew request is translated into English before anything else sees it — the everyday
    commands by `nlu.py`'s rules (instant), the rest by **DictaLM 2.0** (Dicta, Apache-2.0, 4.4 GB, ~0.5 s) — so every
    command, the Blender and code agents, chat and its tools, follow-ups and corrections work exactly as in English.
    File names, paths and code never go through the model. A translation is checked before anything acts on it: one
    that lost an English word or a number, gained or lost a "delete/close/send" or a "don't", or invented a name, is
    said back ("רק לוודא שהבנתי: ... לעשות את זה?") and only done after "כן"; garbled speech gets "say it again".
    Translations are plain one-line answers (twice as fast as JSON, ~0.25 s); a translation that contains words that
    are neither English (CMUdict) nor in what was said is treated as unsure.
  - *Answering:* replies are translated back by DictaLM (code blocks, paths, numbers and program output untouched;
    English kept if a translation fails its checks) and spoken by a **natural Hebrew voice**: the Piper voice "Shaul"
    with the phonikud diacritizer and pronunciation (`hebrew_voice.py`, ~0.2 s a sentence on the CPU, 380 MB
    downloaded once with the Hebrew models). Heard back by Whisper it comes through with 3.3% letter errors, vs 6.0%
    for Windows' Asaf, which stays the fallback (and `JERVIS_HEBREW_VOICE=windows` picks it). English words in a Hebrew
    sentence are said through CMUdict, with an accent. Licenses: the voice is CC BY-NC (non-commercial use only),
    phonikud CC BY 4.0, CMUdict BSD. He answers in the language you last spoke (Settings, Voice, "Jervis answers in"
    can fix it).
  - *On an 8 GB GPU* (`local_llm.gpu_slot`): Ollama can't see the GPU memory other programs use (the speech
    models' ~1.8 GB, Discord, a game), loaded whole models anyway, and Windows moved the overflow to system RAM —
    answers became 20-50x slower (minutes, in a real session). Now, before a model loads, Jervis unloads his other
    model, measures what's really free (`nvidia-smi`) and asks for only the layers that fit (the rest run on the CPU:
    slower, never stuck); one model loads at a time. Plain talk (no tools, numbers or pictures) is answered by the
    bilingual DictaLM in one call — Hebrew from the Hebrew, English while DictaLM is the model loaded — so a Hebrew
    conversation doesn't swap models; the agent's coder model is loaded only for commands, building and code (a swap
    of ~4-7 s). The two translation directions share one prompt, so it stays cached between them. A translator that
    fails is reported at once (in Hebrew) instead of queuing more calls. `JERVIS_GPU_FIT=off` /
    `JERVIS_GPU_MARGIN_MB` adjust it. "היי ג'רביס" still wakes him.
  - *Timing:* every request leaves one line in `logs/jervis.log` — `Turn 7 (spoken, he): stt 0.8s · understand 1.8s
    (model) · command 0.0s · reply-translate 1.1s · speak 2.3s · total 6.0s [program task running]` — never the words;
    every model call logs its load, prompt and generation time, and every GPU plan how many layers fit.
- **Exact numbers:** for a question with numbers in it ("3 apples plus 2 dozen, minus 7?"), the model writes a tiny
  calculation that `reasoning.py` runs (plain arithmetic only), and the answer is told the exact result.
- **Optional, faster:** paste a free key from <https://console.groq.com> into Settings, AI. He then answers with
  `openai/gpt-oss-20b` on Groq and falls back to the local AI by himself when Groq can't be reached or is rate limited.
  The real reason for any failed AI call is written to `logs/ai_errors.log` in his data folder.

## Computer control

Ask for something on screen, like "click Save", "scroll down", "type hello into the search box" or "use my computer
to turn on dark mode in Chrome". Jervis works in a loop: he reads the window in front through the system's
accessibility interface (UI Automation on Windows, the Accessibility API on macOS), picks one action, does it, waits
for the screen to settle and checks what changed before the next step.

- **Always visible:** while he works, a glowing edge and a bar ("AI control active", the current step, Pause, Stop)
  sit on top of everything. His own window steps aside.
- **Instant stop:** move the mouse (he pauses), press **Ctrl+Alt+Q** (**Control-Option-Q** on a Mac), press Stop, or
  say "stop". Switching to another app also pauses him.
- **Asks first:** by default before each task (Settings, Computer control: ask / allowed / off), and always before
  a risky step: sending, posting, buying, deleting, installing, signing out, or pressing Enter in a chat or mail app.
- **Never:** types into password fields, presses the emergency shortcut, or runs more than 25 steps per task.
- **Privacy:** screenshots are only ever looked at by the local vision model, never sent anywhere, unless you turn on
  *Settings, Computer control, "Look at the screen with" > Online* yourself (some apps, like Spotify, don't expose
  anything to accessibility at all, so this is the only way Jervis can find things in them without a local vision
  model). With a Groq key, the list of buttons and fields in the window (not a picture of the screen) goes to Groq
  along with the request either way.

- **Moves like a hand:** the pointer glides to its target (a short, smooth arc that speeds up and slows down,
  `pointer_motion.py`) instead of jumping, and only clicks once it has arrived. Grab the mouse during a glide and he
  stops at once, without clicking, and pauses.

On macOS, turn on Jervis in *System Settings > Privacy & Security > Accessibility*; macOS asks the first time.

**Write where your cursor is** (`write_here.py`). Put the cursor in a document, an email, a chat box or a code
editor and say "write me a story about someone who discovers a secret island" (or "type a short reply here"). He
writes exactly the text asked for, brings that window back (the app puts its own caret back), checks the cursor is
still in an editable, non-password field, types it (short text) or pastes it (long text and code — your clipboard is
put back afterwards), then **reads the field back** to check the text really arrived. A plain "write me a story"
typed into Jervis's own window stays a chat answer; "write it here", or saying it while you're in a text app, types it.

**Questions about your screen** (`screen_reader.py`): "what's on my screen?", "what does this error say?", "explain
this error". He reads the window you're working in through the accessibility interface (app, window, dialogs,
buttons, fields and their text — password fields never) and answers from that; only a window that shows almost nothing
that way (a 3D viewport, a game) is looked at by the local vision model. Reading only: nothing is clicked or typed.

How far he gets depends on the AI. With `gpt-oss-20b` on Groq (a free key), multi-step tasks work well: "set the
font size in TextEdit to 18" took one step. Locally, the controls use the strongest installed model (see *Which AI
answers*); a 3B model like `llama3.2` handles short, simple tasks but often misses when it's done or wanders. With the
local AI a task is capped at 20 steps, repeats that change nothing are refused, and he stops when he's stuck.

## Building things in apps: the agent (Blender, Minecraft)

"Open Blender and build a small house with a red roof", then "add a tree next to it", "make it two times bigger",
"color the roof green", "undo". Simple commands ("create a cube", "make it red", "rotate it 45 degrees") run
instantly with no AI (`blender_commands.py`). Anything else goes to the agent (`agent_core.py`), all local and free:

1. **Plan:** one call to the local model returns the steps, each with code, plus checks for the whole request.
2. **Act** through the most reliable channel the app has: Blender runs the code itself through its scripting bridge
   (`blender_bridge.py`, loaded by Blender on every start), using a small forgiving building kit (`blender_kit.py`:
   `box`, `roof`, `cylinder`, `color`, `move`, `top`...) instead of raw `bpy`.
3. **Observe and verify:** the real scene is read back and every check is evaluated in plain code: does it exist,
   is it the right color, does it rest on what it should. Things floating in the air are set down, and new things
   built inside existing ones are moved beside them, automatically.
4. **Repair:** a failed step is undone and the model gets the exact error, the failed checks and the real state, and
   tries again. If something is still missing at the end, one fix-up step targets exactly that.
5. **Report only what was verified** ("I checked it in Blender: 9 of 9 checks passed"), or say plainly what didn't
   work. Clearing the scene or deleting things you didn't ask about is refused, and "undo" puts everything back.

Builds that worked cleanly the first time are remembered (`agent_memory.json`) as examples for similar requests.

**Modeling quality, not just "it exists".** The kit is a procedural modeling toolkit, so the model can build things the
way an artist would rather than stacking primitives: `blob()` (rocks, foliage clusters, bushes), `tube()` along a
curving `path()` (trunks, branches, curved legs), `lathe()` (vases, columns), `extrude_shape()`, `frame()`,
`opening()`/`hollow()` (real window and door holes), `taper`/`bend`/`roughen`, bevels and subdivision, seeded variation
(`rng`, `points_on_sphere`...), construction helpers that get the geometry right (`legs_under()`, `supports()`), and
textured procedural materials (`bark`, `wood`, `leaves`, `stone`, `brick`, `roof tiles`, `plaster`, `glass`...). After a
build Jervis **inspects** how each part was actually made and judges it, then **refines** it:
- *Malformed* (fixed during verification, any quality level): legs not under the seat, parts below the ground, a
  chair that would tip over, a trunk that doesn't reach the ground, a roof off its walls.
- *Too primitive* (one or two improvement rounds): a cylinder-and-sphere "tree", too few parts, razor-sharp boxes,
  flat colours where wood or stone belongs, identical copies, separate things built inside each other, proportions
  that aren't those of the thing asked for. A build far from real-world size (a bench the size of a shoe) is rescaled.
- *Quality level* comes from your words: "simple"/"quick"/"low poly" stays fast; "detailed", "realistic",
  "beautiful", "polished"... gets more parts, more tokens and more refinement.
- *Scenes* ("a park with a bench, two trees and some rocks") are laid out first, then each thing is built and
  inspected on its own. An improvement round that breaks anything is undone, so refining only makes things better.

**Finished assets** (`blender_assets.py`). A local 7B model writing geometry code from scratch produces blockouts:
asked for "a detailed house" it built a box, a door and a roof, and every check passed. So the things people ask for
most are modelled once, properly, and the AI only chooses which one and its options (one quick structured call):
`house()` (styles cottage, brick, modern, farmhouse, cabin; 1-3 floors; foundation, walls with real openings, framed
glazed windows with sills and lintels, a panelled door with a handle and steps, corner boards, a tiled roof with real
thickness and courses, ridge cap, fascia and gutters, chimney with cap and pots, shutters, a porch with railings, a
stone path), `tree()` (oak, pine, palm, birch), `island()` (natural coastline, beach sloping into turquoise
shallows, grassy hills and rocky slopes, shore rocks, the sea, and trees growing on it), `water()`, `rock()`,
`bush()` and `fence()`. Options are kept only when your own words support them (the model once gave a palm tree
"autumn leaves" nobody asked for). Then:
- "make the windows bigger", "give it two floors", "add more trees to the island" rebuild that asset with the option
  changed (and "undo" brings back the very same objects);
- "add a small cabin **on** the island" finds free, level ground on its terrain; "a fence **next to** the house"
  goes just clear of its footprint; on sloping ground a house's foundation reaches down to the ground;
- "make the house white" paints its walls (not its windows), "make the roof green" the roof and its ridge;
- "no, the roof" (after "make it bigger") puts the house back and makes the roof bigger instead; "the door too"
  does the same to the door;
- "... and save it" is always carried out and checked on disk (a new scene gets a new file name in Documents — an
  earlier file is never overwritten).
Things nobody modelled (a castle, a car, a chair) still go to the general planner with the kit, which can also use the
assets as parts. `tests/test_blender_assets_real.py` builds every asset in a real, headless Blender.

**A picture, rebuilt in 3D — then directed in words.** Attach a photo and say "recreate this in Blender" (or "turn
this picture into a 3D scene"):
1. *Seeing* (`vision.py`, `image_analysis.py`, `visual_scene.py`): a local vision model, Qwen2.5-VL 7B (the 3B where
   the GPU is smaller; a text model is never asked to pretend), is asked focused questions — the whole scene, where
   each thing is (boxes), each important thing up close — and its answers are checked against the pixels themselves
   (night is measured, not believed; colours are measured; lit windows are counted). The camera is reconstructed
   (lens, horizon, pitch, height from things of known size) and every grounded thing is projected onto the ground in
   metres. Every value says how it is known — visible, estimated, inferred or unknown — and what the picture can't
   show (the far side of a house) is inferred and said to be.
2. *Meaning* (`semantics.py`): what each thing is (a shop is commercial and lit at night, a palm sways, an ocean rolls
   in waves, a pool only ripples) and data-driven behaviour rules that add only what the scene justifies.
3. *Rebuilding* (`reconstruct.py`): finished assets chosen and configured from what was seen — `villa()`,
   `storefront()`, `room()`, `road()`, `shore()`, `ground()`, `hills()`, `forest()` (`blender_places.py`), furniture,
   lamps, lanterns and parasols (`blender_props.py`), and the existing houses, pools, trees, cars — laid out
   consistently, the camera set up like the photo's, the light and weather matched, everything tagged with its meaning.
   Each step is checked like any other build.
4. *Checking by eye* (`visual_critique.py`): the scene is rendered, compared with the photo (where each thing lands,
   colours, the sky, brightness), the biggest mismatch fixed, rendered again — a fix is kept only if it helps — and the
   biggest difference left is said, not hidden.

Then the scene is edited, never rebuilt (`scene_edit.py`, `blender_world.py`, `scene_state.py`): "add fog", "make the
fog thicker", "put fog near the ground", "make it sunset / night" (sun, sky, exposure, windows, signs and street lamps
together), "add rain" (rain and wet surfaces), "make the ocean calmer", "make the waterfall faster", "make the trees
move more", "stop the animation", "turn on the house lights", "add lights along the path", "make the windows darker",
"make the grass greener", "move the camera closer", "show the house from behind", "give me a low-angle shot", "use a
wider lens", "switch to the other camera", "move the villa back" (what belongs to it moves with it), "make it
cinematic", "make it look more like the photo". Things are found by meaning and position — "the pool", "the left
palm", "that tree", "those chairs". The photo is kept as the reference, but the scene as it is now is what every edit
starts from: "make it sunrise" stays sunrise.

**Adding an app** means writing one adapter (see `agent_blender.py`, and `agent_minecraft.py`, which types chat
commands and reads the game's own log to verify them): how to act, how to read the state, and what each check
means. The planning, verification and repair loop is shared. Then route requests to it in `app.py` (see
`handle_minecraft_command`). The Minecraft adapter has tests with a simulated game but hasn't been run against the real
game yet; it needs cheats on (Open to LAN, "Allow Cheats").

## Programming

"Write a Python program that prints the first 15 prime numbers", then "make it also print their sum", "run it again"
(`agent_code.py`). The code is never assumed to work: the local coding model writes the program (non-interactive,
ending with its own self-checks), Jervis **runs** it in its own folder (*projects* in his data folder) with a time
limit, **inspects** the exit code, any traceback, the self-checks and the expected output, and on a failure gives the
model the real error to **fix** it and runs it again (up to three fixes). He reports only what was verified ("it ran
and its self-checks passed; it printed ...") and shows the code in the window. Code that deletes files, starts
programs or uses the network runs only after you say yes. Python and JavaScript run when installed.

## Listening

- Say the request with the wake phrase in one breath — "Hey Jervis, create a house in Blender" — and it's done
  right away (it used to wake up and drop the request).
- However the name is heard ("hey Gravis", "okay Gervis", "Jarvis"), after a greeting it's Jervis; inside a sentence
  ("customer service", a friend called Travis) it's just a word.
- A sentence cut off by a pause ("put a palm tree next to the..." "...house") is waited on for a few seconds and
  joined, instead of acting on half a command.
- Tests can play WAV recordings to the real listening loop instead of the microphone (`JERVIS_TEST_AUDIO`).

## Phone control

Turned off by default (Settings, Computer control, *"Let your phone control this computer"*).

**Pairing a phone, the first time:** say **"connect my phone"** — Jervis asks, out loud and in the window, *"Want to
connect your phone, so you can talk to me and control this computer from it?"*, and only on "yes" does a QR code show
up on screen ("Scan the QR code on your screen with your phone to connect."). Scan it with your phone's camera (same
Wi-Fi as the computer) and it pairs on its own — no typing. Can't scan it? The address and code are shown as text
too. This is a one-time step per phone, always over your own Wi-Fi — it's also when your phone gets its own
encryption key (see "Away from Wi-Fi" below).

**Connecting an already-paired phone:** say "connect my phone" again and Jervis instead sends a push notification —
*"Jervis wants to connect to this computer"* — with **Confirmed** / **Not Confirmed** buttons right on it. Tap
Confirmed and Jervis says "Your phone is connected"; the phone's page opens to a screen with a press-and-hold mic
button. Hold it, talk, let go — Jervis answers exactly as he would if you'd spoken to him directly, and the reply
shows up on the phone too (read aloud there, using your phone's own voice). The quick-action buttons (open an app,
play a song, pause music, play on YouTube, search Google) still work as before. Say "disconnect my phone", or tap
**Disconnect** on the phone, to end it — it otherwise stays connected until one of you does.

Say "what phones are paired" or "forget my paired phones" to check or undo pairing.

**Notifications:** tap "Enable notifications" on the phone page (works even before pairing) and Jervis reaches your
phone with a real system notification — including every "connect my phone" request — even if the page isn't open.
This uses your phone browser's own push service (the same one every other site's notifications use already), not
any server of Jervis's own. **On iPhone, Safari only delivers these to a page added to the Home Screen** (Share,
*Add to Home Screen*) — a plain Safari tab can't receive push notifications at all; that's an Apple platform rule,
not something Jervis can work around.

If you say "connect my phone" and Jervis can't reach any paired phone (notifications never got turned on), he
tells you exactly where to go — with a relay configured, that's the relay's own stable link (works from anywhere,
never changes with your computer's local IP); without one, your computer's local address. Either way it's a
one-time step: open it, tap "Enable notifications," done.

Prefer a real text message instead, with no page visit ever needed? Fill in the four Twilio fields (Settings,
Optional services) — a free account at twilio.com. Jervis then texts you the "connect my phone" question directly
(for the *first-ever* pairing only; the notification-and-tap flow needs push notifications, since a text can't
carry tappable buttons).

**Away from Wi-Fi:** works out of the box — Jervis ships pointed at a shared relay by default (Settings, Computer
control, advanced, "Relay address"), so an already-paired phone can connect from anywhere, not just this Wi-Fi, with
nothing to set up. The notification-and-tap flow above works exactly the same way whether your phone is next to the
computer or on cellular data across town. Clear that field to keep phone control same-Wi-Fi only, or point it at
your own relay instead (see `relay/README.md`). Either way, everything beyond the first pairing is end-to-end
encrypted with a key only your phone and this computer ever have — a relay only ever moves opaque, encrypted bytes
between them, never anything it can read (see `phone_crypto.py` if you want the details).

*"The phone page couldn't be loaded" (fixed):* the installed engine was built without `phone_client.html`,
`phone_sw.js` and `confirm.html`, so the page every phone (and the Connect window) asks for answered with an error.
They're now packaged, `jervis-backend --selftest` checks every bundled file, and `tests/test_packaging.py` fails if
code reads a file the build doesn't include.

## What works where

| Feature | macOS | Windows |
|---|---|---|
| Voice, wake phrase, timers, notifications, AI answers, window | yes | yes |
| Computer control (mouse and keyboard) | yes (Accessibility permission) | yes |
| Speaking (Hebrew too) | built-in voices | built-in voices; Hebrew: the natural voice above (Windows' Hebrew voice as fallback) |
| Open any app | yes | yes (everything in the Start menu) |
| Websites, Netflix / Stremio / YouTube playback | yes | yes |
| Pause / resume | exact, no toggling | toggles play/pause with the media key |
| Next / previous song or video | yes | yes (media keys) |
| Jump to a minute, restart from the beginning | yes (Chrome) | yes, for a YouTube or Netflix tab that is the *active* tab of its browser window |
| Close a tab, reuse one tab for a site | any tab in Chrome | the active tab of a browser window (Chrome, Edge, Brave, Firefox) |
| Volume up / down / set / mute | yes | exact with `pycaw` |
| Write documents | Word, Pages, TextEdit, Notes, Google Docs | Word, Notepad, Google Docs |
| Edit a document he wrote | yes | Word, Notepad, Google Docs |

### Permissions
- **macOS** asks the first time Jervis uses the microphone and the first time he controls Chrome, Word, Notes,
  Stremio and so on: click Allow. In Chrome, turn on *View > Developer > Allow JavaScript from Apple Events* for
  pause / resume / jump. Computer control, Google Docs and Stremio key presses need *System Settings > Privacy &
  Security > Accessibility*.
- **Windows** needs no special permissions. Word must be installed for Word documents. Because Windows has no
  scripting interface for browsers, Jervis controls them like a person would (finds the window, presses shortcuts), so
  keep the tab you want controlled as the active tab of its window.

## When something goes wrong

If the engine stops by itself, the window says "Jervis's engine keeps stopping" and the details are in the log
(*Settings, Diagnostics*). A crash inside a native library (audio, speech, the AI runtime) used to leave nothing in
the log; now every thread's stack is written to `logs/crash.log` as it happens and copied into `logs/jervis.log` on the
next start, and the window's own log (`logs/window.log`) keeps the last error output of the engine with a readable
exit code. (The crash behind "the engine keeps stopping" since September: two threads starting the audio system at the
same moment — the Settings device list and the microphone — crash PortAudio. All audio-system use now goes through one
lock, `microphones.py`.)

## Run from source, test, build

For development. You need Python 3.12 (3.11–3.14 work on macOS; on Windows PyAudio has wheels up to 3.12) and
Node.js 20. On macOS, `brew install portaudio` first.

```
python3 run.py                 # makes venv/, installs requirements.txt and the window, starts Jervis
venv/bin/python -m pytest -q   # the tests (no microphone, network or real apps needed)
```

When running from source, Jervis keeps his files in this folder, and a `.env` file here is imported into Settings the
first time. `python3 run.py --local-images` adds local picture generation (PyTorch + Diffusers, several GB).

Installers are built by GitHub Actions (`.github/workflows/build.yml`) on real Windows and macOS machines: tests, then
the engine (`jervis-backend.spec`, PyInstaller) and its `--selftest`, then the installer (electron-builder, config in
`package.json`), then a fresh install test (`tests/installer/`): install, start, quit, check nothing is left running,
uninstall. Pushing a tag like `v1.0.1` publishes a release. To build locally:

```
pip install -r requirements.txt pyinstaller && npm run backend   # the engine, into backend-dist/
npm ci && npm run dist                                           # the installer for this system, into release/
```

## Google accounts: school vs personal

If you have two Google accounts in Chrome (each in its own Chrome profile), name them in Settings, Optional services
(or in `.env` when running from source):

    GOOGLE_ACCOUNT_LEARNING=school account
    GOOGLE_ACCOUNT_PERSONAL=personal account

Jervis then opens everything in the right profile, silently: learning things (school documents, Drive, Classroom, lectures and
tutorials, learning sites) under the learning account, and everything else (Gmail, trailers, Netflix, fun documents) under the
personal one. He decides from what you say ("for school" or "personal" settles it) and each decision is written to
`logs/routing.log`. If one lands in the wrong account, say "wrong account" or "open it in my school account".

## Closing tabs

"Close the YouTube tab", "close the Gmail tab", "close the Breaking Bad tab" (any word in a tab's title), "close all the Netflix tabs",
"close this tab". "Close the other tabs" and "close all tabs" ask you to say yes first.

## Solving equations

"Solve 2x + 4 = 24", "x in: 3x^2 + 6x + 4", "what are the roots of x squared minus 9", "find x when 3x + 1 = 10". Linear and quadratic equations are
solved by Jervis himself (exact fractions and roots, complex answers when there are no real ones), as a worksheet with the steps, instead of
trusting the AI's arithmetic. Other equations still go to the AI.

## Full screen

When you wake Jervis ("Hey Jervis") his window opens full screen. Press F to switch full screen on and off, Esc to leave it.

## Graphs

Give Jervis any function of x, spoken or typed: "graph 2x squared plus 4x plus 6", "plot sine of x over x", "graph e to the minus x squared",
"graph the absolute value of x minus 2", "graph 1 over x squared minus 1", "graph the natural log of x", "graph tan x", "plot y = sqrt(4 - x^2)".
Polynomials, powers, roots, trigonometric and inverse trig, exponentials, logarithms, absolute value, fractions and combinations of them work
(y equals something with x; circles and other curves that are not a function of x do not). Use brackets when the wording is ambiguous, e.g.
"x over (x squared plus 1)"; the title above the graph always shows how Jervis read it.

A window opens and draws the curve with a glow, on a grid that fits the function, with the x-intercepts, the highs and lows, the y-intercept and
the asymptotes marked (parabolas also get their vertex and axis of symmetry). Move the mouse over it to read any point. **Save image** stores a PNG,
Esc or "close the graph" closes it. Every graph stays: each one is also a small clickable picture in the conversation, ‹ › (or the arrow keys) step between them, G shows or hides the last one, and "show the graph again", "the previous graph", "the next graph" work by voice, as often as you like (kept until you restart Jervis). Only what is on screen is analysed: the window shows the interesting part of the graph, not all of it.

## Weather

"What's the weather?", "how's the weather in Paris?", "show me the forecast" open the weather window: now (feels-like,
high/low, humidity, wind, visibility, UV), a map of the area with the rain radar, the next 24 hours and 7 days. Click the
weather card on the left to open it too; Esc or "close the weather" closes it. The city is the one in Settings, General,
Weather city; without one, the area of your internet connection.

Everything it uses is free, with no account, no key and no paid plan that could ever start charging:

| What | Service | Terms |
|---|---|---|
| Forecast | [Open-Meteo](https://open-meteo.com) | Free for non-commercial use (personal use is), up to 10,000 calls a day; CC BY 4.0 (credited in the window) |
| Backup forecast | [MET Norway](https://api.met.no) | Free, commercial use allowed; CC BY 4.0. Used automatically when Open-Meteo doesn't answer |
| Map | [OpenFreeMap](https://openfreemap.org), OpenStreetMap data | Free, no limits, commercial use allowed; credited on the map |
| Terrain shading | Mapzen terrain tiles (AWS Open Data) | Free public dataset; credited on the map |
| Rain radar | [RainViewer](https://www.rainviewer.com/api.html) | Free for personal and educational use; optional (the window works without it) |
| Place names → map position | Open-Meteo geocoding, then OpenStreetMap Nominatim as a backup | Free; Nominatim asks for light use (one lookup per place) |
| Location without a city | [GeoJS](https://www.geojs.io) | Free, no key |
| Drawing the map | [MapLibre GL](https://maplibre.org) 5.24 (bundled in vendor/maplibre) | BSD licence |

If Jervis were ever sold or made part of a paid product, Open-Meteo (non-commercial) and RainViewer (personal use)
would need replacing; MET Norway and OpenFreeMap already allow that.

## Distance on a 3D globe

"What is the distance between New York and Tel Aviv?", "how far is Paris from Tokyo", "show me the distance between Rome and
Berlin on the globe". Jervis looks up both places (a free geocoding service, no key needed), works out the straight-line
(great-circle) distance, and opens a spinning 3D globe — real, richly coloured Earth imagery (bundled, works offline)
with drifting clouds, a day/night terminator and an atmosphere glow, not a wireframe — with a glowing arc between them. Drag to rotate it yourself, scroll to
zoom, **Save image** stores a PNG. Every globe stays, exactly like the graphs: click its picture in the chat, use ‹ › or the
arrow keys, press **E** to show or hide the last one, or say "show the globe again", "the previous one", "the next one".
Esc or "close the globe" closes it.

## Opening an app and being asked what to do

"Open Spotify" asks what to listen to; "open Google" asks what to search; "open Netflix" or "open Stremio" asks "What do
you want to watch today?"; "open your calendar" asks whether to hear what's next or make a new event. Say the answer next
(a song, a search, a show or movie) and he acts on it right away, no need to repeat the app's name. "Never mind" cancels.
Naming what you want in the same breath ("open Netflix and play the office") skips the question, exactly like before.

## Google Calendar

Setup once: get a free Desktop app OAuth client from Google Cloud Console (with the Calendar API turned on) and paste
its client ID and secret into Settings, Optional services (turn on *Show advanced settings*); `.env.example` has the
exact steps. The very first time you use it, a browser tab opens once for you to sign in; after that Jervis remembers
it in a local file, `.calendar_token.json`, in his data folder, never shared.

"Open my calendar" (or "check my calendar", "create a calendar event" on their own) then asks: hear the next events, or
make a new one?
- **Hear the next events:** he reads out your next 5 events — title, day, time, and location if there is one — straight
  from your real Google Calendar.
- **Make a new event:** he asks for the title, then the date ("tomorrow", "next Friday", "October 3rd"), then the time
  ("3pm", "15:30"), then how long ("30 minutes", "an hour and a half", "all day", or "default" for one hour), and creates
  it for real. "Never mind" cancels at any point; a wrong date or time is asked again rather than guessed.

## Writing without saying what, up front

"Open a document on Google Drive", "open a blank Word document" (no content yet): Jervis opens it and asks "What would
you like to write?" Say what you want, and he writes it in there. "Never mind" cancels. Saying the content up front
("open a document and write a poem about the sea") still works in one go, without the extra question.

## Planets

"Tell me about Mars", "show me Saturn", "what is Neptune like", "tell me about the Sun" or "the Moon". Jervis tells you the
key facts (size, day and year length, distance from the Sun, moons, temperature) and opens a real, lit, spinning 3D model
next to a starfield — the same look as the Earth-distance globe, textures bundled so it works offline, with real rings on
Saturn. Every model stays, exactly like the graphs and the globe: click its picture in the chat, ‹ › or the arrow keys, P
shows or hides the last one, or say "show the planet again", "the previous one", "the next one". Esc or "close the planet"
closes it. Works for all eight planets, the Sun, the Moon and Pluto; anything else gets a plain, softly lit sphere instead
of a picture, since no texture is bundled for it.

Drag to rotate; scroll to zoom, including in close on a spot to look at it more closely (the underlying photo only
has so much detail, so very close zooms look soft rather than blocky). While you're dragging or scrolling, the view stays
responsive first and sharpens back up automatically the moment you let go.

## Math answers

Calculations come back as a worksheet: a one-line spoken answer, then the Problem, numbered Steps (one formula each, typeset like a
textbook with fractions, roots and powers) and a highlighted Answer box. Formulas are typeset by KaTeX (bundled in `vendor/katex`, works offline).

## Typing to Jervis

Under the orb there is a box: type anything, words or numbers, and press Enter. It works exactly like saying it, so it also works
while the microphone is muted or Jervis is asleep, and if he is talking he stops to answer. Press `/` to jump to the box, the up and
down arrows bring back what you typed before, and Escape leaves the box (the M and Space shortcuts are off while you type).

## Voice-reactive core

The 3D core in the window spins faster, pulses and glows with how loud you speak. The window only measures the loudness of the
microphone (nothing is recorded or sent anywhere), and it stops when you mute. The first time, macOS asks to let the window
use the microphone: allow it. If you say no, everything else still works and the core just moves on its own.

## Google Classroom

"Check Google Classroom for work I didn't submit" (or "do I have missing homework?"). Jervis opens Classroom in your school
account, shows it, and tells you which assignments are missing (overdue) and which are still to turn in. He reads the page in
Chrome, so turn on Chrome's **View > Developer > Allow JavaScript from Apple Events** once, in the school profile's window.
Without it he still opens Classroom and tells you how to turn it on. Reading works on macOS; on Windows he only opens the page.
What he read is saved in `logs/classroom_last.json`.

## WhatsApp (macOS)

"Do I have unread WhatsApp messages?", then "read them", or "what did Dana write me?" / "read my messages from Mom".
Jervis reads WhatsApp Desktop's local chat data on your Mac, read-only: he cannot send, reply or mark anything as read.
Message text is only spoken and shown in the window. It is never sent to the online AI, never added to his memory, and never
written to the transcript files. If macOS blocks access, allow the app that runs Jervis in System Settings > Privacy & Security >
Full Disk Access. Turn it off in Settings, Privacy. WhatsApp only updates its data while it is open, so Jervis
says so when what he reads may be old.

## Images

Attach a picture (click the paperclip under the orb, drag a file onto the window, or paste one from the clipboard) and ask
about it, or just say what you want — a spoken command alone works too if you attach the image first. Every picture stays
part of the conversation, so a follow-up like "what's wrong with it?" or "what should I do about it?" still refers to the
last one you shared, exactly like the graphs and globes already do for equations and places.

**Understanding a picture** (works out of the box — no extra key, same `GROQ_API_KEY` as the rest of Jervis):
- "What's in this picture?", "describe this image", "look at this screenshot" — a plain description.
- "What does this error mean?", "what's wrong with this screenshot, and how do I fix it?" — Jervis looks at it *and*
  reasons about what you asked, not just a caption.
- "Read the text in this image", "what does this screenshot say", "extract the text" — OCR.
- "Compare these two images", "what changed between these screenshots?" — once at least two pictures have been shared.

**Creating a picture** works out of the box, free, no key or setup — "generate an image of a futuristic cyberpunk
city at night", "draw me a picture of a golden retriever puppy". It uses [Pollinations.ai](https://pollinations.ai),
a free, keyless image service, so there is nothing to configure. Pollinations adds a small watermark and shares its
free tier between everyone using it (roughly one request every 15 seconds); a free account at
<https://auth.pollinations.ai> removes the watermark and raises that limit, but nothing requires it.

For higher quality, and for **editing** an existing picture (Pollinations only creates new ones, it can't modify one
you show it), paste an OpenAI key into Settings, Optional services
(create one at <https://platform.openai.com> — "API keys" in your account, and add a small amount of billing credit
there too, since image generation isn't covered by any free OpenAI tier; `OPENAI_IMAGE_MODEL` in `.env.example` lets
you pick a different model). When it's set, Jervis prefers it for generating; if it ever fails (no credits, a bad
key, a service hiccup), generation quietly falls back to the free Pollinations service instead of giving up — and
says so, so it's never a silent switch. Editing always needs the OpenAI key; without it Jervis says so plainly
instead of pretending to edit something.

**Generating unlimited pictures for free, on this computer**, needs no key or account either, but is a bigger
install (a few GB) and needs real free memory to run well:

    python3 run.py --local-images

That installs PyTorch and Diffusers (see `requirements-local-images.txt`) and, the first time you ask Jervis to draw
something afterward, downloads the model itself (a few GB more, once). When it's set up, Jervis prefers it over
OpenAI and Pollinations — it's genuinely unlimited and never leaves this computer. **This needs real free memory to
run well** (16 GB total RAM is the comfortable floor; 8 GB machines can work but may be slow or, if the system is
already low on free memory, time out and fall back to the free cloud service instead — Jervis gives up after about
2 minutes rather than hang forever, so a bad fit here never blocks anything, it just quietly uses Pollinations that
time; tested on an actual 8 GB machine under memory pressure, that recovery took under 2.5 minutes worst case). Only
worth setting up if this computer has memory to spare; otherwise the free cloud service is the better fit. Unlike
OpenAI, the local model has no content filter — it's running only on this computer, for you, so that's your call.
- "Remove the person in the background", "change the sky to a sunset", "make this black and white", "turn this into
  a cartoon style" — edits the most recent picture; the original file is never overwritten, the edited result is a
  new picture, shown and saved separately.
- "Open this image", "save this image" — opens the most recent picture in your normal photo viewer, or copies it to
  your Desktop (or Downloads).

Pictures you attach, and everything Jervis makes or edits, are saved under `images/` (`uploads/`, `generated/`,
`edited/`) — nothing is uploaded anywhere without you asking Jervis to look at, generate, or edit it. A picture over
20 MB, or one that isn't really an image (corrupted, wrong format), is rejected with a clear reason rather than
crashing anything; PNG, JPEG, WEBP, GIF and BMP are all supported.

**A known rough edge:** reading text out of a busy or high-contrast screenshot occasionally repeats part of the
transcription (a quirk of the current vision model, not something Jervis's own code introduces) — the text itself is
still accurate, just sometimes said twice. Ask again if it happens.
