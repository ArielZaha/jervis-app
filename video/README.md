# Jarvis — product films

Three films are made from this folder. Nothing here changes the Jarvis app.

| | |
|---|---|
| **`out/Jarvis_Trailer_Final.mp4`** | **The trailer: 1 min 9 s** (68.6 s), cinematic, five acts, carried by a narrator. (`out/Jervis_Trailer_Final.mp4` is the same file under the older spelling.) Subtitles: `out/Jarvis_Trailer_Final.srt`; script: `trailer_script.md`. |
| **`out/Jarvis_Showcase_Final.mp4`** | **The showcase: 1 min 30 s**, fast, built from six real takes in which Jarvis is asked something out loud (or from the phone) and does several things. Jarvis's own voice answers. Subtitles: `out/Jarvis_Showcase_Final.srt`; script: `showcase_script.md`. |
| `out/Jarvis_Product_Demo.mp4` | The first film: 2 min 39 s, one feature after another, music and titles only. |

Both are 1920×1080, 30 fps, H.264 + AAC, each with a 960×540 `_preview` copy next to it.

## The trailer in one look

| Act | | |
|---|---|---|
| 1. Mystery | 0:00–0:10 | The orb asleep, very close, in the dark. *"What if your computer could do more than wait for your next click?"* Three flashes of what is coming. |
| 2. Awakening | 0:10–0:20 | The real window asleep; "Hey Jarvis"; it wakes and greets in its own voice. *"Meet Jarvis."* |
| 3. Power | 0:20–0:44 | One sentence sets a timer and opens the weather; an equation solved and drawn; two functions; the flight Tokyo → New York; sunrise; Saturn. |
| 4. Escalation | 0:44–1:00 | The permission question and the control bar; the phone driving the computer; eight features in four seconds. |
| 5. Reveal | 1:00–1:08 | *"Your computer. Your commands. Your Jarvis."* The name, and one line: YOUR COMPUTER. YOUR COMMAND. |

`film/trailer.js` is the edit; `audio/trailer_narration.json` is the narration. Build with `video/build.sh trailer`
(about 12 minutes). Its own takes are `awaken` (asleep, then called by name) and `orbsleep` (the orb alone, asleep);
the rest it shares with the showcase.

### The narrator

The narration is spoken by `audio/narrator.py`, which uses, in this order:

1. **Google AI Studio (Gemini text-to-speech)** when a key is available as `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the
   environment or in the project's `.env`. There was no such key on this computer when the trailer was made, so this
   path is written but **has never been run**. With a key: `video/build.sh trailer voice` speaks every line again with
   Gemini (voice `GEMINI_VOICE`, default Charon; model `GEMINI_TTS_MODEL`), re-times the edit to the new lines and renders.
2. Otherwise **Kokoro** (open source, Apache 2.0), a neural voice that runs on this computer: voice `am_onyx`,
   slowed and lowered a little. This is the voice in the delivered trailer. Its files are not in git:
   `venv/bin/python -m pip install --target video/tools.nosync/tts kokoro-onnx`, and `kokoro-v1.0.onnx` and
   `voices-v1.0.bin` from <https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0> into
   `video/tools.nosync/kokoro/`.

To change a line, edit `audio/trailer_narration.json` and run `video/build.sh trailer voice`. To try another Kokoro
voice: `venv/bin/python video/audio/narrator.py --voices bm_lewis am_michael` (prints each voice's pitch; the samples
land in `cache.nosync/`), then set `kokoro_voice` in the JSON. `narrator.py --check` transcribes every line back.

## The showcase in one look

1. **"Hey Jarvis"** — one spoken sentence sets a timer *and* opens the weather for Paris. Then the title.
2. **A spoken thread of mathematics** — an equation solved and drawn; a second function laid over it.
3. **The Earth, a sunrise, a planet** — the flight from Tokyo to New York, dawn over Tokyo, Saturn: three questions in a row.
4. **Phone and computer, filmed together** — what is typed on the phone opens on the computer; then the phone answers alone.
5. **Computer control** — the permission question, then the real control bar: looking, deciding, paused, stopped.
6. **Everything else**, one beat each — music, trailers, documents, pictures, vision, calendar, steps, Android, local AI, pairing.
7. **Close.**

`film/showcase.js` is the edit. Build it with `video/build.sh showcase` (about 8 minutes), or `video/build.sh showcase sound`
to redo only the sound. Its takes: `wake mind world link` (new for the showcase; `link` films the phone and the
computer's window in step), plus `control controlbar talk docs picture plan solve android settings pairing orb`.

## How it is made

1. **Footage is the real app.** `capture/record.js` opens Jarvis's actual window page (`index.html`), the actual
   phone app (`phone_client.html`, served by the real relay) and the actual control bar (`control.html`) off screen
   and films them. A hand-driven clock (`capture/clock.js`) replaces the page's sense of time, so each clip is an
   exact 30 frames a second however slow the computer is. Each shot is a short script in `capture/shots/`.
2. **The engine behind the footage is the real one**, made safe to film (`capture/backend.py`): it is `app.py`
   itself, so every reply on screen is what Jarvis really answers — but *acting on the computer* is recorded
   instead of done (see "What is staged" below).
3. **The film** is a web page (`film/`): `core.js` is a small engine in which everything on screen is a function of
   time, `scenes.js` is the film scene by scene. `render.js` photographs it one frame at a time.
4. **The soundtrack** is original and generated by `audio/score.py` (music and sound effects, from the film's own
   timeline, `audio/cues.json`). Nothing is licensed or borrowed.

## Make it again

```
video/build.sh trailer          # the trailer: narration + soundtrack + picture + final mix   (about 12 minutes)
video/build.sh trailer sound    # only its soundtrack and mix, picture unchanged
video/build.sh trailer voice    # speak the narration again, re-time, render
video/build.sh showcase         # the showcase: soundtrack + picture + final mix   (about 15 minutes)
video/build.sh showcase sound   # only its soundtrack and mix, picture unchanged   (seconds)
video/build.sh                  # the first film                                   (about 13 minutes)
video/build.sh sound            # the first film: only the soundtrack and the mix
video/build.sh voice            # the first film: speak the narration first, then mix (see narration.md)
```

Re-record footage (each shot starts its own throwaway Jarvis, with an empty conversation and no personal data):

```
video/capture/record.sh graph            # one shot
video/capture/record.sh awaken orbsleep                                # the trailer's own takes (about 4 minutes)
video/capture/record.sh wake mind world link                           # the showcase's own takes (about 10 minutes)
video/capture/record.sh talk control docs graph graph2 solve globe saturn mars weather plan picture question \
                        settings pairing phone android orb controlbar      # the rest (about 25 minutes)
