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
    for name in ("pending_spotify_request", "pending_spotify_play", "pending_google_search", "pending_netflix_request",
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
        assert "spotify type My Favorite Songs" in actions
        assert "spotify keys shift+enter" in actions


@pytest.mark.parametrize("said", ["Wake up Jervis", "Hey Jervis", "Hello Jervis", "hello jarvis", "hey jarvis can you hear me"])
def test_wake_phrases(said):
    assert app.is_wake_command(said)


@pytest.mark.parametrize("said", ["take control on my computer and open Chrome", "take control over my computer and open Chrome",
                                  "take control of my computer and open Chrome", "control my computer and open Chrome"])
def test_take_control_recognizes_on_over_and_of(said):
    """"Take control ON/OVER my computer" must be understood exactly like "take control OF my computer" — a request
    phrased with a different preposition is still a real computer-control request, not a question to answer in chat."""
    assert app.is_computer_request(said)
    assert app.parse_computer_task(said) == "open Chrome"


@pytest.mark.parametrize("hour,part", [(6, "morning"), (11, "morning"), (12, "noon"), (13, "afternoon"),
                                       (17, "afternoon"), (18, "evening"), (23, "evening"), (2, "evening")])
def test_time_greeting_matches_the_hour(monkeypatch, hour, part):
    from datetime import datetime as real_datetime

    class FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 1, 1, hour, 0)
    monkeypatch.setattr(app, "datetime", FixedDatetime)
    monkeypatch.delenv("JERVIS_USER_NAME", raising=False)
    assert app.time_greeting() == f"Good {part}, Sir. How can I help you today?"


def test_time_greeting_uses_the_users_name_once_set(monkeypatch):
    monkeypatch.setenv("JERVIS_USER_NAME", "Ariel")
    assert app.time_greeting().startswith("Good ") and ", Ariel." in app.time_greeting()


@pytest.mark.parametrize("said", ["goodbye jervis", "bye jervis", "have a good day jervis", "goodbye", "bye",
                                  "have a good day", "have a nice day"])
def test_farewell_phrases_put_him_to_sleep(said):
    assert app.is_shutdown_command(said)


@pytest.mark.parametrize("said", ["hello", "hi there", "hey", "this is a hint", "I said hello to my brother"])
def test_greetings_without_his_name_dont_wake_him(said):
    assert not app.is_wake_command(said)


def test_closing_the_window_puts_him_to_sleep_and_the_wake_phrase_greets():
    app.awake = True
    app.set_window_visible(False)
    assert app.awake is False and app.window_visible is False
    app.set_window_visible(True)
    assert app.time_greeting().startswith("Good ") and app.time_greeting().endswith("Sir. How can I help you today?")


def test_with_the_window_closed_only_his_name_opens_it_and_he_greets(monkeypatch):
    """Jervis's real listening loop, with the microphone replaced by what was said."""
    said = iter(["some chatter about dinner", "hello", "Hey Jervis"])

    class Done(Exception):
        pass

    def heard(passive=False):
        try:
            return next(said)
        except StopIteration:
            raise Done
    spoken, opened = [], []
    monkeypatch.setattr(app, "listen", heard)
    monkeypatch.setattr(app, "speak", spoken.append)
    monkeypatch.setattr(app, "broadcast", lambda *a, **k: None)
    monkeypatch.setattr(app, "send_status", lambda status: None)
    monkeypatch.setattr(app, "show_fullscreen", lambda: opened.append(True))
    monkeypatch.delenv("JERVIS_WAKE_WORD", raising=False)
    app.awake = True
    app.set_window_visible(False)   # the window was closed: he's asleep, listening for his name
    with pytest.raises(Done):
        app.main_loop()
    assert spoken == [app.time_greeting()]
    assert opened == [True]


def test_typos_in_commands_are_understood():
    assert app.fix_typos("take contorl over my computr") == "take control over my computer"
    assert app.fix_typos("play it on spotfy") == "play it on spotify"
    assert app.fix_typos("I like my dog") == "I like my dog"


@pytest.mark.parametrize("said", ["search for Jane! on Spotify", "look up Jane! in spotify"])
def test_spotify_search_goes_to_spotify_and_play_it_plays_it(said, monkeypatch):
    import time
    from types import SimpleNamespace
    import spotify_local
    monkeypatch.setattr(app, "sp", None)
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    result, actions = route(said)
    assert "Jane!" in result and "play it" in result
    assert "spotify search Jane!" in actions
    assert not any("computer" in a for a in actions)
    sandbox.reset()
    result, actions = route("yes play it")
    assert "spotify front" in actions


