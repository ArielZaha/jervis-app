"""Jervis's Hebrew voice: a neural voice ("Shaul", Piper/VITS, from the Phonikud project — Interspeech 2026) in place
of Windows' old desktop voice (Microsoft Asaf), all on this computer's CPU (~0.2 s a sentence).

    text -> spoken form (file names instead of paths, "ה-6" instead of "minus 6") -> vowel marks and stress
    (phonikud-onnx, a Hebrew diacritizer built on Dicta's) -> phonemes (phonikud) -> audio (Piper voice, onnxruntime)

English words inside Hebrew ("פתחתי את Blender") are pronounced from the CMU Pronouncing Dictionary, mapped onto
the sounds the Hebrew voice knows; unknown English words by spelling rules.

Measured (each voice says Jervis's real Hebrew replies, ivrit.ai large-v3 writes back what it heard): character
error 5.8% for Shaul vs 6.0% for Asaf — as clear, but natural speech, the right vowels ("צור לי", which Asaf said as
"צאו לי"), and faster (0.23 s vs 0.38 s a sentence).

Files (downloaded once, into the models folder): the diacritizer (MIT, 308 MB), the voice (63 MB; the Phonikud
voices are licensed for NON-COMMERCIAL use), the CMU dictionary (BSD, 3.6 MB). Without them Jervis falls back to
Windows' Hebrew voice (osal.py).
"""
import io
import json
import os
import re
import threading
import time
import wave

import paths

FILES = {   # file: (where it comes from, approximate size)
    "phonikud-1.0.int8.onnx": ("hf:Phonikud/phonikud-onnx", 308e6),
    "tokenizer.json": ("hf:dicta-il/dictabert-large-char-menaked", 2e4),   # the diacritizer's (else fetched online)
    "shaul.onnx": ("hf:Phonikud/phonikud-tts-checkpoints", 64e6),
    "model.config.json": ("hf:Phonikud/phonikud-tts-checkpoints", 7e3),
    "cmudict.dict": ("https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict", 3.6e6),
}
PAUSE_SECONDS = 0.22   # between sentences
# Piper's variation (the voice's defaults: 0.667 / 0.8). Measured over 30 renderings heard back by ivrit.ai: with
# these the words came through 3.3% wrong on average and 3 of 30 badly, vs 8.3% and 8 of 30 with the defaults.
NOISE_SCALE, NOISE_W = 0.4, 0.5

_lock = threading.Lock()
_parts = {}


def folder() -> str:
    return os.path.join(paths.models_dir(), "hebrew-voice")


def downloaded() -> bool:
    return all(os.path.isfile(os.path.join(folder(), name)) for name in FILES)


def available() -> bool:
    if (os.getenv("JERVIS_HEBREW_VOICE") or "neural").lower() in ("windows", "off"):
        return False
    try:
        import onnxruntime  # noqa: F401
        import phonikud  # noqa: F401
        import phonikud_onnx  # noqa: F401
    except Exception:
        return False
    return downloaded()


def ensure(progress=None) -> None:
    """Download what's missing (setup calls this). Raises on failure; Windows' voice keeps working meanwhile."""
    import requests
    os.makedirs(folder(), exist_ok=True)
    for name, (source, size) in FILES.items():
        target = os.path.join(folder(), name)
        if os.path.isfile(target):
            continue
        if progress:
            progress(f"Downloading the Hebrew voice ({name}, about {max(1, round(size / 1e6))} MB)…", None)
        if source.startswith("hf:"):
            from huggingface_hub import hf_hub_download
            hf_hub_download(repo_id=source[3:], filename=name, local_dir=folder())
        else:
            response = requests.get(source, timeout=120)
            response.raise_for_status()
            with open(target + ".part", "wb") as f:
                f.write(response.content)
            os.replace(target + ".part", target)
    if not downloaded():
        raise RuntimeError("the Hebrew voice didn't download completely")


