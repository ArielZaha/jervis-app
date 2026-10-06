"""Spotify playback commands: "another song by <artist>" plays a different song by that artist (not just the next
in the queue), and skipping recovers from Spotify's 404 for an idle device instead of showing the raw API error.
Spotify itself is a fake here (no network); tests/sandbox.py keeps everything else from touching the computer."""
import pytest
import spotipy

import sandbox

app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.mark.parametrize("said, artist", [
    ("Play another song of radiohead", "radiohead"),
    ("play another song by Radiohead on Spotify", "radiohead"),
    ("put on a different track from Adele please", "adele"),
    ("play another Radiohead song", "radiohead"),
    ("play something else by Coldplay", "coldplay"),
    ("play another song by them", ""),
    ("another song from this artist", ""),
    ("play one more song by Arctic Monkeys", "arctic monkeys"),
])
def test_another_song_by_an_artist_is_recognized(said, artist):
    assert app.parse_another_by_artist(said) == artist
    assert app.parse_track_skip(said) is None   # never a plain skip


@pytest.mark.parametrize("said", ["play another song", "another song", "play a different song", "next song",
                                  "play another song from the album", "skip this one"])
def test_plain_skips_are_still_skips(said):
    assert app.parse_another_by_artist(said) is None
    assert app.parse_track_skip(said) == "next"


class FakeSpotify:
    """Just enough of spotipy.Spotify. `idle_device` makes player commands 404 until playback is transferred —
    exactly what Spotify does for an open-but-inactive device (the error in the bug report)."""

    def __init__(self, idle_device=True, current_id="t1"):
        self.idle = idle_device
        self.calls = []
        self.current_id = current_id

    def _player(self, name, **kw):
        self.calls.append((name, kw))
        if self.idle:
            raise spotipy.SpotifyException(404, -1, "https://api.spotify.com/v1/me/player/next: Not found.")

    def devices(self):
        return {"devices": [{"id": "phone", "type": "Smartphone", "is_active": False},
                            {"id": "mac", "type": "Computer", "is_active": False}]}

    def transfer_playback(self, device_id, force_play=False):
        self.calls.append(("transfer", {"device_id": device_id}))
        self.idle = False

    def next_track(self, device_id=None):
        self._player("next", device_id=device_id)

    def previous_track(self, device_id=None):
        self._player("previous", device_id=device_id)

    def start_playback(self, **kw):
        self._player("start", **kw)

    def current_playback(self):
        return {"progress_ms": 1000, "item": {"id": self.current_id, "name": "Karma Police",
                                               "artists": [{"name": "Radiohead"}]}}

    def search(self, q, type, limit):
        if type == "artist":
            return {"artists": {"items": [{"id": "rh", "name": "Radiohead"}]}}
        return {"tracks": {"items": []}}

    def artist_top_tracks(self, artist_id):
        return {"tracks": [{"id": f"t{i}", "name": f"Song {i}", "uri": f"spotify:track:t{i}",
                            "album": {"uri": f"spotify:album:a{i}"}, "artists": [{"id": "rh"}]} for i in range(1, 6)]}


@pytest.fixture
def fake_spotify(monkeypatch):
    fake = FakeSpotify()
    monkeypatch.setattr(app, "sp", fake)
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    return fake


def test_skip_on_an_idle_device_activates_it_and_retries(fake_spotify):
    reply = app.skip_track("next")
    assert reply == "Now playing Karma Police by Radiohead."
    names = [c[0] for c in fake_spotify.calls]
    assert names == ["next", "transfer", "next"]
    assert fake_spotify.calls[0][1]["device_id"] == "mac"   # this computer, not the sleeping phone listed first


def test_skip_that_still_fails_gives_a_plain_message_not_the_api_error(fake_spotify, monkeypatch):
    monkeypatch.setattr(fake_spotify, "transfer_playback", lambda device_id, force_play=False: None)   # stays idle
    reply = app.skip_track("next")
    assert "http" not in reply and "404" not in reply
    assert reply == "Spotify isn't playing anything I can skip right now. Ask me to play a song first."


def test_another_song_by_the_artist_plays_a_different_song_by_them(fake_spotify):
    picked = set()
    for _ in range(8):
        reply = app.play_another_by_artist("radiohead")
        start = [kw for name, kw in fake_spotify.calls if name == "start"][-1]
        assert start["offset"]["uri"] != "spotify:track:t1"   # never the song already playing
        assert reply.startswith("Playing Song ") and reply.endswith(" by Radiohead.")
        picked.add(start["offset"]["uri"])
    assert len(picked) > 1   # not the same pick every time


def test_another_song_by_them_uses_the_artist_playing_now(fake_spotify):
    fake_spotify.idle = False
    assert app.play_another_by_artist("").endswith(" by Radiohead.")


def test_the_whole_command_routes_there(fake_spotify, monkeypatch):
    monkeypatch.setattr(app, "youtube_active", False)
    reply = app.handle_direct_command("Play another song of radiohead")
    assert reply.endswith(" by Radiohead.") and "couldn't" not in reply
