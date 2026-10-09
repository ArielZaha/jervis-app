"""Every use of the audio system (PortAudio, through PyAudio) goes through here, one at a time.

PortAudio's start-up and shut-down (Pa_Initialize / Pa_Terminate, i.e. pyaudio.PyAudio() and .terminate()) are not
thread-safe: two threads doing them at once crash the whole process with an access violation, before Python can
raise anything. Jervis did exactly that on every start — the Settings device list was gathered on one thread while
the listening loop opened the microphone on another — and the window could only report that the engine "keeps
stopping". speech_recognition's Microphone creates its own PyAudio instances (in __init__, __enter__ and __exit__),
so it is wrapped too.

Holding the lock only around start-up/shut-down (not while recording) is enough: once PortAudio is up, another
instance's start-up only bumps its reference count, and reading device info while a stream records is safe.
"""
import threading

import speech_recognition as sr

LOCK = threading.RLock()


def input_device_names() -> list:
    """Names of the input devices, in PyAudio's order, without duplicates."""
    import pyaudio
    names = []
    with LOCK:
        audio = pyaudio.PyAudio()
        try:
            for i in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(i)
                if int(info.get("maxInputChannels", 0)) > 0 and info.get("name") not in names:
                    names.append(info.get("name"))
        finally:
            audio.terminate()
    return names


def input_device_index(name: str):
    """PyAudio's index of the input device with this name, or None if it isn't connected."""
    import pyaudio
    with LOCK:
        audio = pyaudio.PyAudio()
        try:
            for i in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(i)
                if info.get("name") == name and int(info.get("maxInputChannels", 0)) > 0:
                    return i
        finally:
            audio.terminate()
    return None


class Microphone(sr.Microphone):
    """speech_recognition's Microphone, with its PortAudio start-up and shut-down serialized."""

    def __init__(self, *args, **kwargs):
        with LOCK:
            super().__init__(*args, **kwargs)

    def __enter__(self):
        with LOCK:
            return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        with LOCK:
            return super().__exit__(exc_type, exc_value, traceback)
