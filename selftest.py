"""`jervis-backend --selftest`: check that an installed copy has every part it needs.

Needs no microphone, no network and no permissions, so it runs on a build machine right after installing: a missing
package, a native library that doesn't load, or a data file left out of the bundle fails here instead of on a user's
computer. Prints one line starting with SELFTEST and a JSON report; the exit code is 0 only if everything required is
there. Reached through app.py, so importing all of Jervis's own modules has already succeeded by the time this runs.
"""
import importlib
import json
import os
import sys
import tempfile

REQUIRED = ["websockets", "requests", "groq", "speech_recognition", "pyaudio", "psutil", "spotipy", "PIL", "numpy",
            "faster_whisper", "ctranslate2", "onnxruntime", "av", "mss", "dotenv",
            "computer_use", "screen_vision", "stt_local", "local_ai", "local_llm", "settings", "paths", "language",
            "nlu", "hebrew_voice", "phonikud", "phonikud_onnx"]
# Read with paths.resource(): an installed engine without one of them fails only when that feature is used (a
# missing phone page once broke every phone connection), so the self-test checks each is really there.
BUNDLED_FILES = ["phone_client.html", "phone_sw.js", "confirm.html", "blender_bridge.py", "blender_kit.py",
                 "blender_assets.py"]
PLATFORM = {
    "win32": ["uiautomation", "comtypes", "pycaw", "screen_windows", "winctl"],
    "darwin": ["Quartz", "AppKit", "ApplicationServices", "screen_mac"],
}
OPTIONAL = ["googleapiclient", "google_auth_oauthlib", "openai"]   # features that also need the user's own keys


def _check(results: dict, name: str, test) -> bool:
    try:
        detail = test()
        results[name] = detail or "ok"
        return True
    except Exception as e:   # noqa: BLE001 - every failure is a finding, whatever its type
        results[name] = f"FAILED: {type(e).__name__}: {e}"[:300]
        return False


def run() -> int:
    results, ok = {}, True
    for name in REQUIRED + PLATFORM.get(sys.platform, []) + OPTIONAL:
        passed = _check(results, name, lambda n=name: importlib.import_module(n) and None)
        ok = ok and (passed or name in OPTIONAL)

    def bundled_files():   # files the engine reads from its own folder (pages for the phone, Blender scripts)
        import paths
        missing = [name for name in BUNDLED_FILES if not os.path.isfile(paths.resource(name))]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        return f"ok ({len(BUNDLED_FILES)} files)"
    ok = _check(results, "bundled_files", bundled_files) and ok

    def flac():
        import speech_recognition as sr
        return f"ok ({os.path.basename(sr.get_flac_converter())})"

    def whisper_runtime():
        import ctranslate2
        import faster_whisper
        assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
        if not any(f.endswith(".onnx") for f in os.listdir(assets)):
            raise FileNotFoundError("the voice-activity model is missing from faster_whisper/assets")
        return f"ok (cpu: {', '.join(sorted(ctranslate2.get_supported_compute_types('cpu')))})"

    def audio_library():
        import pyaudio
        audio = pyaudio.PyAudio()
        try:
            return f"ok ({audio.get_device_count()} audio devices)"
        finally:
            audio.terminate()

    def data_folder():
        import paths
        import settings
        probe = os.path.join(paths.DATA_DIR, ".selftest")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        settings.update({"WEATHER_CITY": settings.get("WEATHER_CITY") or "London"})
        return f"ok ({paths.DATA_DIR})"

    def local_ai_download():
        import local_ai
        name, size, _sha = local_ai.LocalAI(report=lambda state: None)._asset()
        return f"ok ({name}, {size // 1_000_000} MB)"

    for name, test in (("flac", flac), ("whisper_runtime", whisper_runtime), ("audio_library", audio_library),
                       ("data_folder", data_folder), ("local_ai_download", local_ai_download)):
        ok = _check(results, name, test) and ok

    # Informational only: a build machine has no accessibility permission, and that's fine.
    try:
        if sys.platform == "win32":
            import screen_windows
            ready, why = screen_windows.WindowsScreen().available()
        elif sys.platform == "darwin":   # checked without showing macOS's permission prompt
            import screen_mac
            ready, why = screen_mac.MacScreen.trusted(), "no Accessibility permission yet"
        else:
            ready, why = False, "not supported on this system"
        results["computer_control"] = "ok" if ready else f"not ready: {why}"
    except Exception as e:  # noqa: BLE001
        results["computer_control"] = f"not ready: {e}"

    def speech_engine():   # which speech models this computer would use (the GPU needs Ollama's CUDA libraries)
        import stt_local
        return f"{'/'.join(stt_local.plan())} ({'GPU' if stt_local.gpu_possible() else 'CPU'})"
    _check(results, "speech_engine", speech_engine)

    if "--speech" in sys.argv:   # also download the speech model and run it (needs the internet, ~150 MB)
        def speech():
            import io
            import time
            import wave
            import paths
            import stt_local
            stt_local.ensure_model()
            clip = io.BytesIO()
            with wave.open(clip, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 16000)
            started = time.time()
            heard = stt_local.transcribe_full(clip.getvalue())
            return f"ok ({heard.engine or stt_local.engine_summary()}, models in {paths.models_dir()}, "                    f"ran in {time.time() - started:.1f}s)"
        ok = _check(results, "offline_speech", speech) and ok

        def hebrew_voice():   # the natural Hebrew voice really speaks (its tables and models are all packaged)
            import time
            import hebrew_voice as voice
            if not voice.available():
                return "not downloaded (Windows' Hebrew voice speaks instead)"
            started = time.time()
            wav = voice.synthesize("שלום, פתחתי את Blender ב-14:32.")
            return f"ok ({len(wav) // 44100:.0f}s of speech in {time.time() - started:.1f}s)"
        ok = _check(results, "hebrew_voice_speaks", hebrew_voice) and ok

    results["python"] = sys.version.split()[0]
    results["frozen"] = bool(getattr(sys, "frozen", False))
    print("SELFTEST " + json.dumps({"ok": ok, "checks": results}), flush=True)   # ASCII: any console can show it
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("JERVIS_DATA_DIR", tempfile.mkdtemp(prefix="jervis-selftest-"))
    sys.exit(run())
