"""Hebrew with the real models: Whisper (turbo + ivrit.ai), DictaLM through Ollama, and Windows' Hebrew voice saying
the test sentences. Run with JERVIS_REAL_LANGUAGE=1 (and JERVIS_REAL_MODELS: a data folder whose models/whisper holds
the speech models). Kept apart from test_language.py, whose app tests run in a sandbox without network access.
The letters name the cases the Hebrew support was specified with (see test_language.py).
"""
import os
import wave

import pytest

import language
import local_llm
import nlu
import stt_local

REAL = os.getenv("JERVIS_REAL_LANGUAGE") == "1"
real = pytest.mark.skipif(not REAL, reason="real models: set JERVIS_REAL_LANGUAGE=1")

@pytest.fixture(scope="module")
def real_models():
    if not REAL:
        pytest.skip("real models: set JERVIS_REAL_LANGUAGE=1")
    if language.translator() != local_llm.DICTALM:
        pytest.skip("DictaLM isn't installed in Ollama")
    language._cache.clear()
    folder = os.getenv("JERVIS_REAL_MODELS")
    if folder:   # its models folder also has the English dictionary the translation checks use
        import paths
        original, paths.DATA_DIR = paths.DATA_DIR, folder
        yield
        paths.DATA_DIR = original
    else:
        yield


def _contains(text, *words):
    low = text.lower()
    return all(w.lower() in low for w in words)


@real
@pytest.mark.parametrize("said, previous, words", [
    ("תפתח את בלנדר", "", ["open", "blender"]),                                                  # B
    ("תיצור לי בית מפורט", "", ["create", "detailed", "house"]),                                 # H
    ("תעשה את הגג אדום", "Create a detailed house", ["roof", "red"]),                            # D
    ("לא, התכוונתי לחלונות", "Make the roof red", ["no", "meant", "windows"]),                  # E
    ("לא התכוונתי לחלונות", "Make the roof red", ["no", "meant", "windows"]),                   # E, comma lost
    ("תשמור את הפרויקט", "Make the windows red", ["save", "project"]),                          # J
    ("תפתח Blender ותיצור detailed house", "", ["open", "blender", "create", "detailed house"]),  # C, K
    ("תעשה את ה-roof אדום", "", ["roof", "red"]),                                               # C
    ("לא, התכוונתי ל-windows", "Make the roof red", ["no", "meant", "windows"]),                # C, E
    ("צור לי תוכנית Python שמדפיסה Hello World", "", ["python", "program", "hello world"]),      # I
    ("שים את זה ליד הבית", "", ["it", "next to the house"]),                                    # F
    ("תריץ את test_app.py ותגיד לי מה יצא", "", ["run", "test_app.py"]),                        # G
    ("תסובב את הבית תשעים מעלות", "", ["rotate", "house", "90"]),
    ("תיצור אי טרופי עם עצי דקל ותשמור אותו", "", ["tropical island", "palm", "save"]),        # K
    ("אל תמחק את הקובץ", "", ["don't", "delete", "file"]),
])
def test_real_translations(real_models, said, previous, words):
    heard = language.to_english(said, previous)
    assert heard.status == "ok", heard.log_line()
    assert _contains(heard.english, *words), heard.log_line()


@real
def test_real_gibberish_is_not_acted_on(real_models):
    assert language.to_english("פלורגנים מנוגבים בקרזל").status in ("unclear", "confirm")


@real
def test_real_replies_in_hebrew(real_models):
    out = language.to_user_language(r"Done — saved to C:\Users\me\Documents\jervis_scene.blend.", "he")
    assert nlu.has_hebrew(out) and r"C:\Users\me\Documents\jervis_scene.blend" in out
    out = language.to_user_language("Done — I wrote hello_world.py (3 lines). It printed: `Hello World`.", "he")
    assert nlu.has_hebrew(out) and "hello_world.py" in out and "`Hello World`" in out


def _hebrew_voice_says(text: str, folder) -> bytes:
    """Windows' Hebrew voice (Asaf) says `text`; returned as 16 kHz 16-bit mono WAV, like Jervis records."""
    import osal
    import speech_recognition as sr
    path = str(folder / "said.wav")
    os.environ["JERVIS_SPEECH_OUT"] = path
    # Windows' voice says the test sentences: it says them the same way every time (the neural voice varies a
    # little from one rendering to the next — measured on its own in the Hebrew voice report), and what's tested
    # here is hearing and understanding them.
    os.environ["JERVIS_HEBREW_VOICE"] = "windows"
    try:
        osal.speech_process(text, 100).wait(timeout=60)
    finally:
        os.environ.pop("JERVIS_SPEECH_OUT", None)
        os.environ.pop("JERVIS_HEBREW_VOICE", None)
    with wave.open(path) as w:
        audio = sr.AudioData(w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth())
    return audio.get_wav_data(convert_rate=16000, convert_width=2)


@pytest.fixture(scope="module")
def real_speech(real_models):
    folder = os.getenv("JERVIS_REAL_MODELS")
    if not folder:
        pytest.skip("JERVIS_REAL_MODELS: a data folder with models/whisper")
    import paths
    original = paths.DATA_DIR
    paths.DATA_DIR = folder
    if not stt_local.model_ready():
        paths.DATA_DIR = original
        pytest.skip("the speech models aren't in JERVIS_REAL_MODELS")
    yield
    paths.DATA_DIR = original


@real
@pytest.mark.parametrize("said, language_, words", [
    ("תפתח את בלנדר", "he", ["open", "blender"]),
    ("תיצור לי בית מפורט", "he", ["create", "detailed", "house"]),
    ("תשמור את הפרויקט", "he", ["save", "project"]),
    ("תסובב את הבית תשעים מעלות", "he", ["rotate", "house", "90"]),
])
def test_real_speech_to_english(real_speech, tmp_path, said, language_, words):
    heard = stt_local.transcribe_full(_hebrew_voice_says(said, tmp_path))
    assert heard.language == language_, heard
    english = language.to_english(heard.text).english
    assert _contains(english, *words), (heard.text, english)


@real
def test_real_hebrew_voice_is_understood(real_speech):
    """The natural Hebrew voice, heard back: Jervis's usual replies come through (measured average 3.3%)."""
    import io
    import re
    from difflib import SequenceMatcher
    import hebrew_voice
    from faster_whisper import decode_audio
    if not hebrew_voice.available():
        pytest.skip("the Hebrew voice isn't downloaded in JERVIS_REAL_MODELS")
    said = ["סיימתי, פתחתי את התוכנה.", "הגג אדום עכשיו.", "שמרתי את הפרויקט בתיקיית המסמכים.",
            "סליחה, לא הבנתי. תוכל להגיד את זה שוב?", "אני מצוין, תודה ששאלת! במה אוכל לעזור?"]
    norm = lambda t: re.sub(r"[^\u05d0-\u05ea]", "", t)   # noqa: E731
    errors = total = 0
    with stt_local._lock:
        model = stt_local._get(stt_local.HEBREW_MODEL, stt_local.setup().device)
    for text in said:
        segments, _ = model.transcribe(decode_audio(io.BytesIO(hebrew_voice.synthesize(text))), language="he",
                                       beam_size=5)
        heard = " ".join(s.text for s in segments)
        ref, got = norm(text), norm(heard)
        errors += round((1 - SequenceMatcher(None, ref, got).ratio()) * len(ref))
        total += len(ref)
    assert errors / total < 0.10, f"{100 * errors / total:.1f}% of the letters heard wrong"
