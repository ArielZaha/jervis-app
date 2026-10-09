"""Playing music on Spotify, from the words to the exact track (sandboxed: a fake Spotify app whose search shows
what each test puts in its catalogue, and whose player plays what was pressed):

- a clear request is played at once — never "just to make sure, ...? (yes / no)";
- the result is chosen by rules (spotify_match), not by Spotify's first row or a language model: a Hebrew title,
  the same title typed in English letters, an artist misheard, an artist named with a title, a playlist asked for;
- that exact result (its URI) is the one played, and the reply names what the player really shows;
- when nothing fits, the closest is offered once, kept exactly — "yes" plays that very URI, and a "yes" is never
  taken as a new request (a song called "yes");
- a start that didn't happen is said plainly, never "Playing ...";
- with the user's own Spotify keys, the Web API's results are ranked the same way and played by URI."""
import pytest

import sandbox

app = None
SUZI_KFIR = {"uri": "spotify:track:7tJSQWB4z5fKJCR63yhq9v", "kind": "track", "title": "סוזי תזוזי", "artists": ["כפיר עטיה"]}
SUZI_ALBUM = {"uri": "spotify:album:4S5uljsXgcHPpin5co4gik", "kind": "album", "title": "סוזי תזוזי", "artists": ["כפיר עטיה"]}
SUZI_STATIC = {"uri": "spotify:track:static-suzi", "kind": "track", "title": "Suzi Tazuzi", "artists": ["Static & Ben El"]}
SUSANNA = {"uri": "spotify:track:celentano", "kind": "track", "title": "Susanna (Susanna) - Remastered",
           "artists": ["Adriano Celentano"]}
WW3 = {"uri": "spotify:track:ww3", "kind": "track", "title": "WW3", "artists": ["Someone"]}
KAPIT = {"uri": "spotify:track:kapit", "kind": "track", "title": "כפית אחת של טוב", "artists": ["Static"]}
STATIC_ARTIST = {"uri": "spotify:artist:0xHa28taiElkcQf9o3z76g", "kind": "artist", "title": "Static & Ben El", "artists": []}
STATIC_PLAYLIST = {"uri": "spotify:playlist:static-all", "kind": "playlist", "title": "STATIC AND BEN EL ALL SONGS",
                   "artists": ["Elad"]}


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def fresh(sandboxed, monkeypatch):
    import time
    from types import SimpleNamespace
    import spotify_local
    for name in ("pending_spotify_request", "pending_spotify_choice", "pending_spotify_play", "pending_translation"):
        setattr(app, name, None)
    app.youtube_active = app.netflix_active = app.stremio_active = False
    monkeypatch.setattr(app, "sp", None)
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    sandbox.reset()
    yield


def catalogue(**searches):
    import spotify_match
    for q, results in searches.items():
        sandbox.spotify_catalogue[spotify_match.normalize(q.replace("_", " "))] = results


def say(text: str):
    """The whole way a request goes: understood (Hebrew or English), then handled as a command."""
    english = app.understand_language(text)
    if english is None:
        return None
    return app.handle_direct_command(english)


def pressed():
    return [a.split("play ", 1)[1] for a in sandbox.actions if a.startswith("spotify press play ")]


# ---- clear requests play at once, the right result ----
def test_a_hebrew_title_in_an_english_command_is_played_without_asking():
    catalogue(**{"סוזי תזוזי": [SUZI_KFIR, SUZI_ALBUM, WW3]})
    reply = say('play "סוזי תזוזי" on spotify')
    assert reply == 'Playing "סוזי תזוזי" by כפיר עטיה on Spotify.'
    assert pressed() == [SUZI_KFIR["uri"]]   # that exact track, not its album, not WW3
    assert app.pending_translation is None   # no "just to make sure" question


@pytest.mark.parametrize("said", ["תנגן סוזי תזוזי בספוטיפיי", "תנגן לי את סוזי תזוזי",
                                  "play סוזי תזוזי on spotify"])
def test_hebrew_requests_keep_the_title_as_said(said):
    catalogue(**{"סוזי תזוזי": [SUZI_KFIR]})
    assert say(said) == 'Playing "סוזי תזוזי" by כפיר עטיה on Spotify.'


def test_a_hebrew_title_typed_in_english_letters_is_found_in_hebrew():
    # Spotify's top result for the English letters is an Italian song: it's not taken just for being first
    catalogue(suzi_tazozi=[SUSANNA], **{"סוזי תזוזי": [SUZI_KFIR]})
    reply = say("play suzi tazozi on spotify")
    assert pressed() == [SUZI_KFIR["uri"]] and "כפיר עטיה" in reply
    assert "spotify search page סוזי תזוזי" in sandbox.actions


