"""A tiny, dependency-free error bus: any module can report something going wrong without needing to know how (or
whether) it ends up on screen — app.py is the only module with an actual window to show it in, and subscribes here
once at startup. Every report is also printed exactly as a bare print(...) always was, so reading the log file
still works the same as before for anyone who prefers that.

Exists separately from app.py (rather than living there) because most of the modules that need to report an error
— local_ai.py, push.py, phone_control.py, images.py, screen_mac.py, and the rest — are imported BY app.py, so they
can't import it back without a cycle. This module has no imports of its own, so anything can depend on it.
"""
import threading

_lock = threading.Lock()
_subscribers = []


def subscribe(callback) -> None:
    """callback(context: str, message: str) -> None, called for every report() made from here on."""
    with _lock:
        _subscribers.append(callback)


def report(context: str, exc: Exception = None, detail: str = None) -> None:
    """Something went wrong: `context` is a short label for where, `exc` the exception if there is one, `detail`
    an override message when the exception text alone wouldn't mean anything to a non-technical reader."""
    message = detail or (f"{type(exc).__name__}: {exc}" if exc is not None else "")
    print(f"[{context}] {message}" if message else f"[{context}]", flush=True)
    with _lock:
        subscribers = list(_subscribers)
    for callback in subscribers:
        try:
            callback(context, message)
        except Exception:
            pass   # a broken subscriber must never turn one error into two
