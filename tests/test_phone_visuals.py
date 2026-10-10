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
    ours = (phone_visuals.SCRIPTS, phone_visuals.IMAGES, phone_visuals.FONTS)
    assert (wake.VISUAL_SCRIPTS, wake.VISUAL_IMAGES, wake.VISUAL_FONTS) == ours
    assert (relay.VISUAL_SCRIPTS, relay.VISUAL_IMAGES, relay.VISUAL_FONTS) == ours


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
