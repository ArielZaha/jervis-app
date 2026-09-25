"""Commands must fire when asked for, and never just because a word appears in conversation.

Everything runs in the sandbox (tests/sandbox.py): an action shows up as a recorded "run ..." / "open ..." instead of
happening on the computer running the tests.
"""
import pytest

import sandbox

app = None   # imported inside the sandbox (see sandboxed), so nothing it does at import can act on the computer


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def fresh_state(sandboxed):
    """Each sentence starts from a quiet Jervis: nothing playing, no question waiting for an answer."""
    for name in ("pending_spotify_request", "pending_google_search", "pending_netflix_request",
                 "pending_stremio_request", "pending_calendar_choice", "pending_dictation"):
        if hasattr(app, name):
            setattr(app, name, None)
    app.youtube_active = app.netflix_active = app.stremio_active = False
    app.last_whatsapp["at"] = 0
    sandbox.reset()
    yield


def route(text: str):
    result = app.handle_direct_command(text)
    return result, list(sandbox.actions)


# ---- the brief's own examples, and more talk *about* things ----
CONVERSATION = [
    "I installed Chrome yesterday",
    "I was talking about the weather yesterday",
    "my brother opened Spotify on his phone",
    "I watched Breaking Bad last year and loved it",
    "the song Echoes is really long",
    "my teacher said the timer broke",
    "do you know what Netflix is",
    "I closed the door",
    "YouTube was down this morning",
    "I had to solve a hard problem at work",
    "Word is a program by Microsoft",
    "my WhatsApp is full of messages from school",
    "I was on WhatsApp all day",
    "tell me a joke",
    "what is the capital of France",
    "I don't want to play right now",
    "Saturn is my favorite planet",
    "I graphed a function in class today",
    "the volume at the concert was too loud",
    "should I open a bank account",
    "is it going to rain",
]


@pytest.mark.parametrize("sentence", CONVERSATION)
def test_conversation_does_not_act(sentence):
    result, actions = route(sentence)
    assert not result and not actions, f"{sentence!r} triggered {result!r} {actions}"


@pytest.mark.parametrize("sentence", CONVERSATION)
def test_conversation_gets_no_tools(sentence):
    """The AI isn't even offered tools for small talk, so it can't decide to open something."""
    tools, _choice = app.select_tools(sentence)
    assert not tools, f"{sentence!r} offered tools {[t['function']['name'] for t in tools]}"


# ---- real requests still work ----
def test_open_app_launches_it():
    result, actions = route("open Chrome")
    assert result and any("chrome" in a.lower() for a in actions)   # Windows names it "chrome"


def test_timer():
    result, _ = route("set a timer for 10 minutes")
    assert "10 minutes" in str(result)
    assert app.timer_manager.snapshot()   # really running
    app.timer_manager.cancel(everything=True)


def test_math_is_solved_by_jervis_not_the_ai():
    result, actions = route("solve 2x + 4 = 24")
    assert "x equals 10" in str(result)
    assert not actions


def test_graph_and_planet_are_handled_directly():
    assert "trigonometric" in str(route("graph sine of x over x")[0]).lower()
    assert "Saturn" in str(route("tell me about Saturn")[0])


def test_netflix_episode_is_parsed():
    assert app.parse_service_request("play Breaking Bad season 3 episode 2 on Netflix", "netflix") == \
        ("breaking bad", "series", 3, 2)


def test_whatsapp_requests_still_work():
    assert app.parse_whatsapp_request("do I have unread WhatsApp messages") == {"action": "check", "name": ""}
    assert app.parse_whatsapp_request("read my WhatsApp messages from Mom") == {"action": "read_chat", "name": "mom"}


# ---- "Open Spotify" -> "What would you like to listen to?" ----
def test_followup_answer_is_used_as_the_answer():
    app.pending_spotify_request = {"at": app.time.time()}
    route("Bohemian Rhapsody")
    assert app.pending_spotify_request is None   # consumed as the song to play


def test_followup_yields_to_a_different_request():
    """Answering "What would you like to listen to?" with a request for another service does that instead."""
    app.pending_spotify_request = {"at": app.time.time()}
    assert app.is_new_command("play Breaking Bad season 3 episode 2 on Netflix", "spotify")
    assert app.is_new_command("set a timer for 5 minutes", "spotify")
    assert not app.is_new_command("Bohemian Rhapsody by Queen", "spotify")



def test_spotify_without_keys_uses_the_spotify_app(monkeypatch):
    """No Spotify keys (every installed copy): Jervis searches in the Spotify app itself and presses play there."""
    import sys
    import time
    from types import SimpleNamespace
    import spotify_local
    monkeypatch.setattr(app, "sp", None)
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    result, actions = route('play "My Favorite Songs" playlist on spotify')
    assert "not configured" not in str(result)
    assert "spotify front" in actions
    if sys.platform == "darwin":
        assert "spotify type my favorite songs" in actions
        assert "spotify keys shift+enter" in actions
