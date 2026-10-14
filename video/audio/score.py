"""The film's soundtrack, made from nothing but arithmetic: an original piece of ambient electronic music and the
sound effects, written to audio/cues.json (the film's own timeline: where each scene starts, where things happen).

    venv/bin/python video/audio/score.py             ->  assets/audio/music.wav, sfx.wav        (the first film)
    venv/bin/python video/audio/score.py showcase    ->  assets/audio/showcase/music.wav, sfx.wav, jarvis.wav
    venv/bin/python video/audio/score.py trailer     ->  assets/audio/trailer/... and narrator.wav (the narration, placed)

Everything is original and generated here, so there is nothing to license. 100 beats a minute in D minor; a bar is
2.4 s, and every scene of the film is a whole number of bars, so cuts land on the music.
"""
import json
import os
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FILM = next((a for a in sys.argv[1:] if not a.startswith("-")), "")   # "" = the first film, "showcase", or "trailer"
NARRATION = os.path.join(HERE, "..", "assets", "narration")            # the trailer's narrator, one file a line
OUT = os.path.join(HERE, "..", "assets", "audio", FILM)
VOICE = os.path.join(HERE, "..", "assets", "voice")                   # Jarvis's own spoken replies, saved with the footage
SR = 48000
rng = np.random.default_rng(7)

cues = json.load(open(os.path.join(HERE, f"cues.{FILM}.json" if FILM else "cues.json"), encoding="utf-8"))
BAR, BEAT = cues["bar"], cues["bar"] / 4
TOTAL = cues["duration"] + 1.0
N = int(TOTAL * SR)
SCENES = {s["id"]: s for s in cues["scenes"]}


def hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def bus():
    return np.zeros((2, N), dtype=np.float32)


def put(dest, at: float, sound, gain: float = 1.0, pan: float = 0.0) -> None:
    """Mix a mono (or stereo) sound into a bus at `at` seconds. pan: -1 left .. 1 right."""
    start = int(round(at * SR))
    if start >= N:
        return
    if start < 0:
        sound, start = sound[..., -start:], 0
    length = min(sound.shape[-1], N - start)
    if length <= 0:
        return
    if sound.ndim == 1:
        left, right = np.cos((pan + 1) * np.pi / 4) * 1.4142, np.sin((pan + 1) * np.pi / 4) * 1.4142
        dest[0, start:start + length] += sound[:length] * (gain * left)
        dest[1, start:start + length] += sound[:length] * (gain * right)
    else:
        dest[:, start:start + length] += sound[:, :length] * gain


def env(n: int, attack: float, release: float, hold: float = None, curve: float = 1.0):
    """Attack, optional hold, release (seconds), over n samples."""
    t = np.arange(n) / SR
    total = n / SR
    up = np.clip(t / max(attack, 1e-4), 0, 1)
    down = np.clip((total - t) / max(release, 1e-4), 0, 1) if hold is None else np.clip(1 - (t - attack - hold) / max(release, 1e-4), 0, 1)
    return (np.minimum(up, down) ** curve).astype(np.float32)


def spectrum_filter(x, shape):
    """Filter by multiplying the spectrum with shape(frequencies)."""
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.shape[-1], 1 / SR)
    return np.fft.irfft(spec * shape(freqs), x.shape[-1]).astype(np.float32)


def band(lo: float, hi: float, slope: float = 0.35):
    """A smooth band-pass shape between lo and hi Hz."""
    def shape(f):
        f = np.maximum(f, 1e-3)
        up = 1 / (1 + (lo / f) ** (2 / slope)) if lo > 0 else 1.0
        down = 1 / (1 + (f / hi) ** (2 / slope)) if hi < SR / 2 else 1.0
        return up * down
    return shape


def noise(seconds: float, lo: float, hi: float):
    return spectrum_filter(rng.standard_normal(int(seconds * SR)).astype(np.float32), band(lo, hi))