def test_a_misheard_artist_plays_that_artist_not_a_neighbours_song():
    catalogue(static_and_ben_al=[KAPIT, STATIC_PLAYLIST, STATIC_ARTIST])
    reply = say("play static and ben al on spotify")
    assert pressed() == [STATIC_ARTIST["uri"]] and reply == "Playing Static & Ben El on Spotify."


def test_a_named_artist_wins_over_a_closer_title_by_someone_else():
    catalogue(**{"Suzi Tazuzi by Static and Ben El": [SUZI_KFIR, SUZI_STATIC]})
    say("play Suzi Tazuzi by Static and Ben El on spotify")
    assert pressed() == [SUZI_STATIC["uri"]]


def test_a_playlist_asked_for_is_the_playlist():
    catalogue(**{"static and ben el all songs": [STATIC_ARTIST, STATIC_PLAYLIST]})
    say("play the static and ben el all songs playlist on spotify")
    assert pressed() == [STATIC_PLAYLIST["uri"]]


# ---- nothing fits: offered, kept exactly; "yes" is that, never a new request ----
def test_when_nothing_fits_the_closest_is_offered_and_yes_plays_exactly_it():
    catalogue(zzqy_blorp=[WW3])
    reply = say("play zzqy blorp on spotify")
    assert "Should I play it?" in reply and not pressed()
    assert app.pending_spotify_choice["candidate"]["uri"] == WW3["uri"]
    assert say("yes") == 'Playing "WW3" by Someone on Spotify.'
    assert pressed() == [WW3["uri"]]
    assert app.pending_spotify_choice is None


def test_no_to_the_offer_plays_nothing():
    catalogue(zzqy_blorp=[WW3])
    say("play zzqy blorp on spotify")
    assert say("no") == "Okay, I didn't play anything." and not pressed()


def test_yes_to_what_would_you_like_to_listen_to_is_not_a_song():
    app.pending_spotify_request = {"at": app.time.time()}
    assert say("yes") == "What should I play?"
    assert not [a for a in sandbox.actions if a.startswith("spotify search page")]
    catalogue(**{"סוזי תזוזי": [SUZI_KFIR]})
    assert "כפיר עטיה" in say("סוזי תזוזי")   # the next thing said is the song


# ---- it really started, or it says so ----
def test_a_start_that_didnt_happen_is_said_plainly():
    catalogue(**{"סוזי תזוזי": [SUZI_KFIR]})
    sandbox.spotify_refuses.add(SUZI_KFIR["uri"])
    reply = say("play סוזי תזוזי on spotify")
    assert not reply.startswith("Playing") and "didn't start" in reply


# ---- the Web API, with the user's own keys: ranked the same, played by URI ----
class FakeAPI:
    def __init__(self, results, plays=True):
        self.results, self.plays, self.started, self.now = results, plays, None, {}

    def search(self, q, type, limit):
        import spotify_match
        items = self.results.get(spotify_match.normalize(q), [])
        out = {"tracks": {"items": []}, "artists": {"items": []}, "albums": {"items": []}, "playlists": {"items": []}}
        for r in items:
            key = {"track": "tracks", "artist": "artists", "album": "albums", "playlist": "playlists"}[r["kind"]]
            out[key]["items"].append({"uri": r["uri"], "name": r["title"],
                                      "artists": [{"name": a} for a in r["artists"]], "duration_ms": 200000})
        return out

    def start_playback(self, device_id=None, uris=None, context_uri=None, position_ms=None):
        self.started = {"uris": uris, "context_uri": context_uri}
        if self.plays:
            self.now = {"is_playing": True, "item": {"uri": (uris or [None])[0]}, "context": {"uri": context_uri}}

    def current_playback(self):
        return self.now


def test_with_keys_the_ranked_result_is_played_by_its_exact_uri(monkeypatch):
    import spotify_match
    api = FakeAPI({spotify_match.normalize("suzi tazozi"): [SUSANNA],
                   spotify_match.normalize("סוזי תזוזי"): [SUZI_KFIR]})
    monkeypatch.setattr(app, "sp", api)
    monkeypatch.setattr(app, "ensure_spotify_device", lambda: "device")
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    reply = app.play_song("suzi tazozi")
    assert api.started == {"uris": [SUZI_KFIR["uri"]], "context_uri": None}
    assert reply == 'Playing "סוזי תזוזי" by כפיר עטיה on Spotify.'


