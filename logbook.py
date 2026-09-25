"""Jervis's diagnostic log: logs/jervis.log in the data folder, kept to a few MB.

Jervis reports what he is doing with print() all over the code. Rather than rewrite hundreds of lines, install()
copies everything printed to the console into the log file as well, with a timestamp. What the user said or what
Jervis answered is never written to the log (those lines are replaced by a placeholder): conversation text belongs in
the transcripts, which the user can switch off, not in a diagnostic file that may be shared to report a problem.
"""
import os
import re
import sys
import threading
import time

import paths

MAX_BYTES = 2 * 1024 * 1024
KEEP = 3  # jervis.log plus jervis.log.1 .. .3

# Console lines that carry what was said. Only their label reaches the log.
_PRIVATE = re.compile(r"^(\s*)(Recognized|Speaking|Typed|Heard|You said|Transcript|User|Jervis says|Reply)\s*:\s*.+$",
                      re.IGNORECASE)
_lock = threading.Lock()
_log_file = None
_log_path = None


def log_path() -> str:
    return os.path.join(paths.logs_dir(), "jervis.log")


def redact(line: str) -> str:
    return _PRIVATE.sub(lambda m: f"{m.group(1)}{m.group(2)}: [not logged]", line)


def _rotate_if_needed() -> None:
    global _log_file
    try:
        if _log_file is None or os.path.getsize(_log_path) < MAX_BYTES:
            return
    except OSError:
        return
    _log_file.close()
    for i in range(KEEP, 0, -1):
        older, newer = f"{_log_path}.{i}", (_log_path if i == 1 else f"{_log_path}.{i - 1}")
        if os.path.exists(newer):
            try:
                os.replace(newer, older)
            except OSError:
                pass
    _log_file = open(_log_path, "a", encoding="utf-8")


def write(text: str) -> None:
    """Add lines to the log (already-complete lines; used by the console tee and by log())."""
    if _log_file is None:
        return
    with _lock:
        try:
            _rotate_if_needed()
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            for line in text.splitlines():
                if line.strip():
                    _log_file.write(f"{stamp}  {redact(line)}\n")
            _log_file.flush()
        except (OSError, ValueError):
            pass


def log(message: str) -> None:
    """Write straight to the log without printing (for details that would only clutter the console)."""
    write(message)


class _Tee:
    """Stands in for sys.stdout / sys.stderr: the console gets everything as before, the log gets whole lines."""

    def __init__(self, stream):
        self._stream = stream
        self._buffer = ""

    def write(self, text):
        if self._stream is not None:
            try:
                self._stream.write(text)
            except UnicodeEncodeError:   # a console that can't show some letters (e.g. Hebrew): escape them
                encoding = getattr(self._stream, "encoding", None) or "ascii"
                try:
                    self._stream.write(text.encode(encoding, "backslashreplace").decode(encoding))
                except (OSError, ValueError, LookupError, UnicodeError):
                    pass
            except (OSError, ValueError):
                pass
        self._buffer += text
        if "\n" in self._buffer:
            complete, self._buffer = self._buffer.rsplit("\n", 1)
            write(complete)
        return len(text)

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return bool(self._stream is not None and getattr(self._stream, "isatty", lambda: False)())

    def fileno(self):
        return self._stream.fileno()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")


def install() -> str:
    """Start logging. Safe to call more than once. Returns the log file's path."""
    global _log_file, _log_path
    if _log_file is not None:
        return _log_path
    _log_path = log_path()
    try:
        _log_file = open(_log_path, "a", encoding="utf-8")
    except OSError:
        return _log_path   # no log (read-only disk?): Jervis still runs, just without the file
    write(f"===== Jervis backend starting (pid {os.getpid()}, data folder {paths.DATA_DIR}) =====")
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    return _log_path
