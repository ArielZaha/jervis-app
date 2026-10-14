"""Playing music by name: playlists, albums, artists and liked songs, on Spotify, Apple Music, YouTube and the rest.
Spotify, the Music app and YouTube are all simulated here; nothing plays for real."""
import json

import pytest

import music
import sandbox
from music import parse_music_request

app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


# ---------------------------------------------------------------- understanding the request
@pytest.mark.parametrize("said, kind, names, service, extra", [
    ('play "My Favorite Songs" playlist on spotify', "playlist", ["My Favorite Songs"], "spotify", {"mine": False}),
    ("play My Favorite Songs playlist on spotify", "playlist", ["Favorite Songs", "My Favorite Songs"], "spotify", {"mine": True}),
    ("play my workout playlist", "playlist", ["workout", "my workout"], "", {"mine": True}),
    ("shuffle my liked songs", "liked", ["my liked songs"], "", {"shuffle": True}),
    ("Jarvis, can you play my Gym playlist on shuffle", "playlist", ["Gym", "my Gym"], "", {"shuffle": True}),
    ("play the album OK Computer by Radiohead", "album", ["OK Computer"], "", {"by": "Radiohead"}),
    ("play OK Computer album on apple music", "album", ["OK Computer"], "apple_music", {}),
    ("play the song Creep by Radiohead on apple music", "song", ["Creep"], "apple_music", {"by": "Radiohead"}),
    ("play songs by Adele on youtube music", "artist", ["Adele"], "youtube_music", {}),
    ("put on a lofi playlist on youtube", "playlist", ["lofi"], "youtube", {}),
    ("play my discover weekly", "playlist", ["discover weekly", "my discover weekly"], "", {}),
    ("play the repeat playlist on spotify", "playlist", ["repeat"], "spotify", {"public": False}),
    ("play a lofi playlist on spotify", "playlist", ["lofi"], "spotify", {"public": True}),
    ("play some chill playlist", "playlist", ["chill"], "", {"public": True}),
    ("play the playlist called Road Trip", "playlist", ["Road Trip"], "", {}),
    ("play Radiohead on Apple Music", "any", ["Radiohead"], "apple_music", {}),
    ("listen to the album Thriller on deezer", "album", ["Thriller"], "deezer", {}),
])
def test_requests_are_understood(said, kind, names, service, extra):
    r = parse_music_request(said)
    assert (r.kind, r.names, r.service) == (kind, names, service)
    for key, value in extra.items():
        assert getattr(r, key) == value, key


@pytest.mark.parametrize("said", ["play Bohemian Rhapsody", "play Bohemian Rhapsody on spotify", "play Radiohead on spotify",
                                  "play lofi on youtube", "open spotify", "what's playing", "play the next song"])
def test_plain_songs_keep_their_existing_handling(said):
    assert parse_music_request(said) is None


@pytest.mark.parametrize("said, mix", [("repeat", "On Repeat"), ("my repeat", "On Repeat"), ("on repeat", "On Repeat"),
                                       ("rewind", "Repeat Rewind"), ("my discover weekly", "Discover Weekly"),
                                       ("daily mix 3", "Daily Mix 3"), ("daily 2", "Daily Mix 2"),
                                       ("top songs 2025", "Your Top Songs 2025"), ("Release Radar", "Release Radar"),
                                       ("workout", ""), ("my favorite songs", ""), ("repeat after me", "")])
def test_spotifys_own_mixes_are_known_by_what_people_call_them(said, mix):
    assert music.spotify_mix(said) == mix


def test_best_match_prefers_the_real_name_and_refuses_a_guess():
    names = ["Workout Mix 2024", "My Favorite Songs", "Favorites from Mom", "Road Trip"]
    assert music.best_match("My Favorite Songs", names) == "My Favorite Songs"
    assert music.best_match("road trip", names) == "Road Trip"
    assert music.best_match("workout", names) == "Workout Mix 2024"
    assert music.best_match("Sleep sounds", names) is None


# ---------------------------------------------------------------- Spotify (simulated)
class FakeSpotify:
    def __init__(self, own=(), public=(), saved=()):
        self.own, self.public, self.saved, self.calls = list(own), list(public), list(saved), []

    def current_user_playlists(self, limit=50, offset=0):
        return {"items": self.own[offset:offset + limit], "next": None}

    def current_user_saved_tracks(self, limit=50):
        return {"items": [{"track": {"uri": u}} for u in self.saved]}

    def search(self, q, type, limit):
        self.calls.append(("search", type, q))
        if type == "playlist":
            return {"playlists": {"items": self.public}}
        if type == "album":
            return {"albums": {"items": [{"name": "OK Computer", "uri": "spotify:album:ok", "artists": [{"name": "Radiohead"}]}]}}
        if type == "artist":
            return {"artists": {"items": [{"name": "Adele", "uri": "spotify:artist:adele"}]}}
        return {"tracks": {"items": []}}

    def start_playback(self, device_id=None, context_uri=None, uris=None, **kw):
        self.calls.append(("play", context_uri or uris))

    def shuffle(self, state, device_id=None):
        self.calls.append(("shuffle", state))

    def devices(self):
        return {"devices": [{"id": "mac", "type": "Computer", "is_active": True}]}