def _diacritizer(Phonikud):
    """phonikud-onnx fetches its tokenizer from Hugging Face every time it starts; this one reads the downloaded copy,
    so the voice works offline."""
    import phonikud_onnx.model as model
    from tokenizers import Tokenizer
    online = model.Tokenizer
    model.Tokenizer = type("LocalTokenizer", (), {
        "from_pretrained": staticmethod(lambda _name: Tokenizer.from_file(os.path.join(folder(), "tokenizer.json")))})
    try:
        return Phonikud(os.path.join(folder(), "phonikud-1.0.int8.onnx"))
    finally:
        model.Tokenizer = online


def _load():
    """The diacritizer, the voice and the dictionary, loaded once (~2 s). Called with _lock held."""
    if _parts:
        return _parts
    import onnxruntime as ort
    from phonikud_onnx import Phonikud
    options, parts = ort.SessionOptions(), {}
    options.intra_op_num_threads = max(2, min(6, (os.cpu_count() or 4) // 3))
    parts["diacritizer"] = _diacritizer(Phonikud)
    parts["voice"] = ort.InferenceSession(os.path.join(folder(), "shaul.onnx"), options,
                                          providers=["CPUExecutionProvider"])
    with open(os.path.join(folder(), "model.config.json"), encoding="utf-8") as f:
        parts["config"] = json.load(f)
    words = {}
    with open(os.path.join(folder(), "cmudict.dict"), encoding="utf-8", errors="replace") as f:
        for line in f:
            word, _, phones = line.partition(" ")
            if "(" not in word and phones:   # the first pronunciation of each word
                words[word] = phones.split("#")[0].split()
    parts["cmudict"] = words
    _parts.update(parts)   # all or nothing: a load that failed half-way is tried again next time
    return _parts


def preload() -> None:
    if available():
        try:
            with _lock:
                _load()
        except Exception as e:
            print(f"Couldn't load the Hebrew voice: {e}", flush=True)


# ---------- English words, in the Hebrew voice's sounds ----------
_ARPABET = {
    "AA": "a", "AE": "a", "AH": "a", "AO": "o", "AW": "aw", "AY": "aj", "EH": "e", "ER": "eʁ", "EY": "ej",
    "IH": "i", "IY": "i", "OW": "o", "OY": "oj", "UH": "u", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "d", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l",
    "M": "m", "N": "n", "NG": "nɡ", "P": "p", "R": "ʁ", "S": "s", "SH": "ʃ", "T": "t", "TH": "t", "V": "v",
    "W": "v", "Y": "j", "Z": "z", "ZH": "ʒ",   # (Hebrew says English w as ו: the voice never learned a w)
}
_LETTERS = [("sh", "ʃ"), ("ch", "tʃ"), ("th", "t"), ("ph", "f"), ("ck", "k"), ("qu", "kw"), ("oo", "u"), ("ee", "i"),
            ("ea", "i"), ("ou", "au"), ("ai", "ej"), ("ay", "ej"), ("x", "ks"), ("c", "k"), ("q", "k"), ("y", "i"),
            ("j", "dʒ"), ("g", "ɡ"), ("r", "ʁ"), ("w", "v")]


def english_ipa(word: str) -> str:
    phones = _parts.get("cmudict", {}).get(word.lower())
    if phones:
        out, stressed = [], False
        for p in phones:
            base, stress = p.rstrip("012"), p[len(p.rstrip("012")):]
            sound = _ARPABET.get(base, "")
            if stress == "1" and not stressed:
                out.append("ˈ")
                stressed = True
            out.append(sound)
        return "".join(out)
    # not in the dictionary: by spelling (names of apps, files...)
    w = re.sub(r"(.)\1", r"\1", word.lower())
    for letters, sound in _LETTERS:
        w = w.replace(letters, sound)
    w = re.sub(r"(?<=[^aeiou])e$", "", w)   # a silent final e
    return re.sub(r"([aeiou])", r"ˈ\1", w, count=1)


# ---------- text -> speech ----------
_PATH = re.compile(r"(?:[A-Za-z]:\\|\\\\)\S*?([^\\/\s]+?)(?=[.,;:!?]?(?:\s|$))|(?:~|\.{1,2})?/(?:[\w.~-]+/)+([\w.~-]+)")
_FILE = re.compile(r"\b([\w-]+)\.(?:py|js|ts|blend|txt|json|csv|md|html|png|jpe?g|wav|mp3|pdf|docx?|xlsx?|zip|exe)\b")
_PREFIX_DASH = re.compile(r"(?<![א-ת])([ובלהמכש])[-־](?=[\dA-Za-z])")


def spoken_form(text: str) -> str:
    """What to actually say: file names rather than whole paths, "ה6" rather than "ה-6" (read as "minus 6"), no
    Markdown or code marks."""
    text = _PATH.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _FILE.sub(lambda m: m.group(1).replace("_", " "), text)   # "hello_world.py" -> "hello world"
    text = _PREFIX_DASH.sub(r"\1", text)
    text = re.sub(r"[`*_#>|]+", " ", text)
    return " ".join(text.split())


def _sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?:;])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def synthesize(text: str, volume: int = 100) -> bytes:
    """The text, said in Hebrew, as WAV bytes (22.05 kHz mono)."""
    import numpy as np
    import phonikud
    with _lock:
        parts = _load()
        config = parts["config"]
        ids_map = config["phoneme_id_map"]
        rate = config["audio"]["sample_rate"]
        inference = config["inference"]
        pieces = []
        for sentence in _sentences(spoken_form(text)):
            vocalized = parts["diacritizer"].add_diacritics(sentence)
            ipa = phonikud.phonemize(vocalized, fallback=english_ipa)
            ids = ids_map["^"] + ids_map["_"]
            for ch in ipa:
                if ch in ids_map:
                    ids += ids_map[ch] + ids_map["_"]
            ids += ids_map["$"]
            if len(ids) < 6:
                continue
            audio = parts["voice"].run(None, {
                "input": np.array([ids], dtype=np.int64),
                "input_lengths": np.array([len(ids)], dtype=np.int64),
                "scales": np.array([NOISE_SCALE, inference["length_scale"], NOISE_W],
                                   dtype=np.float32)})[0].squeeze()
            pieces += [audio, np.zeros(int(rate * PAUSE_SECONDS), dtype=np.float32)]
    samples = np.concatenate(pieces) if pieces else np.zeros(int(rate * 0.1), dtype=np.float32)
    peak = float(np.abs(samples).max()) or 1.0
    samples = samples / peak * 0.9 * max(0, min(100, volume)) / 100
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class Playing:
    """Speech being played (in this process, through winsound): the same shape as a speaking process — poll(),
    terminate(), wait(), kill() — so speak() can wait for it and cut it off. Played from a file, asynchronously:
    Windows can't stop a sound played synchronously from memory until it ends."""

    TAIL = 0.15   # the sound device finishes a little after the samples run out

    def __init__(self, wav: bytes):
        self.returncode = None
        with wave.open(io.BytesIO(wav)) as w:
            self.duration = w.getnframes() / w.getframerate()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._play, args=(wav,), daemon=True, name="hebrew-voice")
        self._thread.start()

    def _play(self, wav: bytes) -> None:
        path = None
        try:
            import tempfile
            import winsound
            with tempfile.NamedTemporaryFile(prefix="jervis-voice-", suffix=".wav", delete=False) as f:
                f.write(wav)
                path = f.name
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            if self._stop.wait(self.duration + self.TAIL):
                winsound.PlaySound(None, 0)   # cut off; only now, so a finished sound never stops the next one
        except Exception as e:
            print(f"Couldn't play the Hebrew voice: {e}", flush=True)
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
            self.returncode = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self._stop.set()

    kill = terminate

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            import subprocess
            raise subprocess.TimeoutExpired("hebrew-voice", timeout)
        return self.returncode


def speak(text: str, volume: int = 100, out_path: str = None):
    """Start saying `text`; returns a Playing (or None after writing to out_path, for tests)."""
    started = time.time()
    wav = synthesize(text, volume)
    if out_path:
        with open(out_path, "wb") as f:
            f.write(wav)
        return None
    print(f"Hebrew voice: {time.time() - started:.2f}s to prepare", flush=True)
    return Playing(wav)
