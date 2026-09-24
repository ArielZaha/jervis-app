"""Where Jervis finds his own files, and where he writes.

Two kinds of places:
  - RESOURCE_DIR: the code and bundled files. In an installed copy this is inside the program folder, which is
    read-only (C:\\Program Files, /Applications), so Jervis must never write there.
  - DATA_DIR: everything Jervis writes (settings, transcripts, logs, pictures, documents, caches, sign-in tokens,
    downloaded AI models). One folder per user.

Running from source (python run.py) keeps working exactly as before: DATA_DIR is the project folder itself, so
transcripts/, logs/ and images/ stay where they always were. The installed app passes JERVIS_DATA_DIR (Electron's
per-user folder); a frozen backend started any other way falls back to the usual per-user location.
"""
import os
import platform
import sys

FROZEN = bool(getattr(sys, "frozen", False))  # running from the packaged backend (PyInstaller), not from source


def _resource_dir() -> str:
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _default_data_dir() -> str:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    elif system == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "Jervis")


def _data_dir() -> str:
    explicit = os.environ.get("JERVIS_DATA_DIR")
    if explicit:
        return os.path.abspath(explicit)
    return _default_data_dir() if FROZEN else RESOURCE_DIR


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()


def resource(*parts: str) -> str:
    """A bundled, read-only file (e.g. a script Jervis starts, a list shipped with the app)."""
    return os.path.join(RESOURCE_DIR, *parts)


def data(*parts: str) -> str:
    """A file or folder Jervis writes. Its parent folder is created on first use."""
    path = os.path.join(DATA_DIR, *parts)
    os.makedirs(os.path.dirname(path) or DATA_DIR, exist_ok=True)
    return path


def data_dir(*parts: str) -> str:
    """A folder Jervis writes into, created if missing."""
    path = os.path.join(DATA_DIR, *parts)
    os.makedirs(path, exist_ok=True)
    return path


# The folders every part of Jervis agrees on.
def transcripts_dir() -> str:
    return data_dir("transcripts")


def logs_dir() -> str:
    return data_dir("logs")


def models_dir() -> str:
    """Downloaded AI models (speech recognition, and the local AI when Jervis runs it himself)."""
    return data_dir("models")