MINE = {"name": "My Favorite Songs", "uri": "spotify:playlist:mine", "owner": {"display_name": "Ariel"}}
STRANGERS = {"name": "My Favorite Songs", "uri": "spotify:playlist:stranger", "owner": {"display_name": "someone"}}


@pytest.fixture
def spotify(monkeypatch):
    def use(own=(), public=(), saved=(), library=True):
        fake = FakeSpotify(own, public, saved)
        monkeypatch.setattr(app, "sp", fake)
        monkeypatch.setattr(app, "spotify_library", lambda: fake if library else None)
        asked = []
        monkeypatch.setattr(app, "ask_spotify_library_permission", lambda: asked.append(True))
        fake.asked = asked
        return fake
    return use


def test_the_reported_request_plays_the_users_own_playlist(spotify):
    fake = spotify(own=[MINE], public=[STRANGERS])
    reply = app.handle_direct_command('play "My Favorite Songs" playlist on spotify')
    assert reply == "Playing your playlist My Favorite Songs on Spotify."
    assert ("play", "spotify:playlist:mine") in fake.calls


def test_my_playlist_never_falls_back_to_a_strangers_one(spotify):
    fake = spotify(own=[], public=[STRANGERS])
    reply = app.handle_direct_command("play my favorite songs playlist")
    assert "couldn't find a playlist" in reply
    assert not any(c[0] == "play" for c in fake.calls)


def test_a_public_playlist_is_found_when_it_isnt_yours(spotify):
    fake = spotify(own=[], public=[{"name": "Lofi Beats", "uri": "spotify:playlist:lofi", "owner": {"display_name": "Spotify"}}])
    assert app.handle_direct_command("play the Lofi Beats playlist") == "Playing the playlist Lofi Beats by Spotify on Spotify."
    assert ("play", "spotify:playlist:lofi") in fake.calls


@pytest.mark.parametrize("said", ["play my Workout playlist on Spotify", 'play "My Favorite Songs" playlist on spotify',
                                  "play the Lofi Beats playlist"])
def test_without_library_permission_it_asks_once_instead_of_guessing(spotify, said):
    """Spotify's search for "My Favorite Songs" really does return strangers' playlists with that exact name."""
    fake = spotify(public=[STRANGERS, {"name": "Lofi Beats", "uri": "spotify:playlist:lofi", "owner": {}}], library=False)
    reply = app.handle_direct_command(said)
    assert "permission" in reply and fake.asked == [True]
    assert not any(c[0] == "play" for c in fake.calls)


def test_a_name_starting_with_my_never_plays_a_strangers_playlist(spotify):
    fake = spotify(own=[], public=[STRANGERS])
    reply = app.handle_direct_command('play "My Favorite Songs" playlist on spotify')
    assert reply.startswith("I couldn't find a playlist called My Favorite Songs in your Spotify.")
    assert not any(c[0] == "play" for c in fake.calls)


def test_the_repeat_playlist_is_the_users_on_repeat_not_a_strangers(spotify, monkeypatch):
    """Reported: "play the repeat playlist on spotify" played a stranger's playlist called "repeat"."""
    fake = spotify(own=[MINE], public=[{"name": "repeat", "uri": "spotify:playlist:julez", "owner": {"display_name": "julez"}}])
    local = []
    monkeypatch.setattr(app.spotify_local, "installed", lambda: True)
    monkeypatch.setattr(app, "play_song_locally", lambda q, *a, **k: local.append(q) or f"Playing {q} on Spotify.")
    assert app.handle_direct_command("play the repeat playlist on spotify") == "Playing On Repeat on Spotify."
    assert local == ["On Repeat"] and not any(c[0] == "play" for c in fake.calls)


def test_a_playlist_of_your_own_called_repeat_wins_over_the_mix(spotify, monkeypatch):
    fake = spotify(own=[{"name": "Repeat", "uri": "spotify:playlist:myrepeat"}])
    monkeypatch.setattr(app.spotify_local, "installed", lambda: True)
    monkeypatch.setattr(app, "play_song_locally", lambda q, *a, **k: pytest.fail("played the mix"))
    assert app.handle_direct_command("play the repeat playlist") == "Playing your playlist Repeat on Spotify."
    assert ("play", "spotify:playlist:myrepeat") in fake.calls


def test_one_particular_playlist_never_plays_a_strangers_but_a_playlist_may(spotify):
    road = {"name": "Road Trip", "uri": "spotify:playlist:road", "owner": {"id": "julez", "display_name": "julez"}}
    fake = spotify(own=[MINE, {"name": "Road Trips 2023", "uri": "spotify:playlist:rt23"}], public=[road])
    reply = app.handle_direct_command("play the road trip vibes playlist")
    assert reply.startswith("I couldn't find a playlist called road trip vibes in your Spotify. Did you mean Road Trips 2023")
    assert 'play a road trip vibes playlist' in reply and not any(c[0] == "play" for c in fake.calls)
    assert app.handle_direct_command("play a road trip playlist") == "Playing the playlist Road Trip by julez on Spotify."


