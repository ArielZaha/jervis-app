"""The phone's own copy of Jarvis's brain (phone_brain.py, run inside the phone's browser): it must answer exactly
as Jarvis on the computer does, since it is the same modules with different glue. Each sentence here goes through
both, and the words and the picture (graph, globe, planet) must match. Place lookups are simulated (no network)."""
import time

import pytest

import earth
import forecast
import phone_brain
import sandbox

app = None

PLACES = {
    "tokyo": {"name": "Tokyo, Japan", "country": "Japan", "lat": 35.6895, "lon": 139.69171, "timezone": "Asia/Tokyo"},
    "new york": {"name": "New York, United States", "country": "United States", "lat": 40.71427, "lon": -74.00597, "timezone": "America/New_York"},
    "tel aviv": {"name": "Tel Aviv, Israel", "country": "Israel", "lat": 32.08088, "lon": 34.78057, "timezone": "Asia/Jerusalem"},
    "london": {"name": "London, England, United Kingdom", "country": "United Kingdom", "lat": 51.50853, "lon": -0.12574, "timezone": "Europe/London"},
    "haifa": {"name": "Haifa, Haifa District, Israel", "country": "Israel", "lat": 32.81841, "lon": 34.9885, "timezone": "Asia/Jerusalem"},
}
VALENCIAS = [{"name": "Valencia, Carabobo, Venezuela", "country": "Venezuela", "lat": 10.16202, "lon": -68.00765, "timezone": "America/Caracas"},
             {"name": "Valencia, Spain", "country": "Spain", "lat": 39.46975, "lon": -0.37739, "timezone": "Europe/Madrid"}]


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture
def both(monkeypatch):
    """Says one sentence to the computer's Jarvis and to the phone's brain; returns ((reply, picture), (reply, picture))."""
    def resolve(name):
        if name.lower() == "valencia":
            return None, VALENCIAS
        return PLACES.get(name.lower()), None
    monkeypatch.setattr(earth, "resolve", resolve)
    monkeypatch.setattr(earth, "geocode", lambda name: PLACES.get(name.lower()))
    monkeypatch.setattr(earth, "_sun_now", lambda: {"lat": 0.0, "lon": 0.0, "at": "2026-10-10T12:00:00Z"})
    shown = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: shown.append(payload))
    monkeypatch.setattr(app, "last_function", {"tree": None, "at": 0.0, "equation": None})
    monkeypatch.setattr(app, "pending_earth_choice", None)
    monkeypatch.setattr(app, "last_globe_route", {"a": None, "b": None, "at": 0.0})
    monkeypatch.setattr(app, "pending_earth_places", {"at": 0.0})
    monkeypatch.setattr(app, "chat_history", [])
    brain = phone_brain.Brain()

    def say(text):
        shown.clear()
        computer = app.handle_direct_command(text)
        picture = next((p for p in shown if p.get("type") in ("graph", "globe", "planet")), None)
        phone = brain.handle(text)
        return (computer, picture), (phone.get("reply"), phone.get("visual"))
    return say


@pytest.mark.parametrize("sentence", [
    "solve 2x + 4 = 24",
    "what are the roots of x squared minus 9",
    "solve x^2 + x + 1 = 0",
    "solve 3x^2 - 5x - 1 = 0",
    "graph sine of x over x",
    "plot y = x^2 - 4",
    "graph tan x",
    "graph x cubed minus 3x",
    "what is 2x + 6 = 0, draw the graph",
    "drew the greph of x squared",
    "tell me about Saturn",
    "tell my about seturn",
    "show me the moon",
    "what is the distance between Tokyo and New York",
    "the distence between tel aviv and london",
    "how long is the flight from Tel Aviv to New York?",
    "which is farther from Tel Aviv, London or New York?",
    "cities within 100 km of Haifa",
    "what is the distance between Atlantis and London",
])
def test_the_phone_answers_as_the_computer_does(both, sentence):
    computer, phone = both(sentence)
    assert computer[0], f"the computer's Jarvis has no direct answer for {sentence!r}"
    assert phone[0] == computer[0]
    assert phone[1] == computer[1]


