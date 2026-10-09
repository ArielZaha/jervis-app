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

# ---- a fake Spotify app: what its search shows, what its player plays ----
spotify_catalogue = {}   # normalized search -> [{"uri", "kind", "title", "artists"}], in Spotify's order
spotify_player = {"playing": False, "title": "", "artist": ""}
spotify_refuses = set()   # URIs whose Play button "does nothing" (to test a failed start)


def spotify_results(query: str) -> list:
    import spotify_match
    return spotify_catalogue.get(spotify_match.normalize(query), [])


def _fake_ui_search(query, wait=12.0):
    actions.append(f"spotify search page {query}")
    return [dict(r, position=i, query=query, button=("play", r["uri"])) for i, r in enumerate(spotify_results(query))]


def _fake_press(button):
    actions.append(f"spotify press play {button[1]}")
    if button[1] in spotify_refuses:
        return True
    for results in spotify_catalogue.values():
        for r in results:
            if r["uri"] == button[1]:
                title = r["title"] if r["kind"] != "artist" else "Their Top Song"
                artist = ", ".join(r["artists"]) if r["kind"] != "artist" else r["title"]
                spotify_player.update(playing=True, title=title, artist=artist)
                return True
    return False


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
    # Driving the Spotify app (bringing it forward, key presses, AppleScript) doesn't go through subprocess alone
    import spotify_local
    _saved[0].extend((spotify_local, n, getattr(spotify_local, n))
                     for n in ("_mac_bring_forward", "_win_bring_forward", "_mac_keys", "_mac_type", "_osa", "running",
                               "installed", "_mac_can_press_keys", "_mac_ask_for_accessibility", "open_search", "_glide", "cursor",
                               "_window_bounds", "ui_available", "ui_search", "_press", "ui_now_playing"))
    # Spotify's results and player, faked: a test fills spotify_catalogue {search: [results]} (see spotify_results)
    spotify_local.ui_available = lambda: True
    spotify_local.ui_search = _fake_ui_search
    spotify_local._press = _fake_press
    spotify_local.ui_now_playing = lambda: dict(spotify_player)
    spotify_local._mac_bring_forward = spotify_local._win_bring_forward = lambda: actions.append("spotify front") or True
    spotify_local._mac_keys = lambda *keys: actions.append("spotify keys " + "+".join(keys))
    spotify_local._mac_type = lambda text: actions.append(f"spotify type {text}")
    spotify_local._osa = lambda command, timeout=8.0: actions.append(f"spotify {command}") or ""
    spotify_local.running = lambda: False
    spotify_local.installed = lambda: True
    spotify_local._mac_can_press_keys = lambda: True
    spotify_local._mac_ask_for_accessibility = lambda: actions.append("ask for accessibility")
    spotify_local.open_search = lambda query: actions.append(f"spotify search {query}") or True
    spotify_local._glide = lambda x, y, seconds=0.6: actions.append(f"pointer to {x},{y}")
    spotify_local.cursor = lambda: None
    spotify_local._window_bounds = lambda: (0, 0, 1200, 800)
    # Windows key presses, clicks and window switching go straight to the system, not through subprocess
    import winctl
    if winctl.IS_WIN:
        _saved[0].extend((winctl, n, getattr(winctl, n)) for n in ("_send", "focus", "list_windows", "close_window",
                                                                   "press", "type_text"))
        winctl._send = lambda events, strict=False: actions.append(f"input {len(events)} events")
        # readable, like the macOS recordings: "keys ctrl+k", "type Jane!"
        winctl.press = lambda *names, strict=False: actions.append("keys " + "+".join(names))
        winctl.type_text = lambda text, strict=False: actions.append(f"type {text}")
        winctl.focus = lambda hwnd: actions.append(f"focus window {hwnd}") or True
        winctl.list_windows = lambda: []   # the developer's real windows must not count as "already open"
        winctl.close_window = lambda hwnd: actions.append(f"close window {hwnd}") or True
    import app_launcher
    _saved[0].append((app_launcher, "LAUNCH_CONFIRM_SECONDS", app_launcher.LAUNCH_CONFIRM_SECONDS))
    app_launcher.LAUNCH_CONFIRM_SECONDS = 0   # nothing really starts, so there is no window to wait for


def uninstall() -> None:
    """Put the real functions back (so later tests in the same run can use the network, start programs...)."""
    if _saved:
        for owner, name, original in _saved.pop():
            setattr(owner, name, original)


def reset() -> None:
    actions.clear()
    spotify_catalogue.clear()
    spotify_refuses.clear()
    spotify_player.update(playing=False, title="", artist="")
