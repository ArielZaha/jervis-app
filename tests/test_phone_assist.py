"""What Jarvis on the phone ("On this phone") asks this computer for: the user's Spotify account, to play on the
phone itself (Spotify Connect), and where a title is on Netflix. Spotify is a stand-in that records what it was
told; the routing, the choice of device and what may and may not happen on the computer are the real code."""
import json
import threading
import time

import pytest

import netflix
import phone_control
import phone_crypto
import phone_session
import sandbox

app = None
PHONE, MAC = "phone-device", "mac-device"


class Spotify:
    """Stands in for spotipy's client: the devices it lists, and everything it was asked to do."""

    def __init__(self, devices):
        self.listed, self.calls = devices, []

    def devices(self):
        return {"devices": [dict(d) for d in self.listed]}

    def search(self, q, type="track", limit=1):
        self.calls.append(("search", q))
        return {"tracks": {"items": [{"name": "Bohemian Rhapsody", "uri": "spotify:track:1", "duration_ms": 354000,
                                      "album": {"uri": "spotify:album:1"}, "artists": [{"name": "Queen"}]}]}}

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, kwargs.get("device_id"), args, kwargs))
        return call


def device(kind, device_id, active=False, volume=True):
    return {"id": device_id, "type": kind, "is_active": active, "is_restricted": False, "supports_volume": volume,
            "volume_percent": 50}


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture
def spotify(monkeypatch):
    fake = Spotify([device("Computer", MAC, active=True), device("Smartphone", PHONE)])
    monkeypatch.setattr(app, "sp", fake)
    for flag in ("youtube_active", "netflix_active", "stremio_active", "spotify_active"):
        monkeypatch.setattr(app, flag, False)
    return fake


def test_a_song_asked_for_on_the_phone_plays_on_the_phone(spotify):
    out = app.handle_phone_music("play Bohemian Rhapsody")
    assert out == {"ok": True, "reply": "Playing Bohemian Rhapsody by Queen."}
    started = [c for c in spotify.calls if c[0] == "start_playback"]
    assert len(started) == 1 and started[0][1] == PHONE   # the phone, though the computer is the active device


def test_nothing_changes_for_the_computers_own_music(spotify):
    app.handle_phone_music("play Bohemian Rhapsody")
    assert app.spotify_active is False                       # the computer doesn't think it is playing
    assert app.get_device_id() == MAC                        # and its own commands still go to its own Spotify
    assert not sandbox.actions or not any("Spotify" in a for a in sandbox.actions[-3:])   # no app opened here


@pytest.mark.parametrize("said, call", [("pause", "pause_playback"), ("resume", "start_playback"),
                                        ("next song", "next_track"), ("skip to 2:30", "seek_track")])
def test_playback_is_controlled_on_the_phone(spotify, said, call):
    out = app.handle_phone_music(said)
    assert out["ok"], out
    done = [c for c in spotify.calls if c[0] == call]
    assert done and all(c[1] == PHONE for c in done), spotify.calls


def test_volume_goes_to_spotify_on_the_phone_or_says_why_not(spotify):
    assert app.handle_phone_music("set the volume to 40") == {"ok": True, "reply": "Spotify volume is at 40 percent."}
    assert [c for c in spotify.calls if c[0] == "volume"][0][1] == PHONE
    spotify.listed[1]["supports_volume"] = False              # an iPhone
    assert "volume buttons" in app.handle_phone_music("volume up")["reply"]
    assert sandbox.actions == [] or not any("volume" in a.lower() for a in sandbox.actions)   # never the computer's own


def test_no_spotify_on_the_phone_yet_is_said_at_once_or_waited_for(spotify, monkeypatch):
    spotify.listed[:] = [device("Computer", MAC, active=True)]
    began = time.time()
    assert app.handle_phone_music("play Bohemian Rhapsody") == {"ok": False, "reason": "no_device"}
    assert time.time() - began < 1 and not [c for c in spotify.calls if c[0] == "start_playback"]
    # the phone is opening its Spotify: it shows up a moment later, and the music starts there
    monkeypatch.setattr(app.time, "sleep", lambda s: spotify.listed.append(device("Smartphone", PHONE)))
    out = app.handle_phone_music("play Bohemian Rhapsody", wait=True)
    assert out["ok"] and [c for c in spotify.calls if c[0] == "start_playback"][0][1] == PHONE


