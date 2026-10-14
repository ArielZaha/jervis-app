"""The trailer's narrator: speaks every line of audio/trailer_narration.json -> assets/narration/<id>.wav, and writes
the real length of each line to audio/trailer_voice.json (the edit is timed to the voice, not the other way round).

Two ways to speak, chosen automatically:

  * Google AI Studio (Gemini text-to-speech), when a key is in the environment as GEMINI_API_KEY or GOOGLE_API_KEY
    (or on a GEMINI_API_KEY= line in the project's .env). Voice and model: GEMINI_VOICE (default Charon),
    GEMINI_TTS_MODEL (default gemini-2.5-flash-preview-tts).
  * Otherwise Kokoro, an open-source neural voice that runs on this computer (model files in tools.nosync/kokoro,
    see the README). Voice: KOKORO_VOICE (default am_onyx), deepened a little and slowed, as a trailer voice is.

    venv/bin/python video/audio/narrator.py              speak what is missing or changed
    venv/bin/python video/audio/narrator.py --all        speak everything again
    venv/bin/python video/audio/narrator.py --check      also transcribe each line back (needs the Groq key) and compare
    venv/bin/python video/audio/narrator.py --voices a b   audition voices on the first lines (prints pitch and length)
"""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(VIDEO, ".."))
OUT = os.path.join(VIDEO, "assets", "narration")
KOKORO = os.path.join(VIDEO, "tools.nosync", "kokoro")
SR = 48000


def env_key(*names: str) -> str:
    for name in names:
        if os.environ.get(name):
            return os.environ[name].strip()
    try:
        for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
            key, _, value = line.strip().partition("=")
            if key.strip() in names and value.strip():
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


def provider() -> str:
    return "gemini" if env_key("GEMINI_API_KEY", "GOOGLE_API_KEY") else "kokoro"