def test_follow_ups_about_the_math_keep_working(both):
    both("plot y = x^2 - 4")
    for follow in ("what is the vertex?", "what are its roots?", "show the steps", "what is the y intercept of it?"):
        computer, phone = both(follow)
        assert computer[0] and phone[0] == computer[0], follow
    both("solve 2x + 4 = 24")
    computer, phone = both("draw the function")
    assert phone[0] == computer[0] and phone[1] == computer[1] and phone[1]["type"] == "graph"


def test_an_ambiguous_place_is_asked_about_then_answered(both):
    computer, phone = both("what is the distance between Valencia and London")
    assert phone[0] == computer[0] == "Which Valencia do you mean: Valencia, Carabobo, Venezuela, or Valencia, Spain?"
    computer, phone = both("the one in Spain")
    assert phone[0] == computer[0] and phone[1] == computer[1]
    assert phone[1]["data"]["a"]["name"] == "Valencia, Spain"


def test_a_route_follow_up_uses_the_last_route(both):
    both("what is the distance between Tel Aviv and London")
    computer, phone = both("which countries does it fly over?")
    assert phone[0] == computer[0] and "Greece" in phone[0]


def test_which_two_places_then_the_answer(both):
    computer, phone = both("show me the distance on the globe")
    assert phone[0] == computer[0] == "Which two places? For example: what's the distance between Tokyo and Paris."
    computer, phone = both("Tokyo and New York")
    assert phone[0] == computer[0] and phone[1] == computer[1]


def test_the_sun_is_answered_with_a_globe():
    brain = phone_brain.Brain()
    out = brain.handle("show me Earth at night")
    assert out["visual"]["data"]["mode"] == "sun" and out["reply"].startswith("Here's the night side of Earth right now")
    out = brain.handle("where is it daytime right now?")
    assert "the Sun is straight overhead at" in out["reply"]


def test_sunrise_is_said_in_the_places_own_time(monkeypatch):
    monkeypatch.setattr(earth, "resolve", lambda name: (PLACES.get(name.lower()), None))
    out = phone_brain.Brain().handle("show sunrise over Tokyo")
    assert out["visual"]["data"]["what"] == "sunrise"
    assert "The Sun rises in Tokyo at" in out["reply"] and "AM local time" in out["reply"]


def test_seeing_something_again_and_closing_it():
    brain = phone_brain.Brain()
    assert brain.handle("show the graph again")["reply"] == "I haven't drawn a graph yet. Give me a function and I'll draw it."
    brain.handle("graph x squared")
    again = brain.handle("show the graph again")
    assert again["visual"] == {"type": "show_graph", "which": "last"} and again["reply"] == "Here is the graph again."
    assert brain.handle("show the previous graph")["visual"] == {"type": "show_graph", "which": "prev"}
    assert brain.handle("close the graph")["visual"] == {"type": "close_graph"}


# ---------------------------------------------------------------- timers: read here, kept by the app
def test_timers_are_read_the_way_the_computer_reads_them():
    brain = phone_brain.Brain()
    out = brain.handle("set a 30 second timer for the eggs")
    assert out["reply"] == "Timer set for 30 seconds, for eggs."
    assert out["timer"] == {"action": "set", "label": "eggs", "kind": "timer", "total": 30,
                            "done": {"message": "Your 30 seconds timer for eggs is done.",
                                     "spoken": "Time's up. Your 30 seconds timer for eggs is done."}}
    out = brain.handle("remind me in an hour to call Mom")
    assert out["reply"] == "Okay, I'll remind you to call mom in 1 hour."
    assert out["timer"]["kind"] == "reminder" and out["timer"]["total"] == 3600
    assert out["timer"]["done"] == {"message": "Reminder: call mom.", "spoken": "Reminder: call mom."}
    assert brain.handle("set a timer for 10 seconeds")["timer"]["total"] == 10   # the typo is fixed first
    assert brain.handle("set a timer")["reply"] == "How long should I set it for?"


