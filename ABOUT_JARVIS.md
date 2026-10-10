# Jarvis

Jarvis is a personal AI assistant that lives on your computer and on your phone. You talk to him (or type), and he
does things: plays music and shows, opens apps, answers questions, draws graphs, shows the Earth and the planets in
3D, writes documents, adds calendar events, sets timers, makes pictures, and can even use your mouse and keyboard
for you.

He was made by Ariel and Shalev. He runs on **macOS** and **Windows 10/11**, with a phone app for **iPhone and
Android**.

This document describes everything Jarvis does today.

---

## 1. How you talk to him

| Way | How it works |
|---|---|
| **Voice** | Say **"Hey Jarvis"** (also "Wake up Jarvis" or "Hello Jarvis"). His window opens and he listens. Then just speak. |
| **Typing** | A box under the glowing orb. Type anything and press Enter. It works exactly like saying it, even when the microphone is muted. |
| **Your phone** | A chat app on your phone that talks to the same Jarvis (see section 5). |
| **Pictures** | Attach, drag in or paste a picture, then ask about it. |

Ways to stop or pause him:

- Say **"Goodbye"** (or "good night", "see you later") and he goes to sleep until you say "Hey Jarvis" again.
- Press **M** to mute the microphone. While muted he hears nothing; typing still works.
- Press **Space** or the stop button to cut him off while he's speaking.
- Closing his window puts him to sleep. Minimizing it does not.

He answers out loud and in writing. Everything said is kept as a conversation on the right side of his window.

---

## 2. His window

- **The orb** in the middle: a 3D core that reacts to how loudly you speak, and changes color with what he's doing
  (listening, thinking, speaking, sleeping, muted).
- **Conversation** on the right: everything you and Jarvis said, with small clickable pictures of every graph,
  globe and planet he showed.
- **System** panel: your computer's processor, memory and battery.
- **Weather** card: the current weather; click it for the full forecast.
- **Timers** card: appears when a timer is running.
- **Try saying**: example requests sorted by kind (Watch, Learn, Do, More). Click one to put it in the message box.
- **Settings** (the gear): everything you can change (section 9).
- **Phone** button: shows whether a phone is connected.

---

## 3. Everything he can do

### Music

- **Play a song:** "Play Bohemian Rhapsody", "play Five Years by David Bowie", "play Creep on Spotify".
- **Play your own playlists, albums and liked songs:** "play my Workout playlist", "play "My favorite songs" playlist
  on Spotify", "shuffle my liked songs", "play the album OK Computer by Radiohead", "play songs by Adele".
- **Spotify's personal mixes by their everyday names:** "play the repeat playlist" (On Repeat), "play my discover
  weekly", "daily mix 3".
