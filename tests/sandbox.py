"""Run Jervis's command handling without letting it touch the computer.

Every way Jervis acts on the machine (starting programs, AppleScript, PowerShell, opening web pages, notifications,
network calls) is replaced by a recorder, so a test can check what Jervis *would* have done, and a sentence that
wrongly triggers a command shows up as a recorded action instead of opening an app on the developer's computer.
"""
import os
import subprocess
import sys
import tempfile
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("JERVIS_DATA_DIR", tempfile.mkdtemp(prefix="jervis-test-"))
os.environ.setdefault("JERVIS_AUDIO", "off")
os.environ["GROQ_API_KEY"] = ""           # tests never call an online AI
os.environ["SPOTIFY_CLIENT_ID"] = ""      # nor Spotify
os.environ["LLM_BACKEND"] = "ollama"

actions = []   # what Jervis tried to do, as short strings


class _FakeProcess:
    returncode = 0
    pid = 0
    stdout = ""
    stderr = ""

    def __init__(self, *args, **kwargs):
        actions.append(f"run {_describe(args[0] if args else kwargs.get('args'))}")

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def communicate(self, *args, **kwargs):
        return ("", "")

    def terminate(self):
        pass

    def kill(self):
        pass


def _describe(cmd) -> str:
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(c) for c in cmd)[:160]
    return str(cmd)[:160]


def _fake_run(*args, **kwargs):
    actions.append(f"run {_describe(args[0] if args else kwargs.get('args'))}")
    return subprocess.CompletedProcess(args[0] if args else [], 0, "", "")


def _fake_call(*args, **kwargs):
    actions.append(f"run {_describe(args[0] if args else kwargs.get('args'))}")
    return 0


def _fake_open(url, *args, **kwargs):
    actions.append(f"open {url}")
    return True


class _FakeResponse:
    status_code = 200
    ok = True
    text = ""
    content = b""

    def json(self):
        return {}

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(())

    def iter_content(self, *a, **k):
        return iter(())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_http(method):
    def call(url, *args, **kwargs):
        actions.append(f"http {method} {str(url)[:100]}")
        return _FakeResponse()
    return call


_saved = []


def install() -> None:
    """Replace every way of acting on the computer with a recorder. Call before importing app; uninstall() after."""
    import requests
    if not _saved:
        _saved.append([(subprocess, n, getattr(subprocess, n)) for n in ("Popen", "run", "call", "check_output")]
                      + [(webbrowser, n, getattr(webbrowser, n)) for n in ("open", "open_new_tab")]
                      + [(requests, n, getattr(requests, n)) for n in ("get", "post", "put", "delete", "head")]
                      + [(requests.Session, "request", requests.Session.request)]
                      + ([(os, "startfile", os.startfile)] if hasattr(os, "startfile") else []))
    subprocess.Popen = _FakeProcess
    subprocess.run = _fake_run
    subprocess.call = _fake_call
    subprocess.check_output = lambda *a, **k: (actions.append(f"run {_describe(a[0] if a else '')}") or b"")
    webbrowser.open = _fake_open
    webbrowser.open_new_tab = _fake_open
    if hasattr(os, "startfile"):
        os.startfile = lambda path, *a, **k: actions.append(f"open {path}")
    import requests
    for method in ("get", "post", "put", "delete", "head"):
        setattr(requests, method, _fake_http(method))
    requests.Session.request = lambda self, method, url, *a, **k: _fake_http(method.lower())(url)


def uninstall() -> None:
    """Put the real functions back (so later tests in the same run can use the network, start programs...)."""
    if _saved:
        for owner, name, original in _saved.pop():
            setattr(owner, name, original)


def reset() -> None:
    actions.clear()