```

Useful while editing: `FILM=showcase video/stills.sh 12 36.5 80` renders those moments of the showcase into one picture
(`cache.nosync/review.jpg`; without `FILM=showcase`, of the first film); `video/sheet.sh assets/footage/globe.mp4` makes a contact sheet of a clip;
`electron video/render.js --from 60 --to 80` renders part of the film.

Needs: macOS with a 2× display (frames are captured at the display's density), the project's `venv` and
`node_modules`, and ffmpeg. A copy of ffmpeg lives in `tools.nosync/` (not in git); to get it back:
`venv/bin/python -m pip install --target video/tools.nosync/py imageio-ffmpeg`. An `ffmpeg` on the PATH works too.

## What is where

| | |
|---|---|
| `capture/` | recorder, the hand-driven clock, the film-safe engine, and one script per shot in `shots/` |
| `assets/footage/` | the recorded clips (`.mp4`) and their marks (`.json`: frame numbers the edit cuts on) |
| `assets/images/` | two pictures Jarvis generated, used as the attached picture in one shot |
| `assets/narration/` | the trailer's narrator, one file a line |
| `assets/voice/` | Jarvis's spoken replies from the takes (the Mac's own `say` voice, which is the voice the app uses here) |
| `assets/audio/` | the generated music and effects for the first film; `assets/audio/showcase/` for the showcase (with `jarvis.wav`, his lines on the timeline) |
| `film/` | `core.js` (engine and building blocks), `trailer.js`, `showcase.js`, `scenes.js` (the three edits), `film.css` (the look) |
| `audio/` | `score.py` (music, effects, voices on the timeline), `narrator.py` and `trailer_narration.json` (the trailer's narrator), `subtitles.py`, the timelines `cues*.json`; for the first film's optional narrator: `narration.json`, `tts.py`, `voice.py` |
| `out/` | the finished film and its preview |
| `cache.nosync/`, `tools.nosync/` | scratch space; ffmpeg and the Kokoro voice (not in git; see above to get them back) |

## What is real, and what is staged

Real: every window, panel, graph, globe, planet, weather screen, timer, chat message and phone screen is the app
itself, filmed. Every reply is produced by Jarvis's own code. The weather, the place lookups, the generated picture
(free Pollinations service), the picture description and the general answer came from the real services while
filming. The phone was paired through the real one-time pairing link and talks to the engine through the real relay
(run locally).

Staged, so that filming never touches the computer or anyone's accounts:

- **Spotify, the browser, Calendar and app launching are stand-ins.** Jarvis sends the same commands he always
  does; they are recorded instead of carried out, and the stand-in answers as the real program does when it works
  ("the song started", "the document took the text"). That is why the film shows Jarvis's side of music, trailers,
  documents and the calendar, and never footage of Spotify, YouTube, Netflix, Google Docs or Calendar.
- **Computer control never really starts.** The request, the question on screen and the click on Allow are real;
  the task is then held back. The control bar is the real `control.html`, shown the states the engine reports
  (looking, deciding, paused, stopped) over a plain background.
- **The person's voice is staged; Jarvis's is real.** What is "said" to Jarvis is handed to the engine through the
  door the microphone's text goes through (worded as speech-to-text words it), and the orb is fed a voice-shaped level;
  no human voice is recorded, so requests appear as words on screen. What Jarvis says back is his real reply, spoken
  by the voice the app really uses on this Mac, and cut short where the film moves on.
- **The story in the documents scene** is the text Jarvis really wrote in that take, set as a plain page by the
  film (it is not a picture of Google Docs).
- **The phone frames** are drawn by the film; the screens inside them are the real phone app in an iPhone-sized
  and an Android-sized window. It has not been filmed on a physical phone.
- **The Settings shot** runs with the local AI chosen, so that choice is the one on screen.

Not in the film because it could not be shown honestly here: real playback in Spotify/YouTube/Netflix/Stremio,
a real Google Doc, Jarvis actually driving Chrome, and Windows (everything was filmed on macOS).

- **In the showcase, waiting is cut out.** Each sequence is one real take; the edit removes the listening and
  thinking time between a question and its answer, and shows the flight across the globe as a time-lapse.

## Changing the film

- **Words on screen** are in `film/showcase.js` / `film/scenes.js` (search for `Caption(`, `spoken(`, `word:` and `label:`).
- **Timing**: each scene is `scene(name, bars, …)`; a bar is 2.4 s. Change the number of bars and run
  `video/build.sh` — the music follows the new length by itself.
- **A different request in a shot**: edit the sentence in `capture/shots/<shot>.js`, record it again, build.