def convolve(x, impulse):
    size = 1 << int(np.ceil(np.log2(x.shape[-1] + impulse.shape[-1])))
    out = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(impulse, size), size)
    return out[..., :x.shape[-1]].astype(np.float32)


def reverb(stereo, seconds: float = 3.2, bright: float = 5200.0, gain: float = 1.0):
    """A hall: decaying noise, different in each ear, darker as it fades."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros_like(stereo)
    for ch in range(2):
        impulse = rng.standard_normal(n).astype(np.float32) * np.exp(-t * 6.9 / seconds)
        impulse[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
        impulse = spectrum_filter(impulse, band(180, bright))
        impulse /= np.sqrt(np.sum(impulse ** 2)) + 1e-9
        out[ch] = convolve(stereo[ch], impulse)
    return out * gain


# ---------- where the music is, bar by bar ----------
# D minor, four bars round: Dm9, Bbmaj7, Fadd9, C6/9 (as MIDI notes)
CHORDS = [
    {"root": 38, "pad": [50, 57, 60, 64, 65, 69], "arp": [62, 65, 69, 72, 76, 77, 81]},      # Dm9
    {"root": 34, "pad": [46, 53, 57, 62, 65, 69], "arp": [58, 62, 65, 69, 74, 77, 81]},      # Bbmaj7
    {"root": 41, "pad": [53, 57, 60, 65, 67, 72], "arp": [60, 65, 67, 72, 77, 79, 81]},      # Fadd9
    {"root": 36, "pad": [48, 55, 57, 62, 64, 67], "arp": [60, 64, 67, 69, 74, 76, 79]},      # C6/9
]
BARS = int(np.ceil(cues["duration"] / BAR)) + 1
# how loud each layer is in each scene: pad, bass, arp, kick, hats, clap, pad brightness (harmonics kept)
LEVELS = {
    "opening":  dict(pad=0.55, bass=0.0, arp=0.0, kick=0.0, hat=0.0, clap=0.0, bright=3),
    "talk":     dict(pad=0.8, bass=0.55, arp=0.3, kick=0.0, hat=0.0, clap=0.0, bright=4),
    "media":    dict(pad=0.8, bass=0.8, arp=0.62, kick=0.75, hat=0.3, clap=0.0, bright=5),
    "control":  dict(pad=0.8, bass=0.8, arp=0.5, kick=0.75, hat=0.2, clap=0.0, bright=4),
    "docs":     dict(pad=0.85, bass=0.7, arp=0.55, kick=0.6, hat=0.0, clap=0.0, bright=4),
    "math":     dict(pad=0.9, bass=0.9, arp=0.8, kick=0.85, hat=0.45, clap=0.3, bright=6),
    "space":    dict(pad=1.0, bass=0.95, arp=0.8, kick=0.9, hat=0.5, clap=0.45, bright=8),
    "everyday": dict(pad=0.9, bass=0.95, arp=0.85, kick=0.9, hat=0.6, clap=0.5, bright=7),
    "phone":    dict(pad=0.85, bass=0.85, arp=0.65, kick=0.75, hat=0.3, clap=0.0, bright=5),
    "trust":    dict(pad=0.9, bass=0.5, arp=0.32, kick=0.0, hat=0.0, clap=0.0, bright=4),
    "closing":  dict(pad=1.0, bass=0.7, arp=0.4, kick=0.0, hat=0.0, clap=0.0, bright=7),
}


def scene_at(t: float) -> str:
    for s in cues["scenes"]:
        if t < s["end"] - 1e-6:
            return s["id"]
    return cues["scenes"][-1]["id"]


def level(layer: str, t: float) -> float:
    name = scene_at(t)
    mix = SCENES[name].get("mix") or LEVELS[name]     # a film may give each scene its own mix (film/showcase.js does)
    return mix.get(layer, 0)


pad, bass, arp, drums, air = bus(), bus(), bus(), bus(), bus()
print("pad", flush=True)
final_at = next(c["t"] for c in cues["cues"] if c["kind"] == "final")
for bar in range(BARS):
    at = bar * BAR
    chord = CHORDS[bar % 4]
    if at >= final_at - 0.01:      # the last chord: D major with its ninth, held to the end (the resolution)
        chord = {"root": 38, "pad": [50, 57, 62, 66, 69, 76], "arp": [62, 66, 69, 74, 76, 78, 81]}
    amount, bright = level("pad", at + 0.01), level("bright", at + 0.01)
    if at >= cues["duration"]:
        break
    length = BAR + 1.6
    if at >= final_at - 0.01:
        length = TOTAL - at
        if at > final_at + 0.01:
            continue
    n = int(length * SR)
    t = np.arange(n) / SR
    shape = env(n, 0.9, 1.5)
    for i, note in enumerate(chord["pad"]):
        for detune, pan in ((-0.07, -0.7), (0.06, 0.7), (0.0, 0.0)):
            f = hz(note + detune)
            wave_ = np.zeros(n, dtype=np.float32)
            for harmonic in range(1, int(bright) + 1):
                if f * harmonic > 7000:
                    break
                wave_ += (np.sin(2 * np.pi * f * harmonic * t + rng.uniform(0, 6.28)) / harmonic ** 1.55).astype(np.float32)
            wobble = 1 + 0.12 * np.sin(2 * np.pi * (0.13 + 0.03 * i) * (t + at) + i)
            put(pad, at, wave_ * shape * wobble.astype(np.float32), 0.022 * amount * (0.8 if detune else 1.0), pan * (0.4 + 0.1 * i))

print("bass, arp, drums", flush=True)
ARP_ORDER = [0, 2, 1, 3, 2, 4, 3, 5, 0, 2, 4, 3, 5, 4, 6, 3]
kick_times = []
for bar in range(BARS):
    at = bar * BAR
    if at >= cues["duration"] - 0.5:
        break
    chord = CHORDS[bar % 4] if at < final_at - 0.01 else {"root": 38, "arp": [62, 66, 69, 74, 76, 78, 81]}
    scene_name = scene_at(at + 0.01)
    # --- bass: a long root with a soft pulse
    amount = level("bass", at + 0.01)
    if amount > 0:
        n = int((BAR + 0.25) * SR)
        t = np.arange(n) / SR
        f = hz(chord["root"])
        tone = np.sin(2 * np.pi * f * t) + 0.32 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
        throb = 0.78 + 0.22 * np.cos(2 * np.pi * t / (BEAT / 2)) if level("kick", at + 0.01) else 1.0
        put(bass, at, (tone * throb * env(n, 0.04, 0.3)).astype(np.float32), 0.12 * amount)
    # --- arp: plucked notes, sixteenths, with the accent on the beat
    amount = level("arp", at + 0.01)
    if amount > 0:
        sparse = scene_name in ("talk", "trust", "closing") or amount < 0.5
        for step in range(16):
            if sparse and step % 4 not in (0, 3):
                continue
            if at + step * BEAT / 4 >= final_at + 4.0:
                continue
            note = chord["arp"][ARP_ORDER[(step + 5 * (bar % 2)) % 16] % len(chord["arp"])] + (12 if (step % 8 == 6 and not sparse) else 0)
            n = int(0.9 * SR)
            t = np.arange(n) / SR
            f = hz(note)
            pluck = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9) + 0.12 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 14))
            pluck = (pluck * np.exp(-t * (5.5 if sparse else 8.5)) * np.clip(t / 0.004, 0, 1)).astype(np.float32)
            accent = 1.0 if step % 4 == 0 else 0.62 if step % 2 == 0 else 0.45
            where = at + step * BEAT / 4
            pan = 0.55 * np.sin(step * 1.9 + bar)
            put(arp, where, pluck, 0.075 * amount * accent, pan)
            for echo, (gain, side) in enumerate(((0.36, -1), (0.2, 1), (0.1, -1)), start=1):   # dotted-eighth echoes, side to side
                put(arp, where + echo * BEAT * 0.75, pluck, 0.075 * amount * accent * gain, side * 0.8 * (1 if pan >= 0 else -1))
    # --- drums
    for beat in range(4):
        where = at + beat * BEAT
        amount = level("kick", where + 0.01)
        if amount > 0:
            n = int(0.42 * SR)
            t = np.arange(n) / SR
            sweep = 46 + 78 * np.exp(-t * 34)
            kick = np.sin(2 * np.pi * np.cumsum(sweep) / SR) * np.exp(-t * 9.5) + 0.25 * np.exp(-t * 900) * rng.standard_normal(n)
            put(drums, where, (kick * np.clip(t / 0.002, 0, 1)).astype(np.float32), 0.3 * amount)
            kick_times.append(where)
        amount = level("hat", where + 0.01)
        if amount > 0:
            for off, gain in ((0.5, 1.0), (0.75, 0.45), (0.25, 0.3)):
                tick = noise(0.07, 6500, 15000) * np.exp(-np.arange(int(0.07 * SR)) / SR * 70)
                put(drums, where + off * BEAT, tick.astype(np.float32), 0.06 * amount * gain, 0.25 if off == 0.5 else -0.3)
        amount = level("clap", where + 0.01)
        if amount > 0 and beat in (1, 3):
            n = int(0.22 * SR)
            t = np.arange(n) / SR
            burst = noise(0.22, 900, 3600) * (np.exp(-t * 30) + 0.7 * np.exp(-np.abs(t - 0.012) * 400) + 0.6 * np.exp(-np.abs(t - 0.024) * 400))
            put(drums, where, burst.astype(np.float32), 0.085 * amount)

# the kick pushes the pad and the bass down a little, so the music breathes with it
duck = np.ones(N, dtype=np.float32)
dip = 1 - 0.42 * np.exp(-np.arange(int(0.36 * SR)) / SR * 9)
for where in kick_times:
    i = int(where * SR)
    j = min(N, i + dip.size)
    duck[i:j] = np.minimum(duck[i:j], dip[: j - i])
pad *= duck
bass *= duck

# ---------- the opening: a low drone before the music arrives ----------
n = int(14 * SR)
t = np.arange(n) / SR
drone = (np.sin(2 * np.pi * hz(26) * t) + 0.6 * np.sin(2 * np.pi * hz(38) * t + 0.4 * np.sin(2 * np.pi * 0.11 * t)) + 0.25 * np.sin(2 * np.pi * hz(45) * t))
put(air, 0.2, (drone * env(n, 3.5, 4.0)).astype(np.float32), 0.085)
put(air, 0.0, noise(14, 300, 2200) * env(n, 5, 5), 0.012)

# ---------- sound effects ----------
print("effects", flush=True)
fx, fx_wet = bus(), bus()


def chime(notes, length=2.4, decay=2.2):
    n = int(length * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for i, note in enumerate(notes):
        f = hz(note)
        partial = np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t * 3) + 0.2 * np.sin(2 * np.pi * f * 3.02 * t) * np.exp(-t * 6)
        start = int(i * 0.07 * SR)
        out[start:] += (partial * np.exp(-t * decay) * np.clip(t / 0.006, 0, 1))[: n - start].astype(np.float32)
    return out / max(1, len(notes)) ** 0.5


def blip(f0, f1, length=0.12, decay=30):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = f0 + (f1 - f0) * (t / length)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * decay) * np.clip(t / 0.003, 0, 1)).astype(np.float32)


def whoosh(length=0.7, lo=500, hi=6000, peak=0.6):
    n = int(length * SR)
    t = np.arange(n) / SR
    shape = np.exp(-((t - peak * length) / (0.22 * length)) ** 2)
    left, right = noise(length, lo, hi) * shape, noise(length, lo, hi) * shape
    sweep = np.linspace(0.2, 1.0, n) ** 2
    return np.stack([left * (1 - 0.6 * sweep), right * (0.4 + 0.6 * sweep)]).astype(np.float32)


def riser(length=1.4):
    n = int(length * SR)
    t = np.arange(n) / SR
    grow = (t / length) ** 2.4
    hiss = noise(length, 1500, 11000) * grow
    f = 180 * 2 ** (2.2 * t / length)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * grow * 0.25
    return ((hiss + tone) * np.clip((length - t) / 0.03, 0, 1)).astype(np.float32)


def impact(deep=1.0):
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    f = 34 + 60 * np.exp(-t * 7)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.4) * deep
    crack = noise(2.6, 200, 4200) * np.exp(-t * 7) * 0.5
    return ((boom + crack) * np.clip(t / 0.004, 0, 1)).astype(np.float32)


for cue in cues["cues"]:
    kind, at = cue["kind"], cue["t"]
    if kind == "orb":
        put(fx_wet, at, chime([74, 81, 86, 93], 4.0, 1.1), 0.2)
        put(fx_wet, at, impact(0.7), 0.16)
    elif kind == "title":
        put(fx, at, impact(1.0), 0.42)
        put(fx_wet, at, chime([62, 69, 77, 81, 88], 4.0, 0.9), 0.24)
    elif kind == "final":
        put(fx, at, impact(1.2), 0.5)
        put(fx_wet, at, chime([62, 66, 69, 74, 81, 86, 90], 6.0, 0.6), 0.3)
        put(fx_wet, at - 2.0, riser(2.0), 0.16)
    elif kind == "swell":
        put(fx_wet, at, riser(1.4), 0.15)
    elif kind == "whoosh":
        put(fx_wet, at, whoosh(0.7), 0.2)
    elif kind == "slide":
        put(fx_wet, at - 0.1, whoosh(0.42, 900, 7000, 0.45), 0.14)
    elif kind == "listen":
        put(fx, at, blip(620, 640, 0.09), 0.2)
        put(fx, at + 0.11, blip(930, 950, 0.14, 18), 0.2)
        put(fx_wet, at + 0.11, blip(930, 950, 0.14, 18), 0.1)
    elif kind in ("tick", "click"):
        put(fx, at, blip(1500, 900, 0.035, 110), 0.2)
    elif kind == "keys":
        clock, end = at, at + cue.get("len", 1.5)
        while clock < end:
            put(fx, clock, blip(rng.uniform(1700, 2300), 1200, 0.018, 260), rng.uniform(0.05, 0.085), rng.uniform(-0.3, 0.3))
            clock += rng.uniform(0.045, 0.11)
    elif kind == "send":
        put(fx, at, blip(480, 900, 0.1, 26), 0.17)
    elif kind == "confirm":
        put(fx_wet, at, chime([81, 86], 1.6, 3.4), 0.2)
        put(fx, at, chime([81, 86], 1.6, 3.4), 0.1)
    elif kind == "sheet":
        put(fx, at, blip(220, 150, 0.3, 9), 0.26)
        put(fx_wet, at, whoosh(0.5, 300, 3000, 0.4), 0.2)
    elif kind == "stop":
        put(fx, at, blip(700, 690, 0.1, 22), 0.2)
        put(fx, at + 0.12, blip(470, 460, 0.2, 14), 0.2)
    elif kind == "page":
        put(fx_wet, at, whoosh(0.5, 1800, 9000, 0.35), 0.2)
    elif kind in ("draw", "globe"):
        n = int(1.0 * SR)
        t = np.arange(n) / SR
        f = 500 * 2 ** (1.6 * t)
        shimmer = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t) ** 2
        put(fx_wet, at, shimmer.astype(np.float32), 0.085)
        if kind == "globe":
            put(fx, at, impact(0.9), 0.3)
    elif kind == "steps":
        for i, note in enumerate([74, 77, 81, 86]):
            put(fx_wet, at + i * 0.3, chime([note], 1.0, 5), 0.13)
    elif kind == "switch":
        put(fx, at, blip(1300, 800, 0.04, 100), 0.2)
        put(fx_wet, at + 0.06, chime([86, 93], 1.2, 4), 0.14)
    elif kind == "hit":          # the trailer's big moments: a deep impact under a low, slow chord
        put(fx, at, impact(1.4), 0.4)
        n = int(3.2 * SR)
        t = np.arange(n) / SR
        horn = np.zeros(n, dtype=np.float32)
        for note, weight in ((26, 1.0), (38, 0.8), (45, 0.45), (50, 0.3)):
            for detune in (-0.08, 0.07):
                f = hz(note + detune)
                for harmonic in range(1, 9):
                    horn += (weight * np.sin(2 * np.pi * f * harmonic * t + harmonic) / harmonic ** 1.25).astype(np.float32)
        put(fx_wet, at, horn * np.clip(t / 0.03, 0, 1) * np.exp(-t * 1.5), 0.022)
    elif kind == "heartbeat":
        for delay, gain in ((0.0, 1.0), (0.3, 0.7)):
            n = int(0.3 * SR)
            t = np.arange(n) / SR
            thump = np.sin(2 * np.pi * (48 + 30 * np.exp(-t * 40)) * t) * np.exp(-t * 16)
            put(fx, at + delay, thump.astype(np.float32), 0.34 * gain)
    elif kind == "wake":
        put(fx, at, impact(1.0), 0.4)
        put(fx_wet, at, chime([62, 69, 74, 81, 86, 93], 5.0, 0.8), 0.3)
        put(fx_wet, at - 0.7, riser(0.7), 0.14)
    elif kind == "open":
        put(fx, at, impact(0.8), 0.3)
        put(fx_wet, at, whoosh(0.6, 400, 5000, 0.35), 0.2)
        put(fx_wet, at + 0.05, chime([74, 81, 86], 2.0, 2.2), 0.14)
    elif kind == "link":
        put(fx_wet, at, chime([74, 81, 86], 2.5, 1.6), 0.16)

# a scene that builds (no drums of its own): a roll of soft hits that tightens toward the next scene
for s in cues["scenes"]:
    if (s.get("mix") or {}).get("build"):
        start = max(s["start"], s["end"] - 2 * BAR)
        steps = int((s["end"] - start) / (BEAT / 4))
        for i in range(steps):
            where = start + i * BEAT / 4
            if i < steps // 2 and i % 2:
                continue
            n = int(0.16 * SR)
            t = np.arange(n) / SR
            hit = noise(0.16, 700, 5200) * np.exp(-t * 34) + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 26)
            put(drums, where, hit.astype(np.float32), 0.02 + 0.075 * (i / steps) ** 1.6, 0.25 * np.sin(i))

# a soft rise into each new scene (the music's own breath between sections)
for s in cues["scenes"][1:]:
    strong = s["id"] in ("math", "space", "closing", "talk", "mind", "world", "more", "close", "power", "escalation")
    put(fx_wet, s["start"] - (1.6 if strong else 1.0), riser(1.6 if strong else 1.0), 0.1 if strong else 0.05)
    if strong:
        put(fx, s["start"], impact(0.9), 0.3)

print("mix", flush=True)
music = pad + bass + arp + drums + air
music += reverb(pad * 0.5 + arp * 0.55 + drums * 0.1 + air * 0.6, 3.4, 5000, 0.42)
effects = fx + fx_wet * 0.5 + reverb(fx_wet + fx * 0.25, 2.8, 6500, 0.55)


def master(x, peak=0.89):
    """Gentle fades at both ends, no rumble below 28 Hz, and a soft ceiling."""
    x = np.stack([spectrum_filter(ch, band(28, 15500)) for ch in x])
    edge = np.clip(np.arange(N) / (0.3 * SR), 0, 1) * np.clip((N - np.arange(N)) / (2.8 * SR), 0, 1)
    x = x * edge.astype(np.float32)
    return x


def save(name, x):
    data = (np.clip(x, -1, 1).T * 32767).astype("<i2")
    with wave.open(os.path.join(OUT, name), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(data.tobytes())


os.makedirs(OUT, exist_ok=True)
music, effects = master(music), master(effects)
level_now = float(np.max(np.abs(music + effects)))
scale = 0.82 / level_now
# In the trailer a few very loud blows set the peak, which would leave the music under them too quiet: bring it up.
lift = 2.1 if FILM == "trailer" else 1.0
music, effects = np.tanh(music * scale * 1.15 * lift) / 1.15, effects * scale

# ---------- silence before a blow: the music and effects drop out for a moment ----------
for cue in cues["cues"]:
    if cue["kind"] == "cutout":
        i, j = int(cue["t"] * SR), min(N, int((cue["t"] + cue["len"]) * SR))
        ramp = int(0.02 * SR)
        gate = np.ones(j - i, dtype=np.float32) * 0.04
        gate[:ramp] = np.linspace(1, 0.04, ramp)
        music[:, i:j] *= gate
        effects[:, i:j] *= gate


def lay(kind, folder, level, room, music_dip, effects_dip, name):
    """A speaking track: the files of every `kind` cue placed on the timeline, each cut at a breath if the film leaves
    it early, with the music and effects stepping back underneath. Saved as `name`; removed when there is none."""
    global music, effects
    spoken = [c for c in cues["cues"] if c["kind"] == kind]
    if not spoken:
        if os.path.exists(os.path.join(OUT, name)):
            os.remove(os.path.join(OUT, name))
        return
    track = bus()
    busy = np.zeros(N, dtype=np.float32)
    for cue in spoken:
        with wave.open(os.path.join(folder, cue["file"])) as f:
            line = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float32) / 32768
        # stop at a breath: the pause between sentences nearest to where the film cuts away (never mid-word if avoidable)
        target = int(cue["len"] * SR)
        if target < line.size - int(0.3 * SR):
            quiet = np.convolve((np.abs(line) < 0.012).astype(np.float32), np.ones(int(0.16 * SR), dtype=np.float32), mode="same") >= int(0.16 * SR) - 1
            pauses = np.flatnonzero(quiet)
            near = pauses[(pauses > target - int(1.6 * SR)) & (pauses < target + int(0.5 * SR))]
            if near.size:
                target = int(near[np.argmin(np.abs(near - target))])
        line = line[:target]
        cue["len"] = target / SR
        line = line / (np.sqrt(np.mean(line[np.abs(line) > 0.02] ** 2)) + 1e-9) * level      # every line at the same loudness
        shape = np.clip(np.arange(line.size) / (0.01 * SR), 0, 1) * np.clip((line.size - np.arange(line.size)) / (0.18 * SR), 0, 1)
        put(track, cue["t"], (line * shape * cue.get("gain", 1)).astype(np.float32), 1.0)
        i, j = int(cue["t"] * SR), min(N, int((cue["t"] + cue["len"]) * SR))
        busy[i:j] = 1
    track += reverb(track, *room)
    glide = int(0.25 * SR)
    smooth = np.convolve(busy, np.ones(glide, dtype=np.float32) / glide, mode="same")
    music *= (1 - music_dip * smooth)
    effects *= (1 - effects_dip * smooth)
    save(name, np.clip(track, -0.97, 0.97))


# Jarvis's own voice: the replies he spoke in the takes. A touch of room, so he sits in the film's space.
lay("voice", VOICE, 0.18 if FILM == "trailer" else 0.16, (0.9, 6000, 0.1), 0.56, 0.5 if FILM == "trailer" else 0.3, "jarvis.wav")
# The trailer's narrator: closer, louder, with a longer tail behind him; the music gives him more room.
lay("narrate", NARRATION, 0.17, (1.6, 5200, 0.16), 0.5, 0.5, "narrator.wav")
save("music.wav", music)
save("sfx.wav", effects)
rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
print(f"music {rms(music):.1f} dB RMS, effects {rms(effects):.1f} dB RMS, peak of both {20 * np.log10(np.max(np.abs(music + effects))):.1f} dB, {TOTAL:.1f} s")