def test_liked_songs_and_shuffle(spotify):
    fake = spotify(saved=["spotify:track:1", "spotify:track:2"])
    assert app.handle_direct_command("shuffle my liked songs") == "Playing your liked songs on Spotify, shuffled."
    assert ("shuffle", True) in fake.calls and ("play", ["spotify:track:1", "spotify:track:2"]) in fake.calls


def test_albums_and_artists(spotify):
    fake = spotify()
    assert app.handle_direct_command("play the album OK Computer by Radiohead") == "Playing the album OK Computer by Radiohead on Spotify."
    assert ("search", "album", "album:OK Computer artist:Radiohead") in fake.calls
    assert app.play_music("Adele", "artist") == "Playing Adele on Spotify."


# ---------------------------------------------------------------- Apple Music (simulated Music app)
def test_apple_music_plays_a_library_playlist(monkeypatch):
    calls = []
    def fake_script(script, *args, timeout=20):
        calls.append((script, args))
        return "Chill, Workout, Road Trip" if script is music._APPLE_PLAYLISTS else "Some Song"
    monkeypatch.setattr(music, "_music_script", fake_script)
    monkeypatch.setattr(music.osal, "IS_MAC", True)
    reply = app.handle_direct_command("play my workout playlist on apple music")
    assert reply == "Playing your playlist Workout on Apple Music."
    assert calls[-1] == (music._APPLE_PLAY_PLAYLIST, ("Workout", "false"))


def test_apple_music_says_so_when_it_can_only_open_the_search(monkeypatch):
    monkeypatch.setattr(music, "_music_script", lambda script, *a, timeout=20: "" if script is not music._APPLE_PLAYLISTS else "Chill")
    monkeypatch.setattr(music.osal, "IS_MAC", True)
    opened = []
    monkeypatch.setattr(music.subprocess, "run", lambda cmd, **kw: opened.append(cmd))
    reply = app.play_music("Thriller", "album", "apple_music")
    assert "isn't in your Apple Music library" in reply and "Tap play" in reply
    assert opened and "music.apple.com/search?term=Thriller" in opened[-1][-1]


# ---------------------------------------------------------------- YouTube / YouTube Music (simulated search)
def test_a_youtube_playlist_is_found_and_started(monkeypatch):
    opened = []
    monkeypatch.setattr(music, "youtube_playlists", lambda q, limit=8: [("Lofi Hip Hop Radio Mix", "PLabc123def456", "vid12345678")])
    monkeypatch.setattr(app, "open_youtube", lambda url, **kw: opened.append(url))
    assert app.handle_direct_command("put on a lofi playlist on youtube") == "Playing the playlist Lofi Hip Hop Radio Mix on YouTube."
    assert opened == ["https://www.youtube.com/watch?v=vid12345678&list=PLabc123def456"]
    assert app.play_music("lofi", "playlist", "youtube_music").endswith("on YouTube Music.")
    assert opened[-1].startswith("https://music.youtube.com/watch?v=")


def test_youtube_playlist_search_results_are_read(monkeypatch):
    data = {"contents": [{"lockupViewModel": {"contentId": "PLxyz7890abcd", "metadata": {"lockupMetadataViewModel": {
        "title": {"content": "Chill Jazz Playlist"}}}, "rendererContext": {"commandContext": {"onTap": {"innertubeCommand": {
        "watchEndpoint": {"videoId": "abcdefghijk", "playlistId": "PLxyz7890abcd"}}}}}}}]}
    html = f"<script>var ytInitialData = {json.dumps(data)};</script>"
    class R:
        text = html
    monkeypatch.setattr("requests.get", lambda *a, **k: R())
    assert music.youtube_playlists("chill jazz") == [("Chill Jazz Playlist", "PLxyz7890abcd", "abcdefghijk")]


# ---------------------------------------------------------------- services Jarvis can only open
def test_other_services_open_their_search_and_say_so(monkeypatch):
    opened = []
    monkeypatch.setattr(app, "_open_music_url", lambda url, host: opened.append((url, host)))
    reply = app.handle_direct_command("play some jazz playlist on soundcloud")
    assert opened == [("https://soundcloud.com/search/sets?q=jazz", "soundcloud.com")]
    assert "Tap play there" in reply and "Playing" not in reply


def test_the_ai_can_ask_for_it_too():
    assert any(t["function"]["name"] == "play_music" for t in app.TOOLS)
    assert "play_music" in app.ACTION_TOOLS and app.TOOL_FUNCTIONS["play_music"] is app.play_music
    assert app.is_music_command("shuffle my workout playlist")