@pytest.mark.parametrize("reply", [
    "The search bar says \"Searching for Jane!\".",
    "I'm using the computer to search for the song \"Jane!\" in Spotify. The result is a list of tracks.",
    "The song \"Jane!\" by Janis Ian starts playing on Spotify.",
    "I will now take control of your computer and play Jain's Song by Peter Gabriel.\n\nPlaying Jain's Song by Peter Gabriel.",
    "Please type \"confirm\" to proceed with taking control of your computer.",
])
def test_replies_claiming_actions_that_never_happened_are_caught(reply):
    assert app._CLAIMS_ACTION.search(reply)


def test_action_request_answered_in_text_without_a_tool_call_is_never_shown(monkeypatch):
    """If the model answers a plainly action-shaped request in free text instead of calling a tool — for whatever
    reason — that text (however plausible-sounding, even a fake back-and-forth about "confirming") must never
    reach the user: it's an untrustworthy hallucination by construction, not a real result."""
    from types import SimpleNamespace

    fake_message = SimpleNamespace(
        content=("I'd like to clarify with you before I do anything... Please confirm that you'd like me to start "
                 "controlling your computer."),
        tool_calls=None)
    fake_response = SimpleNamespace(choices=[SimpleNamespace(message=fake_message)])
    monkeypatch.setattr(app, "groq_chat", lambda **kwargs: fake_response)
    reply = app.ask_jervis([{"role": "system", "content": "x"}], "take control on my computer and play Jane on Spotify")
    assert "didn't do anything on your computer" in reply
    assert "clarify" not in reply and "confirm" not in reply


@pytest.mark.parametrize("reply", [
    "Paris is the capital of France.",
    "A timer counts down and rings when it's done.",
    "I can open apps, play music and set timers.",
])
def test_ordinary_answers_are_not_mistaken_for_claims(reply):
    assert not app._CLAIMS_ACTION.search(reply)


@pytest.mark.parametrize("said", [
    "take contorl on my computer and play Jane! on spotify",
    "take contorl over my computer and type in the search bar for Jane! in spotify.",
    "take the contorl and search for the song Jane! in spotify.",
])
def test_take_control_and_spotify_is_done_visibly_step_by_step(said, monkeypatch):
    """Asked to take control: Jervis shows the process (pointer, letter-by-letter typing, results, play)."""
    import time
    from types import SimpleNamespace
    import spotify_local
    monkeypatch.setattr(app, "sp", None)
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    monkeypatch.setattr(app, "computer_environment", lambda: SimpleNamespace(available=lambda: (True, "")))
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: None)
    result, actions = route(said)
    assert "I'm using the computer to play Jane! on Spotify" in result
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state in ("completed", "error", "stopped"):
            break
        time.sleep(0.02)
    actions = list(sandbox.actions)   # the task runs on its own thread: read what it did once it's finished
    typed = [a for a in actions if a.startswith("spotify type ")]
    assert "spotify front" in actions and "spotify keys cmd+k" in actions
    assert "".join(a[len("spotify type "):] for a in typed) == "Jane!" and len(typed) == 5   # letter by letter
    assert "spotify keys shift+enter" in actions and any(a.startswith("pointer to") for a in actions)
    app.computer_task = None


def test_take_control_stays_visible_even_with_spotify_keys_configured(monkeypatch):
    """With Spotify developer keys set up (Settings, Optional services), an ordinary "play X on Spotify" uses the
    fast online API — but "take control ... and play X on Spotify" asked explicitly to watch it happen, so it must
    still go through the mouse-and-keyboard flow, never silently answer through the API instead."""
    import time
    from types import SimpleNamespace
    import spotify_local
    fake_sp = SimpleNamespace(search=lambda **k: (_ for _ in ()).throw(AssertionError("the online API was called")))
    monkeypatch.setattr(app, "sp", fake_sp)
    monkeypatch.setenv("JERVIS_COMPUTER_CONTROL", "on")
    monkeypatch.setattr(app, "computer_environment", lambda: SimpleNamespace(available=lambda: (True, "")))
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: None)
    result, actions = route("take control on my computer and play Jane! on spotify")
    assert "I'm using the computer to play Jane! on Spotify" in result
    for _ in range(200):
        if app.computer_task is not None and app.computer_task.state in ("completed", "error", "stopped"):
            break
        time.sleep(0.02)
    actions = list(sandbox.actions)
    assert "spotify front" in actions and "spotify keys cmd+k" in actions
    app.computer_task = None