# ---------- Google AI Studio ----------
def gemini(text: str, direction: str):
    """One line from Gemini's text-to-speech: 24 kHz samples as floats."""
    import numpy as np
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    body = {"contents": [{"parts": [{"text": f"{direction}: {text}" if direction else text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": os.environ.get("GEMINI_VOICE", "Charon")}}}}}
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", data=json.dumps(body).encode(),
        headers={"x-goog-api-key": env_key("GEMINI_API_KEY", "GOOGLE_API_KEY"), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as e:
        sys.exit(f"Gemini speech failed ({e.code}): {e.read().decode('utf-8', 'replace')[:300]}")
    data = base64.b64decode(reply["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768, 24000


# ---------- Kokoro, on this computer ----------
_kokoro = None


def kokoro(text: str, voice: str, speed: float):
    global _kokoro
    if _kokoro is None:
        sys.path.insert(0, os.path.join(VIDEO, "tools.nosync", "tts"))
        model, voices = os.path.join(KOKORO, "kokoro-v1.0.onnx"), os.path.join(KOKORO, "voices-v1.0.bin")
        if not (os.path.exists(model) and os.path.exists(voices)):
            sys.exit("The Kokoro voice files are missing (video/tools.nosync/kokoro). See video/README.md, 'The narrator'.")
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(model, voices)
    samples, rate = _kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    return samples, rate


# ---------- making it a trailer voice ----------
def shape(samples, rate: int, deepen: float):
    """To 48 kHz, a little lower and slower (deepen < 1), then the usual voice chain: no rumble, more chest, a
    little presence, levelled, and trimmed of silence at both ends."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float32)
    step = rate * deepen / SR                                   # playing it slower lowers it and stretches it together
    x = np.interp(np.arange(0, x.size - 1, step), np.arange(x.size), x).astype(np.float32)
    spectrum = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / SR)
    gain = 1 / (1 + (70 / np.maximum(f, 1e-3)) ** 4)             # high-pass at 70 Hz
    gain *= 1 + 0.45 / (1 + (f / 170) ** 4)                      # +3 dB of chest below 170 Hz
    gain *= 1 + 0.28 * np.exp(-((np.log2(np.maximum(f, 1) / 3800)) ** 2) / 0.5)   # a little presence around 4 kHz
    gain *= 1 / (1 + (f / 13000) ** 6)
    x = np.fft.irfft(spectrum * gain, x.size).astype(np.float32)
    x = x / (np.max(np.abs(x)) + 1e-9)
    x = np.tanh(x * 2.2) / np.tanh(2.2)                          # gentle levelling: quiet syllables come up
    loud = np.flatnonzero(np.abs(x) > 0.02)
    x = x[max(0, loud[0] - int(0.03 * SR)): loud[-1] + int(0.12 * SR)]
    fade = int(0.01 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x * 0.8


def pitch(x) -> float:
    """The voice's typical pitch in Hz (the median of its voiced moments), for comparing voices."""
    import numpy as np
    found = []
    size = int(0.04 * SR)
    for start in range(0, x.size - size, size):
        frame = x[start:start + size]
        if np.sqrt(np.mean(frame ** 2)) < 0.05:
            continue
        frame = frame - frame.mean()
        corr = np.correlate(frame, frame, "full")[size - 1:]
        lo, hi = SR // 300, SR // 60
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] > 0.45 * corr[0]:
            found.append(SR / lag)
    return float(np.median(found)) if found else 0.0


def save(path: str, x) -> None:
    import numpy as np
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def speak(line: dict, script: dict, voice: str = None):
    if provider() == "gemini":
        samples, rate = gemini(line["say"], line.get("direction") or script.get("direction", ""))
        return shape(samples, rate, 1.0)
    voice = voice or os.environ.get("KOKORO_VOICE") or script.get("kokoro_voice", "am_onyx")
    samples, rate = kokoro(line.get("spoken") or line["say"], voice, line.get("speed", script.get("speed", 0.95)))
    return shape(samples, rate, script.get("deepen", 0.94))


def main() -> None:
    script = json.load(open(os.path.join(HERE, "trailer_narration.json"), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    if "--voices" in sys.argv:
        for voice in sys.argv[sys.argv.index("--voices") + 1:]:
            takes = [speak(line, script, voice) for line in script["lines"][:3]]
            for n, take in enumerate(takes):
                save(os.path.join(VIDEO, "cache.nosync", f"audition_{voice}_{n}.wav"), take)
            print(f"{voice:12s} pitch {sum(pitch(t) for t in takes) / len(takes):5.0f} Hz   {sum(t.size for t in takes) / SR:5.1f} s for the first three lines")
        return
    stamps_path = os.path.join(OUT, "made.json")
    stamps = json.load(open(stamps_path)) if os.path.exists(stamps_path) else {}
    who = provider() + ":" + (os.environ.get("GEMINI_VOICE", "Charon") if provider() == "gemini" else os.environ.get("KOKORO_VOICE") or script.get("kokoro_voice", "am_onyx"))
    lengths = {}
    for line in script["lines"]:
        path = os.path.join(OUT, line["id"] + ".wav")
        stamp = hashlib.sha1(json.dumps([who, line, script.get("speed"), script.get("deepen")], sort_keys=True).encode()).hexdigest()
        if "--all" in sys.argv or not os.path.exists(path) or stamps.get(line["id"]) != stamp:
            save(path, speak(line, script))
            stamps[line["id"]] = stamp
            json.dump(stamps, open(stamps_path, "w"), indent=1)
        with wave.open(path) as f:
            lengths[line["id"]] = round(f.getnframes() / f.getframerate(), 2)
        note = ""
        if "--check" in sys.argv:
            sys.path.insert(0, HERE)
            import tts
            back = tts.transcribe(path)
            same = re.sub(r"[^a-z]", "", back.lower()) == re.sub(r"[^a-z]", "", line["say"].lower())
            note = f"   heard: {back}" + ("" if same else "   <-- differs")
        print(f"{line['id']}  {lengths[line['id']]:5.2f} s  {line['say']}{note}", flush=True)
    json.dump({"voice": who, "lines": lengths}, open(os.path.join(HERE, "trailer_voice.json"), "w"), indent=1)
    print(f"narrator: {who}")


if __name__ == "__main__":
    main()
