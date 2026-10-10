"""Things Jarvis got wrong in one real evening of use (a friend's first session, on Windows), each one as it was said
or typed there, and what he does now. Nothing is opened, played or fetched: the sandbox records instead."""
import time

import pytest

import earth
import graphs
import images
import local_llm
import sandbox

app = None
PLACES = {"new york": {"name": "New York, United States", "country": "United States", "lat": 40.71427, "lon": -74.00597, "timezone": "America/New_York"},
          "paris": {"name": "Paris, France", "country": "France", "lat": 48.85341, "lon": 2.3488, "timezone": "Europe/Paris"}}


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture
def jarvis(monkeypatch):
    """say(text) -> (his answer, the graphs and globes sent to the window)."""
    shown = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: shown.append(payload))
    monkeypatch.setattr(app, "speak", lambda *a, **k: None)
    monkeypatch.setattr(earth, "resolve", lambda name: (PLACES.get(name.lower()), None))
    monkeypatch.setattr(app, "last_function", {"tree": None, "at": 0.0, "equation": None})
    monkeypatch.setattr(app, "pending_graph_ask", {"at": 0.0})
    monkeypatch.setattr(app, "pending_earth_places", {"at": 0.0, "left": 0})
    monkeypatch.setattr(app, "chat_history", [])

    def say(text):
        shown.clear()
        return app.handle_direct_command(text), [p for p in shown if p.get("type") in ("graph", "globe")]
    return say


# ---------------------------------------------------------------- graphs
def test_the_word_graph_after_the_equation_draws_it(jarvis):
    reply, drawn = jarvis("y = 2x +2x^2 +6767 graph")
    assert len(drawn) == 1 and drawn[0]["data"]["plain"].startswith("y = 2x²") and reply.startswith("Here's your parabola")


def test_the_equation_given_after_jarvis_asked_for_it_is_drawn(jarvis):
    assert jarvis("create a graph")[0] == graphs.ASK_FOR_EQUATION
    reply, drawn = jarvis("y=2x+2x 2 +6767.")
    assert len(drawn) == 1 and reply.startswith("Here's your parabola")
    # …and only then: once answered, a bare formula is no longer taken for an answer to anything
    assert jarvis("x^3 - 3x")[1] == []


def test_a_squared_that_lost_its_raised_two_is_still_a_square(jarvis):
    reply, drawn = jarvis("create a graph y=2x+2x 2 +6767.")
    assert drawn[0]["data"]["plain"] == "y = 2x² + 2x + 6767" and "parabola" in reply     # not the line y = 6x + 6767


def test_two_functions_at_once_get_a_graph_each(jarvis):
    reply, drawn = jarvis("create a graph y=x^2 and g = x+ 1")
    assert [d["data"]["plain"] for d in drawn] == ["y = x²", "y = x + 1"]
    assert reply.startswith("I drew 2 graphs, one for each function: y = x² and y = x + 1.") and "arrows" in reply
    reply, drawn = jarvis("graph sine of x and cosine of x")
    assert [d["data"]["plain"] for d in drawn] == ["y = sin(x)", "y = cos(x)"]


def test_one_readable_function_out_of_two_is_drawn_and_the_other_asked_for(jarvis):
    reply, drawn = jarvis("create a graph y=x^2 and g = X = 1")
    assert len(drawn) == 1 and reply.startswith("I could only read one of those as a function of x, so I drew y = x².")


def test_a_function_written_out_on_its_own_is_drawn(jarvis):
    assert len(jarvis("y = x^2")[1]) == 1
    assert jarvis("2x + 4 = 24")[1] == []          # an equation to solve stays an equation to solve
    assert jarvis("I failed the graph in class")[1] == []


# ---------------------------------------------------------------- the globe
def test_the_same_place_twice_is_said_back(jarvis):
    reply, drawn = jarvis("What is the distance between New York and New York?")
    assert reply == "I heard New York twice. Which two places do you mean?" and not drawn


def test_which_two_places_stays_open_across_something_else_said(jarvis, monkeypatch):
    monkeypatch.setattr(app, "ask_jarvis", lambda *a, **k: "ai")
    assert jarvis("What is the distance between New York and New York?")[0].endswith("Which two places do you mean?")
    assert jarvis("Do you remember that I stuck on these?")[0] is None       # not an answer: left to the AI
    reply, drawn = jarvis("new york and paris")
    assert len(drawn) == 1 and "New York" in reply and "Paris" in reply and "kilometers" in reply


def test_the_question_does_not_stay_open_forever(jarvis):
    jarvis("show me the distance on the globe")
    assert jarvis("hello there")[0] is None and jarvis("how are you")[0] is None
    assert jarvis("salt and pepper")[1] == []


# ---------------------------------------------------------------- the phone
@pytest.mark.parametrize("said", ["coonnect my phone", "coonnect to my phone", "conect my phone", "Connect my phone"])
def test_connect_my_phone_however_it_was_typed(monkeypatch, said):
    monkeypatch.setattr(app, "start_phone_pairing", lambda: "pairing")
    assert app.handle_direct_command(said) == "pairing"


def test_pairing_waits_a_moment_for_the_relay_that_is_still_signing_in(monkeypatch):
    monkeypatch.setattr(app, "phone_control_mode", lambda: "on")
    monkeypatch.setattr(app, "send_ui_update", lambda *a, **k: None)
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(app.relay, "_loop", object())            # the relay client is running…
    monkeypatch.setattr(app.relay, "_ws", None)                  # …and not connected yet
    naps = []

    def nap(seconds):                                            # it connects during the wait
        naps.append(seconds)
        if len(naps) == 3:
            app.relay._ws = object()
    monkeypatch.setattr(app.time, "sleep", nap)
    assert "with Scan in the Jarvis app" in app.start_phone_pairing() and len(naps) == 3
    # with no relay client running at all (or none configured), nothing is waited for
    naps.clear()
    monkeypatch.setattr(app.relay, "_loop", None)
    monkeypatch.setattr(app.relay, "_ws", None)
    assert "same Wi-Fi" in app.start_phone_pairing() and naps == []


