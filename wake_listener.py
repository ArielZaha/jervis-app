#!/usr/bin/env python3
import os
import subprocess
import sys
import time

import osal  # macOS: makes every program launch fork-free

import speech_recognition as sr

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(APP_DIR, "app.py")

WAKE_PHRASES = [
    "wake up jervis",
    "wake up jarvis",
    "hey jervis",
    "ok jervis",
    "okay jervis",
]

LISTENER_START_DELAY = 2
RESTART_GUARD_SECONDS = 20


def normalize(text):
    return " ".join(text.lower().strip().split())


def is_wake_phrase(text):
    text = normalize(text)
    return any(phrase in text for phrase in WAKE_PHRASES)


def app_is_running():
    """True if app.py is already running (psutil works the same on macOS and Windows)."""
    try:
        import psutil
        me = os.getpid()
        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = proc.info.get("cmdline") or []
            if proc.info["pid"] != me and any(os.path.abspath(part) == APP_PATH for part in cmd if part.endswith("app.py")):
                return True
        return False
    except Exception:
        return False


def start_jervis():
    if not os.path.exists(APP_PATH):
        print(f"ERROR: app.py not found: {APP_PATH}", flush=True)
        return False

    if app_is_running():
        print("Jervis is already running.", flush=True)
        return True

    print("Wake phrase detected. Starting Jervis...", flush=True)

    try:
        detach = (
            {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}  # detached, own process group, no console window
            if sys.platform == "win32" else {}  # macOS: no start_new_session, it would force an unsafe fork
        )
        subprocess.Popen(
            [sys.executable, APP_PATH],
            cwd=APP_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detach,
        )
        return True
    except Exception as e:
        print(f"ERROR starting Jervis: {e}", flush=True)
        return False


def main():
    time.sleep(LISTENER_START_DELAY)

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.energy_threshold = 300
    recognizer.pause_threshold = 0.8
    recognizer.phrase_threshold = 0.2
    recognizer.non_speaking_duration = 0.3

    with sr.Microphone() as microphone:
        print("Jervis Wake Listener is running.", flush=True)
        print('Say "Wake Up Jervis" to start Jervis.', flush=True)

        try:
            recognizer.adjust_for_ambient_noise(microphone, duration=0.8)
        except Exception as e:
            print(f"Microphone calibration warning: {e}", flush=True)

        while True:
            # If Jervis is already running, this listener must stay out of
            # the way so the two processes never compete for the microphone.
            if app_is_running():
                print("Jervis is running. Wake Listener will wait.", flush=True)
                time.sleep(5)
                continue

            try:
                audio = recognizer.listen(
                    microphone,
                    timeout=8,
                    phrase_time_limit=4,
                )
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                print(f"Listen error: {e}", flush=True)
                time.sleep(1)
                continue

            try:
                text = normalize(recognizer.recognize_google(audio, language="en-US"))
                print(f"Heard: {text}", flush=True)

                if is_wake_phrase(text):
                    if start_jervis():
                        # Give app.py time to take ownership of the microphone.
                        time.sleep(RESTART_GUARD_SECONDS)
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                print(f"Speech recognition service error: {e}", flush=True)
                time.sleep(3)
            except Exception as e:
                print(f"Recognition error: {e}", flush=True)
                time.sleep(1)


if __name__ == "__main__":
    main()
