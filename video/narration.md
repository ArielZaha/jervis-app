# Jarvis product film — narration

The film is finished as a **music-and-titles** film: every scene carries its message in on-screen words, so it works
with no voice at all.

A voice-over is written and wired in, but **not recorded yet**. The voice it is written for is Groq's *Orpheus*
(`canopylabs/orpheus-v1-english`), which uses the Groq key Jarvis already has. Groq asks the account owner to accept
that model's terms once, in the browser, before it can be used:

1. Open <https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english> and accept the terms.
2. Run `video/build.sh voice`. It speaks each line, lays the lines on the timeline, lowers the music under them and
   makes `out/Jarvis_Product_Demo.mp4` again (the picture is not re-rendered).
3. To check the recording word for word, run `venv/bin/python video/audio/tts.py --check`: each recorded line is
   transcribed back and printed, so a garbled line is easy to spot and redo (`tts.py 07` speaks line 07 again).

The lines and their timing are in `audio/narration.json` (`at` = seconds after the scene begins). To use a human
voice instead, save one WAV per line as `audio/voice/01.wav`, `02.wav`, … and run `video/build.sh sound`.

| # | Scene | Line |
|---|---|---|
| 01 | Opening | Meet Jarvis. Your personal AI assistant. |
| 02 | Talk naturally | Say "Hey Jarvis", or simply type. He listens, thinks, and answers — out loud and in writing. |
| 03 | Music and shows | Ask for music, and it plays. Ask for a trailer, and it's on. Spotify, YouTube, Netflix and more — one request away. |
| 04 | Computer control | Need something done on your computer? With your permission, Jarvis takes the mouse and keyboard himself. |
| 05 | Computer control | And you can pause or stop him at any moment. |
| 06 | Documents | Ask for a story, an essay, or a summary. He writes it straight into a document, then reworks it when you ask. |
| 07 | Math | Math becomes something you can see. Graph a function, compare two, and find exactly where they meet. |
| 08 | Math | Every equation, solved step by step. |
| 09 | Earth | Then zoom out. A living 3D Earth shows the journey between any two places. |
| 10 | Planets | And beyond it, the planets. |
| 11 | Every day | Weather. Timers. Your calendar. Pictures made from a sentence, and answers about pictures of your own. |
| 12 | Phone | And Jarvis goes where you go. From your phone, send a request to your computer. |
| 13 | Phone | Or switch modes, and let the phone handle it by itself. |
| 14 | Privacy and control | He can run on a local AI, on your own computer. Phones pair with a one-time code. And he asks before taking control. |
| 15 | Closing | Jarvis. One assistant. Your computer. Your phone. |
