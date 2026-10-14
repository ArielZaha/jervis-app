"""The phone app's graphs, globe and planets: the same fixed list of files is served by Jarvis, Jarvis Wake and the
relay; nothing outside it is; and the window's pictures reach the phone, opening there when the phone asked."""
import importlib.util
import os

import pytest

import phone_visuals
import sandbox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_listed_file_exists():
    for _, (name, _, _) in phone_visuals.files().items():
        assert os.path.isfile(os.path.join(ROOT, name)), name


def test_jarvis_wake_and_the_relay_serve_the_same_list():
    wake = _load("wake/jarvis_wake.py", "jarvis_wake_for_test")
    relay = _load("relay/server.py", "relay_server_for_test")
    ours = (phone_visuals.SCRIPTS, phone_visuals.IMAGES, phone_visuals.FONTS, phone_visuals.BRAIN)
    assert (wake.VISUAL_SCRIPTS, wake.VISUAL_IMAGES, wake.VISUAL_FONTS, wake.BRAIN) == ours
    assert (relay.VISUAL_SCRIPTS, relay.VISUAL_IMAGES, relay.VISUAL_FONTS, relay.BRAIN) == ours


def test_the_phones_brain_gets_every_module_it_imports():
    """The worker loads exactly the BRAIN list: a module phone_brain (or one of its modules) imports must be on it,
    apart from Python's own and the three the worker stands in for (paths, osal, requests)."""
    import ast
    import sys
    listed = {name[:-3] for name in phone_visuals.BRAIN if name.endswith(".py")}
    stood_in, missing = {"paths", "osal", "requests"}, set()
    for module in listed:
        tree = ast.parse(open(os.path.join(ROOT, module + ".py"), encoding="utf-8").read())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
            for name in (n.split(".")[0] for n in names):
                if name not in listed | stood_in and name not in sys.stdlib_module_names:
                    missing.add(f"{module} imports {name}")
    assert not missing, missing
    assert "phone_brain_worker.js" in phone_visuals.SCRIPTS


def test_nothing_else_in_the_project_is_reachable():
    served = phone_visuals.files()
    for path in ("/app.py", "/settings.json", "/vendor/../settings.json", "/vendor/earth/", "/.env"):
        assert path not in served


@pytest.mark.parametrize("from_phone", [True, False])
def test_the_windows_pictures_reach_the_phone(monkeypatch, from_phone):
    sent = []
    monkeypatch.setattr(app, "mirror_to_phone", lambda m: sent.append(m))
    monkeypatch.setattr(app, "turn_from_phone", from_phone)
    monkeypatch.setattr(app, "speak", lambda *a, **k: None)
    app.handle_direct_command("graph y = x^2 - 4")
    visual = [m for m in sent if m.get("type") == "visual"]
    assert visual and visual[0]["visual"]["type"] == "graph" and visual[0]["open"] is from_phone


def test_other_window_updates_stay_on_the_computer(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "mirror_to_phone", lambda m: sent.append(m))
    app.send_ui_update_once({"type": "dismiss_alert"})
    assert not sent


@pytest.mark.parametrize("said, seconds", [("Play the 3 minute", 180), ("play from minute 3", 180), ("play the third minute", 180),
                                           ("play it from 1:20", 80), ("start from minute 2", 120), ("go to minute 3", 180)])
def test_jumping_to_a_time_however_it_is_said(said, seconds):
    assert app.parse_seek_command(said) == seconds


@pytest.mark.parametrize("said", ["play bohemian rhapsody from 1:20", "play five years", "play 22"])
def test_playing_a_song_is_not_a_jump(said):
    assert app.parse_seek_command(said) is None
