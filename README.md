# Jervis

A voice assistant for your computer: say "Hey Jervis", then ask for music, videos, shows, timers, documents and more,
or have him use the mouse and keyboard for you. His AI runs on your own computer: no account and no API key.
Runs on **Windows 10/11** and **macOS** (Apple silicon). Made by Ariel & Shalev.

## Install

Download the installer from <https://arielzaha.github.io/jervis/> (or the
[latest release](https://github.com/ArielZaha/jervis-app/releases/latest)):

- **Windows:** run `Jervis Setup.exe`. If SmartScreen says "Windows protected your PC", click *More info*, then
  *Run anyway* (the installer isn't signed with a paid certificate yet). No administrator rights needed; Jervis is
  added to the Start menu and the desktop.
- **macOS:** open the `.dmg`, drag Jervis to Applications, open it. The first time, macOS says it can't check it for
  malware: open *System Settings > Privacy & Security* and click *Open Anyway*.

On the first start Jervis downloads his AI engine ([Ollama](https://ollama.com)), the `llama3.2` model and an offline
speech model (about 3.5 GB on Windows, 2.5 GB on a Mac), with the progress in his window. Everything that doesn't need
the AI works meanwhile. If you already run Ollama, he uses yours. Then say **"Hey Jervis"**.

Everything else is in **Settings** (the gear at the top right): microphone, voice, the wake phrase, which AI answers,
computer control, the weather city, privacy, optional services, and starting when you sign in. Settings, logs,
transcripts and pictures live in `%APPDATA%\Jervis` (Windows) or `~/Library/Application Support/Jervis` (macOS).

## Which AI answers

- **By default, the AI on your computer:** `llama3.2` through Ollama for answers and Whisper (`base.en`, via
  faster-whisper) for speech. After the first start both work offline. On computers with 16 GB of memory he also
  installs `qwen2.5vl:3b`, so he can look at pictures and the screen (Settings, AI can turn it on or off).
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
- **Privacy:** screenshots are only looked at by the local vision model and never leave the computer. With a Groq key,
  the list of buttons and fields in the window goes to Groq along with the request.

On macOS, turn on Jervis in *System Settings > Privacy & Security > Accessibility*; macOS asks the first time.

## What works where

| Feature | macOS | Windows |
|---|---|---|
| Voice, wake phrase, timers, notifications, AI answers, window | yes | yes |
| Computer control (mouse and keyboard) | yes (Accessibility permission) | yes |
| Speaking (Hebrew too) | built-in voices | built-in voices (add the Hebrew voice in Windows Settings > Time & language > Speech) |
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
