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
            "computer_use", "screen_vision", "stt_local", "local_ai", "local_llm", "settings", "paths"]
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
            stt_local.transcribe(clip.getvalue())
            return f"ok (model in {paths.models_dir()}, ran in {time.time() - started:.1f}s)"
        ok = _check(results, "offline_speech", speech) and ok

    results["python"] = sys.version.split()[0]
    results["frozen"] = bool(getattr(sys, "frozen", False))
    print("SELFTEST " + json.dumps({"ok": ok, "checks": results}), flush=True)   # ASCII: any console can show it
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("JERVIS_DATA_DIR", tempfile.mkdtemp(prefix="jervis-selftest-"))
    sys.exit(run())
