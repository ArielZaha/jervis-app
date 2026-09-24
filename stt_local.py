"""Speech recognition on this computer (faster-whisper): no account, no key, and it works without internet.

The online recognizers (Whisper on Groq, Google's free one) stay available: with a Groq key Jervis still prefers
Groq's larger, faster Whisper, and Google's recognizer is the backup when this model isn't downloaded yet.
The model (about 150 MB) is downloaded once during first-run setup, into the data folder.
"""
import os
import threading

import paths

# The model comes from Hugging Face; keep its download quiet in Jervis's log (no progress bars, no account nagging).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

MODEL = os.getenv("JERVIS_STT_MODEL", "base.en")   # English, like the rest of Jervis's speech handling
REPO = {"tiny.en": "Systran/faster-whisper-tiny.en", "base.en": "Systran/faster-whisper-base.en",
        "small.en": "Systran/faster-whisper-small.en"}
_model = None
_lock = threading.Lock()


def available() -> bool:
    """Whether the faster-whisper package is installed (it ships with the installed app)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:   # ImportError, or a broken native library
        return False


def _model_dir() -> str:
    return os.path.join(paths.models_dir(), "whisper", MODEL)


def model_ready() -> bool:
    return os.path.exists(os.path.join(_model_dir(), "model.bin"))


def ensure_model(progress=None) -> str:
    """Download the model if it isn't here yet. progress(detail, fraction) is called along the way."""
    target = _model_dir()
    if model_ready():
        return target
    from huggingface_hub import snapshot_download
    if progress:
        progress("Downloading the speech model (about 150 MB)…", None)
    snapshot_download(repo_id=REPO.get(MODEL, f"Systran/faster-whisper-{MODEL}"), local_dir=target,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*",
                                      "preprocessor_config.json"])
    if not model_ready():
        raise RuntimeError("the speech model download is incomplete")
    return target


def _load():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            threads = max(1, min(4, (os.cpu_count() or 2) // 2))
            _model = WhisperModel(_model_dir(), device="cpu", compute_type="int8", cpu_threads=threads)
    return _model


def transcribe(wav_bytes: bytes) -> str:
    """Text of a short WAV recording (16 kHz mono, as Jervis records it)."""
    import io
    import wave

    import numpy as np
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        frames = wav.readframes(wav.getnframes())
        width = wav.getsampwidth()
    if width != 2:
        raise ValueError("expected 16-bit audio")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = _load().transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                         condition_on_previous_text=False)
    return " ".join(segment.text.strip() for segment in segments).strip()


def ready() -> bool:
    return available() and model_ready()