# ---------------------------------------------------------------- pictures
@pytest.mark.parametrize("said", ["whats is it", "wha t is it", "what is it", "what's this?", "what is in the picture"])
def test_what_is_it_right_after_a_picture_looks_at_the_picture(monkeypatch, said):
    asked = []
    monkeypatch.setattr(images, "has_pending_context", lambda: True)
    monkeypatch.setattr(images, "just_received_image", lambda *a: True)
    monkeypatch.setattr(app, "tool_analyze_image", lambda question="": asked.append(question) or "A cat on a sofa.")
    assert app.handle_image_command(said) == "A cat on a sofa." and asked
    monkeypatch.setattr(images, "just_received_image", lambda *a: False)    # later in the conversation it means something else
    assert app.handle_image_command(said) is None


# ---------------------------------------------------------------- timers
def test_stop_timer_after_one_went_off_silences_it_and_cancels_nothing_else(monkeypatch):
    sent, cancelled = [], []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: sent.append(payload))
    monkeypatch.setattr(app, "deliver_alert", lambda payload: True)
    monkeypatch.setattr(app, "notify", lambda *a: None)
    monkeypatch.setattr(app.timer_manager, "snapshot", lambda: [{"id": 9, "label": "", "kind": "timer", "total": 300, "end": time.time() + 200}])
    monkeypatch.setattr(app.timer_manager, "cancel", lambda label="", everything=False: cancelled.append(label) or [])
    app.on_timer_fired({"id": 1, "label": "", "kind": "timer", "total": 60, "end": time.time()})
    assert app.handle_timer_command("stop timer") == "Your 1 minute timer already finished. I've silenced it."
    assert sent == [{"type": "dismiss_alert"}] and cancelled == []          # the 5 minute one keeps running
    app.handle_timer_command("stop timer")                                  # said again: now it means the running one
    assert cancelled == [""]


# ---------------------------------------------------------------- the AI
class _Rejected(Exception):
    status_code = 400

    def __init__(self, message, generation=""):
        super().__init__(message)
        self.body = {"error": {"message": message, "code": "tool_use_failed", "failed_generation": generation}}


def test_an_ai_that_reaches_for_a_tool_it_wasnt_given_is_asked_again_with_its_tools(monkeypatch):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if not kwargs.get("tools"):
                raise _Rejected("Tool choice is none, but model called a tool", '{"name": "show_distance"}')
            return "answered with tools"
    monkeypatch.setattr(app, "groq_client", type("C", (), {"chat": type("Ch", (), {"completions": Completions()})()})())
    monkeypatch.setattr(app, "LLM_BACKEND", "auto")
    monkeypatch.setattr(app, "groq_down_until", 0.0)
    monkeypatch.setattr(app, "log_ai_error", lambda e: None)
    monkeypatch.setattr(local_llm, "chat", lambda **k: pytest.fail("the small local AI was used instead"))
    out = app.groq_chat(model="m", messages=[{"role": "user", "content": "new york and paris"}], tools_if_wanted=[{"type": "function"}])
    assert out == "answered with tools" and len(calls) == 2
    assert calls[1]["tools"] == [{"type": "function"}] and calls[1]["tool_choice"] == "auto" and "tools_if_wanted" not in calls[0]


def test_the_local_ai_never_starts_its_answer_with_its_own_roles_name():
    assert local_llm.clean_reply("assistant It's the number 2.") == "It's the number 2."
    assert local_llm.clean_reply("assistant assistant assistant The image is a cat.") == "The image is a cat."
    assert local_llm.clean_reply("Assistants like me can help.") == "Assistants like me can help."
    assert local_llm.clean_reply("An assistant is here.") == "An assistant is here."


def test_talk_about_someone_else_is_not_corrected_as_a_bad_command(monkeypatch):
    said = "No, he's doing it on the screen. Oh, he's a guy."
    assert app.is_computer_request(said) and app._ABOUT_SOMEONE_ELSE.search(said)
    assert not app._ABOUT_SOMEONE_ELSE.search("click the button on the screen")
    reply = type("R", (), {"choices": [type("Ch", (), {"message": type("M", (), {"content": "Sounds like he's busy!", "tool_calls": None})()})()]})()
    monkeypatch.setattr(app, "groq_chat", lambda **k: reply)
    assert app.ask_jarvis([{"role": "system", "content": "s"}, {"role": "user", "content": said}], said) == "Sounds like he's busy!"


# ---------------------------------------------------------------- YouTube
def test_a_title_youtube_has_nothing_for_is_said_so(monkeypatch):
    opened = []
    monkeypatch.setattr(app, "_find_video_yt_dlp", lambda q: None)
    monkeypatch.setattr(app, "open_youtube", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(app, "_find_video_scrape", lambda q: app.NO_VIDEO)
    assert app.play_youtube_video("a song nobody made") == "YouTube has no video called a song nobody made. Check the spelling, or tell me who it's by."
    assert opened == []
    monkeypatch.setattr(app, "_find_video_scrape", lambda q: None)          # couldn't read the page: the results are opened, as before
    assert "opened YouTube results" in app.play_youtube_video("echoes") and len(opened) == 1
