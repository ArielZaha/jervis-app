"""Lays the spoken lines (audio/voice/*.wav, made by tts.py) onto the film's timeline -> assets/audio/voice.wav.
Does nothing, and removes an old voice.wav, when no lines have been recorded: the film is then music and titles only.

    venv/bin/python video/audio/voice.py
"""
import json
import os
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "audio", "voice.wav")
SR = 48000

cues = json.load(open(os.path.join(HERE, "cues.json"), encoding="utf-8"))
script = json.load(open(os.path.join(HERE, "narration.json"), encoding="utf-8"))
starts = {s["id"]: s["start"] for s in cues["scenes"]}
track = np.zeros(int((cues["duration"] + 1) * SR), dtype=np.float32)
placed, last_end = 0, 0.0
for line in script["lines"]:
    path = os.path.join(HERE, "voice", line["id"] + ".wav")
    if not os.path.exists(path):
        continue
    with wave.open(path) as f:
        rate, channels, width = f.getframerate(), f.getnchannels(), f.getsampwidth()
        raw = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2" if width == 2 else "<i4").astype(np.float32)
    raw = raw.reshape(-1, channels).mean(axis=1) / float(2 ** (8 * width - 1))
    if rate != SR:   # plain linear resampling is plenty for speech
        raw = np.interp(np.arange(0, raw.size, rate / SR), np.arange(raw.size), raw).astype(np.float32)
    raw = raw / (np.max(np.abs(raw)) + 1e-9) * 0.7
    at = max(starts[line["scene"]] + line["at"], last_end + 0.25)   # never talk over the line before
    i = int(at * SR)
    j = min(track.size, i + raw.size)
    track[i:j] += raw[: j - i]
    last_end = at + raw.size / SR
    placed += 1
    print(f"{line['id']}  {at:6.2f} s  {raw.size / SR:4.1f} s  {line['say'][:60]}")
if not placed:
    if os.path.exists(OUT):
        os.remove(OUT)
    print("no recorded lines: the film will be music and titles only")
else:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with wave.open(OUT, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"{placed} lines -> assets/audio/voice.wav")