def test_asking_about_and_cancelling_timers_uses_the_apps_list():
    brain = phone_brain.Brain()
    now = time.time()
    running = [{"id": 7, "label": "eggs", "kind": "timer", "total": 600, "end": now + 300.4},
               {"id": 8, "label": "", "kind": "timer", "total": 60, "end": now + 31}]
    assert brain.handle("how much time is left?", {"timers": running[:1]})["reply"] == "The 10 minutes timer for eggs has 5 minutes left."
    assert brain.handle("how much time is left?", {"timers": []}).get("reply") is None    # no timers: not a timer question
    out = brain.handle("cancel the eggs timer", {"timers": running})
    assert out["timer"] == {"action": "cancel", "ids": [7]} and out["reply"] == "Cancelled the 10 minutes timer for eggs."
    out = brain.handle("cancel the timer", {"timers": running})
    assert out["timer"]["ids"] == [8]   # the one ending soonest
    out = brain.handle("cancel all timers", {"timers": running})
    assert sorted(out["timer"]["ids"]) == [7, 8] and out["reply"] == "Cancelled all 2 timers."
    assert brain.handle("cancel the timer", {"timers": []})["reply"] == "You don't have any timers running."


# ---------------------------------------------------------------- weather and music
def test_weather_is_fetched_for_the_place_asked_or_the_saved_city(monkeypatch):
    asked = []
    data = {"place": {"name": "Paris, France"}, "now": {"temp": 18}}
    monkeypatch.setattr(forecast, "get", lambda city="", fallback_city="", radar=True, refresh=False: asked.append((city, fallback_city, radar)) or data)
    monkeypatch.setattr(forecast, "summary", lambda d: "It's 18 degrees in Paris.")
    brain = phone_brain.Brain()
    out = brain.handle("how's the weather in Paris?", {"weatherCity": "Haifa"})
    assert out["reply"] == "It's 18 degrees in Paris." and out["weather"] is data
    assert asked == [("paris", "Haifa", False)]
    assert brain.handle("what's the weather?", {"weatherCity": "Haifa"})["weather"] is data and asked[-1][0] == ""
    assert brain.handle("I was talking about the weather yesterday").get("reply") is None


def test_weather_that_cant_be_loaded_says_why(monkeypatch):
    def fail(**kwargs):
        raise forecast.WeatherError("I couldn't find a place called atlantis.")
    monkeypatch.setattr(forecast, "get", fail)
    out = phone_brain.Brain().handle("what's the weather in Atlantis?")
    assert out["reply"] == "I couldn't find a place called atlantis." and "weather" not in out


def test_music_is_read_and_left_to_the_app_to_play():
    brain = phone_brain.Brain()
    out = brain.handle("play my Workout playlist")
    assert out["music"]["query"] == "Workout" and out["music"]["kind"] == "playlist" and out["music"]["mine"] is True
    assert "reply" not in out
    assert brain.handle("play the repeat playlist")["music"]["mix"] == "On Repeat"
    assert brain.handle("shuffle my liked songs")["music"] == {**brain.handle("shuffle my liked songs")["music"], "kind": "liked", "shuffle": True}
    assert brain.handle("play OK Computer on Apple Music")["music"]["service"] == "apple_music"
    assert brain.handle("play the album OK Computer by Radiohead")["music"]["by"] == "Radiohead"
    assert "music" not in brain.handle("play Bohemian Rhapsody")   # a plain song: the app's own song handling


def test_anything_else_is_left_alone_with_its_typos_fixed():
    out = phone_brain.Brain().handle("genearte an imgae of a dog in space")
    assert out == {"text": "generate an image of a dog in space"}
    assert phone_brain.Brain().handle("what's the capital of France?") == {"text": "what's the capital of France?"}