- **Any playlist of a kind:** "play a lofi playlist".
- **Other services:** Apple Music, YouTube, YouTube Music, SoundCloud, Deezer, Tidal, Amazon Music ("play OK Computer
  on Apple Music").
- **Another song by the same artist:** "play another song of Radiohead", "something else by them".

Jarvis always prefers *your own* playlist over a stranger's playlist with the same name.

### Video and shows

- **YouTube:** "Play Echoes on YouTube", "play a video about black holes". Opens and plays in one tab.
- **Netflix:** "Play The Office on Netflix", "play Breaking Bad season 3 episode 2 on Netflix" (that exact episode).
- **Stremio:** "Episode 3, season 1, Breaking Bad", "open Stremio and play Inception".
- **Trailers:** "Show me the trailer of Wednesday". They play on YouTube by default; "on Netflix" plays Netflix's own
  trailer. After a YouTube trailer, Jarvis tells you if the show is on Netflix too, and "show it on Netflix" switches.
- **Recommendations:** ask what to watch, then "show me the trailer of the second one".

### Controlling what's playing

- "Pause", "stop the song", "resume", "next song", "previous song", "skip".
- **Jump to a time:** "go to minute 3", "play from minute 3", "play the third minute", "skip to 2:30", "start it at 1:20".
- "Start it from the beginning".
- **Volume:** "volume up", "volume down", "set the volume to 40", "mute".

### Apps, websites and browser tabs

- **Open any installed app** by name, even if said imperfectly: "open Spotify", "open VS Code".
- **Open websites:** "open Gmail", "open Google Drive", "open YouTube".
- **Open and ask:** "Open Spotify" asks what to listen to; "open Netflix" asks what to watch; "open Google" asks what
  to search. Or say it all at once: "open Netflix and play The Office".
- **Close things:** "close Spotify", "close the YouTube tab", "close the Breaking Bad tab" (any word in a tab's
  title), "close all the Netflix tabs". "Close all tabs" asks you to confirm first.
- **Web search:** "search Google for cats", "search YouTube for Minecraft".
- **Two Google accounts:** if you have a school account and a personal one, Jarvis opens school things in the school
  account and everything else in the personal one. "Wrong account" moves it.

### Timers and reminders

- "Set a timer for 10 minutes", "set a 30 second timer for the eggs".
- "Remind me in an hour to call Mom".
- "How much time is left?", "cancel the timer".
- When a timer ends, Jarvis's window comes to the front and he says so, even if he was asleep. Timers survive a
  restart.

### Calendar

- **One sentence is enough:** "add a dentist appointment tomorrow at 5pm", "schedule a meeting with Noa on Sunday
  from 2pm to 3:30pm", "put Dana's birthday in my calendar on October 12 all day".
- He works out the title, date, time and length himself, and asks only for what's missing.
- **Reminders:** he asks "Do you want a reminder?" You can answer "10 minutes", "1 hour and 1 day", "at the time" or
  "no", or say it up front: "…with a reminder 1 hour before".
- **Where events go:** Apple Calendar (the Calendar app on a Mac) or Google Calendar. You choose in Settings.
- "Check my calendar" reads your next events.

### Documents

- "Write a short story in Google Docs", "write a poem about the sea in Word", "write a shopping list in Notes".
- He writes the text and puts it into a new document in **Google Docs, Word, Pages, TextEdit / Notepad or Notes**.
- "Open a new Google Doc" asks what to write; then "write a short story" writes one into that document.
- Afterwards: "make it shorter", "read it to me", "put this list in a document".

### Math

- **Equations, solved step by step:** "solve 2x + 4 = 24", "what are the roots of x squared minus 9". Linear and
  quadratic equations are solved by Jarvis himself, exactly, as a worksheet: the problem, numbered steps, and the
  answer in a box.
- **Graphs of any function of x:** "graph sine of x over x", "plot y = x^2 - 4", "graph tan x". A window draws the
  curve with its roots, highs and lows, intercepts and asymptotes marked. Move over it to read any point.
- **Both at once:** "what is 2x + 6 = 0, draw the graph" gives the worked answer and the graph.
- Follow-ups work: "show the steps", "what's the vertex?", "draw the function".

### The Earth, in 3D

A real globe built from NASA imagery, lit by the Sun where it actually is right now, with city lights on the night
side.

- **Distance:** "What is the distance between Tokyo and New York?" Jarvis finds both places, calculates the true
  shortest (great-circle) distance, and **flies the route**: the camera goes from the whole Earth to the departure,
  follows a small airplane along the real path, and lands at the destination. Pause, Replay and Skip buttons; drag to
  look around; scroll to zoom.
- **Flight time:** "how long is the flight from Tel Aviv to New York?" This is always labeled an *estimate*, separate
  from the straight-line distance.
- **Countries on the way:** "which countries does it fly over?" The answer comes from real border data.
- **Comparisons:** "which is farther from Tel Aviv, London or New York?" Both routes are drawn in different colors,
  with planes flying at the same speed.
- **Nearby places:** "cities within 100 km of Haifa", "what cities are near Paris".
- **Day and night:** "show me Earth at night", "where is it daytime right now?", "show sunrise over Tokyo", "is it
  night in Sydney?" Sunrise and sunset times are calculated astronomically.
- **Ambiguous names:** if a name could fairly mean two big places (Valencia in Spain or Venezuela), he asks which.
  If he can't find a place, he says so; he never invents one.

### Planets

- "Tell me about Saturn", "show me Mars", "tell me about the Sun", "the Moon".
- He gives the key facts (size, day and year length, distance from the Sun, moons, temperature) and opens a spinning,
  lit **3D model**: all eight planets, the Sun, the Moon and Pluto, with real rings on Saturn.

### Weather

- "What's the weather?", "how's the weather in Paris?", "show me the forecast".
- A weather window: now (feels-like, high and low, humidity, wind, UV), a map with rain radar, the next 24 hours and
  7 days. No account or key needed.

### Pictures

- **Understand a picture:** attach one and ask "what's in this picture?", "what does this error mean?", "read the
  text in this image", "compare these two images".
- **Make a picture:** "generate an image of a dog in space", "draw me a dragon". Jarvis first expands a short request
  into a detailed description, which makes a big difference to the result.
- **Edit a picture:** "remove the person in the background", "make this black and white". This needs an OpenAI key.
- "Open this image", "save this image".

### School and messages

- **Google Classroom:** "Check Google Classroom for work I didn't submit". He opens Classroom in your school account
  and tells you which assignments are missing and which are still due.
- **WhatsApp (Mac):** "Do I have unread WhatsApp messages?", then "read them" or "what did Dana write?" This is
  read-only: he cannot send, reply or mark anything as read.

### Using your computer for you

- Ask for something on screen: "click Save", "scroll down", "type hello into the search box", "use my computer to
  turn on dark mode in Chrome".
- He works like a person: looks at the window, picks one action, does it, checks what changed, and continues.
- While he works, a glowing border and a bar show "AI control active", with Pause and Stop.
- **Stop him instantly:** move the mouse, press **Control-Option-Q** (Ctrl+Alt+Q on Windows), press Stop, or say "stop".
- He asks before each task by default, and always before anything risky: sending, posting, buying, deleting,
  installing or signing out. He never types into password fields.
- **Blender:** everyday 3D commands run directly: "create a cube", "make it two times bigger", "color it red",
  "rotate it 45 degrees", "delete the cube", "undo".

### Conversation and questions

Anything that isn't a command goes to his AI: explanations, ideas, summaries, translations, advice, general
knowledge. He remembers the conversation, so follow-up questions work.

### Several things in one sentence

"Solve x squared plus 3x minus 4 equals 0 and draw the function", "open Spotify and play Radiohead". He does each
part in order and answers them together.

### Forgiving of typos

Common misspellings are fixed before he reads a command: "distence", "greph", "seconeds", "tell my about saturn",
"genearte an image".

---

## 4. Things that stay on screen

Every graph, globe and planet is kept for the session:

- Each one is a small clickable picture in the conversation.
- **‹ ›** or the arrow keys step between them.
- "Show the graph again", "the previous one", "the next one" work by voice.
- **Save image** stores a PNG.

---

## 5. Jarvis on your phone

A chat app for iPhone and Android that you add to your Home Screen. It looks and moves like Jarvis's window on the
computer: the same dark HUD, the same orb, and one accent colour that changes with what he is doing (listening,
thinking, speaking, asleep).

The first time you open it, it offers two ways to start:

- **Scan the code on my computer:** say **"Connect my phone"** on the computer, then point the app's own camera at
  the QR code on the screen. This works from anywhere, not only on your home Wi-Fi. (Scanning the code with the
  phone's normal Camera app works too, and then shows how to add Jarvis to the Home Screen.)
- **Use Jarvis on this phone only:** no computer at all. You paste your own Groq key (free at console.groq.com) and
  Jarvis answers and acts on the phone. You can connect a computer later from the menu.

Every time you open it, it asks **"Which Jarvis?"**:

- **On my computer:** a chat with the Jarvis on your computer. Everything you send runs there, exactly as if you had
  typed it at the computer: music, apps, documents, computer control. If Jarvis is closed on the computer, he is
  opened. Graphs, planets and the 3D globe **also open on the phone**, full screen, drawn by the same code.
- **On this phone:** Jarvis acts on the phone itself: opens apps, starts calls and messages, opens maps and
  directions, searches, and answers questions with his own AI. Nothing is opened on the computer. This works even
  when the computer is off. Graph, planet and globe questions are sent to the computer when it is reachable and come
  back as pictures on the phone.

You can switch between the two at the top of the chat at any time. "On my computer" or "on my phone" in a sentence
always wins for that one request.

You can also hold the microphone button and speak.

**Away from home:** a paired phone can reach your computer from anywhere through a small relay server. Everything
between the phone and the computer is end-to-end encrypted with a key only those two have; the relay only passes
along bytes it cannot read. On your home Wi-Fi the connection is encrypted too.

---

## 6. Jarvis Wake

A small helper that keeps running in the background on a Mac, even when Jarvis is closed. It does two things:

- Listens only for "Hey Jarvis", "Wake up Jarvis" or "Hello Jarvis", and opens Jarvis when it hears one.
- Lets your paired phone open Jarvis on the computer.

It pauses whenever Jarvis himself is running.

---

## 7. The AI behind him

Jarvis uses AI for understanding open questions, writing, and looking at pictures. Reliable commands (music, timers,
graphs, the globe, calendar and so on) are handled by his own code first, without asking an AI, which makes them fast
and predictable.

- **On your computer (default):** a local AI (Ollama, `llama3.2`) and local speech recognition (Whisper). No account
  and no key; works offline after the first start.
- **Online, faster (optional):** a free Groq key in Settings. He then answers with a larger model and falls back to
  the local AI by himself if Groq can't be reached.
- **Speech:** Whisper, with a second recognizer as a cross-check. Whisper sometimes invents phrases like "Goodbye"
  from silence, so those must be heard by both recognizers before they count.
- **Pictures:** the best service that is set up is used first: OpenAI (if you add a key), then Cloudflare FLUX (free
  account), then a free public service. A small local model is the fallback when there is no internet.

---

## 8. Privacy and safety

- **Your data stays on your computer:** settings, logs, conversation transcripts and pictures are stored locally.
  Conversation logs can be turned off.
- **WhatsApp messages** are only spoken and shown. They are never sent to an online AI, never added to his memory,
  and never written to the transcripts.
- **Screenshots** for computer control are looked at only by the local AI unless you turn the online option on
  yourself.
- **The microphone** in his window only measures loudness for the orb. Muting stops listening completely.
- **Phone connection:** pairing needs the code on your computer's screen, which is single-use and expires after a
  few minutes. The QR code holds a one-time key, so the pairing itself is sealed end to end (the relay in between
  cannot read it); the typed 6-digit code only works on your own Wi-Fi. After that, everything is encrypted. You can list or forget paired phones by voice ("what phones are paired", "forget my paired phones").
- **Computer control** always shows when it is active, stops the moment you move the mouse, and asks before risky
  steps.
- **Honesty rules built into him:** he never says he did something unless it actually happened, never invents
  places, distances or events, and labels estimates as estimates.

---

## 9. Settings

| Section | What you can set |
|---|---|
| **AI** | Which AI answers (local, online with local backup, or online only); the Groq key; the local model; whether the local AI may look at pictures and the screen. |
| **Voice** | Microphone; Jarvis's voice; whether he waits for "Hey Jarvis"; speaking volume; mute his voice. |
| **Computer control** | Mouse and keyboard: ask each time / allowed / never. What may look at the screen. Whether your phone may control this computer. The relay address. |
| **General** | Your name; the weather city; where events go (Apple or Google Calendar); where trailers play (YouTube or Netflix). |
| **Privacy** | Keep conversation logs; let Jarvis read WhatsApp. |
| **Optional services** | Keys for OpenAI and Cloudflare (better pictures), Spotify, Google Calendar, your two Google accounts, and Twilio (text messages). |

---

## 10. Keyboard shortcuts

| Key | What it does |
|---|---|
| **/** | Jump to the typing box |
| **Enter** | Send what you typed |
| **↑ / ↓** | Bring back what you typed before |
| **M** | Mute or unmute the microphone |
| **Space** | Stop Jarvis speaking |
| **F** | Full screen on or off |
| **Esc** | Close the open window (graph, globe, planet, weather) or leave full screen |
| **G / E / P** | Show or hide the last graph / globe / planet |
| **← / →** | Previous or next graph, globe or planet |
| **Space / R / S** (globe open) | Pause or resume / replay / skip the flight |
| **Control-Option-Q** | Emergency stop for computer control (Ctrl+Alt+Q on Windows) |

---

## 11. What works where

| Feature | macOS | Windows |
|---|---|---|
| Voice, typing, timers, AI answers, graphs, globe, planets, weather, pictures | Yes | Yes |
| Open apps and websites, YouTube / Netflix / Stremio | Yes | Yes |
| Spotify control | Yes | Yes (media keys) |
| Jump to a time, close a specific tab | Any Chrome tab | The active tab of a browser window |
| Documents | Word, Pages, TextEdit, Notes, Google Docs | Word, Notepad, Google Docs |
| Apple Calendar events | Yes | No (Google Calendar instead) |
| WhatsApp reading, Classroom reading | Yes | No |
| Computer control | Yes (needs the Accessibility permission) | Yes |
| Jarvis Wake | Yes | Yes |
| Phone app | iPhone and Android | iPhone and Android |

On a Mac, macOS asks once for each permission Jarvis needs: the microphone, controlling Chrome or Calendar, and
Accessibility for typing and clicking.

---

## 12. Honest limits

- **Picture quality** depends on the service. Without an OpenAI or Cloudflare key, the free service is basic, adds a
  watermark, and limits how often you can use it.
- **Picture editing** needs an OpenAI key.
- **The phone app in "On this phone" mode** can do what a web page is allowed to do on a phone: open apps, calls,
  messages, maps, search and answers. It cannot set alarms or change Wi-Fi or Bluetooth.
- **Graphs, planets and the globe on the phone** need the computer to be reachable, because the maths and maps run
  there.
- **Very short trips** on the globe (under about 100 km) look soft when zoomed in; the satellite imagery is global,
  not street-level. There are no buildings or terrain.
- **"Nearby cities"** uses a list of about 7,300 places, so small towns are missing.
- **Flight times** are estimates, not airline schedules.
- **Computer control** works well with the online AI; the small local AI handles only short, simple tasks.
- **Google Calendar** needs a one-time setup. Without it, Jarvis opens Google Calendar's own new-event page filled in
  and saves it in the browser.

---

## 13. How he is built (for the curious)

- **The engine** is written in Python (`app.py` and about 40 modules, one per ability: `music.py`, `earth.py`,
  `geo.py`, `graphs.py`, `planets.py`, `documents.py`, `timers.py`, `netflix.py`, `images.py` and so on).
- **The window** is an Electron app (`index.html`, `renderer.js`, `style.css`), with the 3D drawing in `earth.js`,
  `planet.js`, `graph.js` and `sphere_gl.js` (WebGL).
- **The phone app** is a web app (`phone_client.html`) with its own small Jarvis (`phone_agent.js`). A native app
  for iPhone and Android also exists (`mobile/`, built with Expo).
- **The relay** (`relay/server.py`) is the small server that lets a phone reach the computer from anywhere.
- **Jarvis Wake** (`wake/`) is the background listener.
- **Tests:** about 850 automated tests check the commands, the geography, the phone connection and more, without
  needing a microphone, the internet or real apps.
- **Free data he relies on:** NASA Blue Marble and Black Marble imagery, Natural Earth borders and places,
  Open-Meteo weather and place lookup, OpenStreetMap.