def test_with_keys_a_start_the_player_doesnt_report_is_not_called_playing(monkeypatch):
    import spotify_match
    api = FakeAPI({spotify_match.normalize("סוזי תזוזי"): [SUZI_KFIR]}, plays=False)
    monkeypatch.setattr(app, "sp", api)
    monkeypatch.setattr(app, "ensure_spotify_device", lambda: "device")
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    assert "didn't report it playing" in app.play_song("סוזי תזוזי")


# ---- the matching itself ----
def test_scores_put_the_meant_result_first():
    import spotify_match as m
    pick = m.choose(m.parse("סוזי תזוזי"), [dict(WW3, position=0), dict(SUZI_ALBUM, position=1),
                                            dict(SUZI_KFIR, position=2)])
    assert pick["best"]["uri"] == SUZI_KFIR["uri"] and pick["verdict"] == "confident"
    pick = m.choose(m.parse("suzi tazozi"), [dict(SUSANNA, position=0)])
    assert pick["verdict"] == "none"   # an Italian song isn't it, however high Spotify put it


@pytest.mark.parametrize("a,b,close", [("suzi tazozi", "סוזי תזוזי", True), ("static and ben al", "Static & Ben El", True),
                                       ("Ben El", "בן אל", True), ("Echoes", "Echoes - 2011 Remastered Version", True),
                                       ("suzi tazozi", "Susanna (Susanna) - Remastered", False),
                                       ("static and ben al", "כפית אחת של טוב", False)])
def test_similarity_across_scripts_spellings_and_extras(a, b, close):
    import spotify_match as m
    assert (m.similarity(a, b) >= 0.8) == close, m.similarity(a, b)


def test_requests_are_read_for_title_artist_and_kind():
    import spotify_match as m
    assert m.parse("Echoes by Pink Floyd") == {"text": "Echoes by Pink Floyd", "title": "Echoes",
                                               "artist": "Pink Floyd", "kind": None}
    assert m.parse("סוזי תזוזי של כפיר עטיה")["artist"] == "כפיר עטיה"
    assert m.parse('Static and Ben El "Suzi Tazuzi"')["title"] == "Suzi Tazuzi"
    assert m.parse("the Chill Vibes playlist")["kind"] == "playlist"
    assert m.uri_of("https://xpui.app.spotify.com/track/7tJSQWB4z5fKJCR63yhq9v") == \
        ("track", "spotify:track:7tJSQWB4z5fKJCR63yhq9v")


# ---- asking first is for what can't be taken back ----
@pytest.mark.parametrize("ask,english,status", [
    (["new name Suzi"], "Play Suzi Tazuzi", "ok"),
    (["not English words: Tazuzi"], "Play Suzi Tazuzi", "ok"),
    (["length 3 -> 12 words"], "Open Spotify and play some music", "ok"),
    (["new name Report"], "Delete the file Report", "confirm"),
    (["a negation appeared"], "Don't open Spotify", "confirm"),
    (["a delete/close/send/cancel word appeared"], "Close Spotify", "confirm"),
])
def test_only_risky_or_meaning_changing_translations_are_confirmed(ask, english, status):
    import language
    assert language.status_for([], ask, english) == status


def test_a_song_the_artist_hasnt_got_is_said_not_passed_off():
    catalogue(**{"Suzi Tazuzi by Static and Ben El": [SUZI_KFIR, STATIC_ARTIST]})
    reply = say("play Suzi Tazuzi by Static and Ben El on spotify")
    assert pressed() == [STATIC_ARTIST["uri"]]
    assert reply == "I couldn't find \"Suzi Tazuzi\" by Static & Ben El on Spotify, so I'm playing Static & Ben El."


def test_whats_already_playing_isnt_paused_by_asking_for_it_again():
    catalogue(**{"סוזי תזוזי": [SUZI_KFIR]})
    sandbox.spotify_player.update(playing=True, title="סוזי תזוזי", artist="כפיר עטיה")
    assert say("play סוזי תזוזי on spotify") == 'Playing "סוזי תזוזי" by כפיר עטיה on Spotify.'
    assert pressed() == []   # its Play button would have paused it


def test_an_album_found_first_doesnt_stop_the_search_for_the_song():
    # the English letters found only the album (Spotify plays an album shuffled for a free account)
    catalogue(suzi_tazozi=[SUZI_ALBUM], **{"סוזי תזוזי": [SUZI_KFIR, SUZI_ALBUM]})
    say("play suzi tazozi on spotify")
    assert pressed() == [SUZI_KFIR["uri"]]