@pytest.mark.parametrize("query,playing,should_match", [
    ("Jane", "Boys Don't Cry by The Cure", False),          # the exact bug once reported: an unrelated song
    ("Joy Of A Toy", "Joy Of A Toy by Soft Machine", True),
    ("Bohemian Rhapsody", "Bohemian Rhapsody by Queen", True),
])
def test_spotify_wont_call_an_unrelated_song_a_success(query, playing, should_match):
    import spotify_local
    assert spotify_local._looks_like_a_match(query, playing) is should_match


def test_visible_spotify_play_refuses_to_report_an_unrelated_song(monkeypatch):
    """Shift+Enter can only play whatever Spotify already has selected — if that turns out not to match the
    request (a stale selection, a slow search), Jervis must say so instead of announcing it as a success."""
    import time
    from types import SimpleNamespace
    import spotify_local
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(spotify_local, "now_playing", lambda: (True, "Boys Don't Cry by The Cure"))
    monkeypatch.setattr(spotify_local, "_mac_now", lambda: ("playing", "spotify:track:xyz", "Boys Don't Cry by The Cure"))
    steps = spotify_local.visible_steps("Jane")
    names = dict(steps)
    for name, action in steps:
        if name != "Playing it":
            action()
    with pytest.raises(spotify_local.SpotifyLocalError, match="doesn't look like a match"):
        names["Playing it"]()
    app.computer_task = None


def test_visible_spotify_uses_sight_when_screen_vision_is_available(monkeypatch):
    """With screen vision turned on (and available), Spotify's search bar and the matching result are found by
    actually looking at a screenshot and clicked for real — not guessed at with Cmd+K / Shift+Enter."""
    import time
    from types import SimpleNamespace
    import spotify_local
    import screen_vision

    class FakeShot:
        def crop(self, box):
            return self   # a fake "cropped" screenshot: FakeVision doesn't actually inspect the image content

    class FakeObservation:
        screenshot = FakeShot()   # anything not None: "a screenshot was taken"
        screen_size = (1440, 900)

    class FakeEnv:
        def observe(self):
            return FakeObservation()

        def click(self, point, button="left", double=False):
            clicked.append(point)
            return ""

    class FakeVision:
        def locate(self, image, description, screen_size):
            return (300, 200) if "What do you want to play" in description else (300, 400)

    clicked = []
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    monkeypatch.setattr(screen_vision, "available", lambda: True)
    monkeypatch.setattr(screen_vision, "ScreenVision", FakeVision)
    monkeypatch.setattr(spotify_local, "_screen", lambda: FakeEnv())
    monkeypatch.setattr(spotify_local, "now_playing", lambda: (True, "Jane! by Someone"))
    monkeypatch.setattr(spotify_local, "_mac_now", lambda: ("playing", "spotify:track:new", "Jane! by Someone"))
    steps = spotify_local.visible_steps("Jane!")
    names = [n for n, _ in steps]
    assert names == ["Opening Spotify", "Clicking the search bar", "Typing “Jane!”", "Searching",
                     "Pointing at the results", "Playing it"]
    result = None
    for name, action in steps:
        result = action()
    assert clicked == [(300, 200), (300, 400)]           # the search bar, then the matching result — real clicks
    typed = [a for a in sandbox.actions if a.startswith("spotify type ")]
    assert "".join(a[len("spotify type "):] for a in typed) == "Jane!"
    assert "spotify keys cmd+k" not in sandbox.actions    # no shortcut guessing when sight is available
    assert result == "Playing Jane! by Someone on Spotify."


def test_without_take_control_spotify_is_played_quickly(monkeypatch):
    import time
    from types import SimpleNamespace
    import spotify_local
    monkeypatch.setattr(app, "sp", None)
    monkeypatch.setattr(spotify_local, "time", SimpleNamespace(sleep=lambda s: None, time=time.time))
    result, actions = route("play Jane! on spotify")
    assert "spotify type Jane!" in actions            # typed at once, no pointer moves
    assert not any(a.startswith("pointer to") for a in actions)