@pytest.mark.parametrize("said, reason", [("open Notes", "not_music"), ("delete my files", "not_music"),
                                          ("what's the weather", "not_music"), ("play OK Computer on Apple Music", "other_service")])
def test_only_music_runs_this_way(spotify, said, reason):
    before = list(sandbox.actions)
    assert app.handle_phone_music(said) == {"ok": False, "reason": reason}
    assert sandbox.actions == before and not [c for c in spotify.calls if c[0] != "search"]


def test_without_a_spotify_account_here_the_phone_is_told_so(monkeypatch):
    monkeypatch.setattr(app, "sp", None)
    assert app.handle_phone_music("play Bohemian Rhapsody") == {"ok": False, "reason": "no_spotify"}
    assert app._phone_ai_config().get("spotify") in (False, None)


def test_netflix_titles_are_looked_up_for_the_phone(monkeypatch):
    monkeypatch.setattr(netflix, "find_title", lambda q: ("70143836", "Breaking Bad") if "breaking" in q.lower() else None)
    monkeypatch.setattr(netflix, "find_episode", lambda series, s, e: ("70196253", "Caballo sin Nombre") if (s, e) == (3, 2) else None)
    assist = app._on_phone_assist
    assert assist({"kind": "netflix", "title": "Breaking Bad"}) == {"ok": True, "url": "https://www.netflix.com/watch/70143836", "name": "Breaking Bad"}
    assert assist({"kind": "netflix", "title": "Breaking Bad", "season": 3, "episode": 2})["url"] == "https://www.netflix.com/watch/70196253"
    assert assist({"kind": "netflix", "title": "Breaking Bad", "season": 9, "episode": 9}) == {"ok": False, "reason": "no_episode", "name": "Breaking Bad"}
    assert assist({"kind": "netflix", "title": "Breaking Bad", "trailer": True})["url"] == "https://www.netflix.com/title/70143836"
    assert assist({"kind": "netflix", "title": "Nothing Like It"}) == {"ok": False, "reason": "not_found"}
    assert assist({"kind": "run", "text": "rm -rf"}) == {"ok": False, "reason": "unknown"}


def test_an_attached_phone_gets_its_answer_and_an_unattached_one_gets_nothing(tmp_path):
    """Through the session router: only a paired, attached phone can ask, and the answer goes back to it alone."""
    registry = phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))
    server = phone_control.PhoneControlServer(execute=lambda *a: "ok", registry=registry)
    device_id, token, key = registry.add("iPhone")
    asked = []
    router = phone_session.PhoneSessionRouter(server, lambda *a: "", lambda *a, **k: None,
                                              on_assist=lambda m: asked.append(m) or {"ok": True, "reply": "Playing."})
    sent = []
    import asyncio

    async def go():
        await router.on_frame("stranger", {"type": "assist", "kind": "music", "text": "play x", "requestId": "r0"}, sent.append, lambda: None)
        assert not asked and not sent
        proof = phone_crypto.encrypt(key, {"type": "attach", "deviceId": device_id, "ts": time.time() * 1000})
        await router.on_frame("conn", {"type": "auto_attach", "deviceId": device_id, "proof": proof}, sent.append, lambda: None)
        sent.clear()
        await router.on_frame("conn", phone_crypto.encrypt(key, {"type": "assist", "kind": "music", "text": "play x", "requestId": "r1"}),
                              sent.append, lambda: None)
        for _ in range(50):
            if sent:
                break
            await asyncio.sleep(0.02)
    asyncio.run(go())
    assert [m["kind"] for m in asked] == ["music"]
    assert phone_crypto.decrypt(key, sent[0]) == {"type": "assist_result", "requestId": "r1", "ok": True, "reply": "Playing."}
