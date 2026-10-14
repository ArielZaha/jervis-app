"""The world clock (worldclock.py and its place in app.py): which sentences ask for the time somewhere, which place is
meant, and that the time said is the time-zone database's, at fixed moments so the answers never drift."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import sandbox
import worldclock

app = None
HOME = ZoneInfo("Asia/Jerusalem")


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    sandbox.reset()
    app.clock_state.update(open=False, places=[], at=0.0)
    app.pending_clock_choice = None
    app.last_place_asked.update(name="", place=None, at=0.0)
    monkeypatch.setattr(app, "ws_loop", None)   # no window, unless a test opens one


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def place(name):
    outcome, found = worldclock.resolve(name, lambda _name: (None, None))
    assert outcome == "ok", name
    return found


# ---- which sentences are about the time somewhere, right now ----
@pytest.mark.parametrize("said,places", [
    ("Jarvis, what time is it in Tokyo?", ["tokyo"]),
    ("What time is it in New York?", ["new york"]),
    ("What's the current time in London?", ["london"]),
    ("Tell me the time in Tokyo.", ["tokyo"]),
    ("Open the clock for New York.", ["new york"]),
    ("time in dubai", ["dubai"]),
    ("what time is it in london, tokyo and sydney", ["london", "tokyo", "sydney"]),
    ("what time is it in london tokyo and sydney", ["london", "tokyo", "sydney"]),
    ("Compare the time in Israel and Los Angeles.", ["israel", "los angeles"]),
    ("Show me London and Tokyo side by side.", ["london", "tokyo"]),
    ("What is the time difference between Israel and California?", ["israel", "california"]),
    ("how many hours ahead is tokyo", ["tokyo", "here"]),
])
def test_time_questions_name_their_places(said, places):
    request = worldclock.parse_request(said)
    assert request["action"] == "show" and request["places"] == places


def test_the_kind_of_question_is_kept():
    assert worldclock.parse_request("What is the time difference between Israel and California?")["difference"]
    assert worldclock.parse_request("Compare the time in Israel and Los Angeles.")["difference"]
    assert not worldclock.parse_request("What time is it in Tokyo?")["difference"]
    daylight = worldclock.parse_request("What time is it in Tokyo, and is it daytime there?")
    assert daylight["places"] == ["tokyo"] and daylight["daylight"]
    assert worldclock.parse_request("Show me the current time around the world.") == {"action": "world"}
    assert worldclock.parse_request("open the world clock") == {"action": "world"}
    assert worldclock.parse_request("What time is it there?")["action"] == "there"
    assert worldclock.parse_request("close the clock") == {"action": "close"}


@pytest.mark.parametrize("said", [
    "what time is it", "what time is it here", "what time is the meeting in tokyo",
    "what time was it in tokyo when the earthquake hit", "what time will it be in tokyo in 3 hours",
    "what time is it in tokyo when it's 5 pm here", "what time does the store open in london",
    "the time in the story was strange", "time in a bottle", "time for lunch", "i had a great time in paris",
    "what is the time complexity of quicksort", "it's time for bed", "set a timer for 5 minutes",
    "what's the weather in tokyo", "show me the photos side by side", "what time is it for john",
    "and in london?", "remove tokyo", "add milk to my list",
])
def test_other_sentences_are_not_for_the_clock(said):
    assert worldclock.parse_request(said) is None


def test_short_follow_ups_only_count_while_the_clock_is_up():
    assert worldclock.parse_request("and in london?", clock_open=True) == {"action": "add", "places": ["london"], "daylight": False}
    assert worldclock.parse_request("add reykjavik to the clock", clock_open=True)["places"] == ["reykjavik"]
    assert worldclock.parse_request("remove tokyo", clock_open=True) == {"action": "remove", "places": ["tokyo"]}
    for other in ("and what about the weather", "remove the last message", "add milk to my list"):
        assert worldclock.parse_request(other, clock_open=True) is None


# ---- which place ----
def test_every_place_known_by_heart_has_a_real_zone():
    for name, (shown, _country, zone, lat, lon) in worldclock._KNOWN.items():
        assert ZoneInfo(zone) and shown and -90 <= lat <= 90 and -180 <= lon <= 180, name
    assert all(name in worldclock._KNOWN for name in worldclock.AROUND_THE_WORLD)


def test_places_are_resolved_or_honestly_refused():
    assert worldclock.resolve("NYC")[1]["tz"] == "America/New_York"
    assert worldclock.resolve("here") == ("home", None)
    outcome, message = worldclock.resolve("the USA")
    assert outcome == "many" and "more than one time zone" in message
    looked_up = {"name": "Kathmandu, Bagmati Province, Nepal", "country": "Nepal", "lat": 27.7, "lon": 85.3, "timezone": "Asia/Kathmandu"}
    assert worldclock.resolve("kathmandu", lambda name: (looked_up, None)) == \
        ("ok", {"name": "Kathmandu", "country": "Nepal", "tz": "Asia/Kathmandu", "lat": 27.7, "lon": 85.3})
    two = [{"name": "Valencia, Spain", "country": "Spain", "lat": 39.5, "lon": -0.4, "timezone": "Europe/Madrid"},
           {"name": "Valencia, Carabobo, Venezuela", "country": "Venezuela", "lat": 10.2, "lon": -68.0, "timezone": "America/Caracas"}]
    outcome, options = worldclock.resolve("valencia", lambda name: (None, two))
    assert outcome == "ambiguous" and [o["tz"] for o in options] == ["Europe/Madrid", "America/Caracas"]
    assert worldclock.resolve("zzyzx", lambda name: (None, None))[0] == "missing"
    outcome, message = worldclock.resolve("nowhere", lambda name: ({"name": "Nowhere, X", "timezone": ""}, None))
    assert outcome == "missing" and "won't guess" in message          # found, but no zone: never a guessed time
    outcome, _ = worldclock.resolve("badzone", lambda name: ({"name": "Bad", "timezone": "Mars/Olympus"}, None))
    assert outcome == "missing"
    outcome, _ = worldclock.resolve("broken", lambda name: 1 / 0)       # a lookup that crashes is "not found", not a crash
    assert outcome == "missing"


# ---- what is said, at fixed moments ----
def test_one_city_with_the_gap_and_the_day():
    now = at(2026, 10, 13, 5, 30)   # 08:30 in Israel (UTC+3, summer time)
    assert worldclock.describe([place("tokyo")], now, HOME) == "It's 2:30 PM in Tokyo, 6 hours ahead of you."
    assert worldclock.describe([place("los angeles")], now, HOME) == \
        "It's 10:30 PM in Los Angeles, 10 hours behind you. It's still Monday there."
    assert worldclock.describe([place("delhi")], now, HOME) == "It's 11:00 AM in Delhi, 2 and a half hours ahead of you."
    assert worldclock.describe([place("haifa")], now, HOME) == "It's 8:30 AM in Haifa, the same time as here."
    assert worldclock.describe([place("sydney")], at(2026, 10, 13, 20), HOME) == \
        "It's 7:00 AM in Sydney, 8 hours ahead of you. It's already Wednesday there."


def test_new_york_follows_daylight_saving():
    ny = place("new york")
    assert worldclock.say_time(worldclock.local_time(ny, at(2026, 3, 8, 6, 59))) == "1:59 AM"    # winter time, UTC-5
    assert worldclock.say_time(worldclock.local_time(ny, at(2026, 3, 8, 7, 0))) == "3:00 AM"     # the clocks jumped: UTC-4
    assert worldclock.say_time(worldclock.local_time(ny, at(2026, 11, 1, 5, 59))) == "1:59 AM"   # still summer time
    assert worldclock.say_time(worldclock.local_time(ny, at(2026, 11, 1, 6, 0))) == "1:00 AM"    # back an hour: UTC-5
    # Israel and New York change on different dates, so the gap between them is not always 7 hours
    assert worldclock.offset_minutes(worldclock.local_time(place("israel"), at(2026, 3, 20, 12)), worldclock.local_time(ny, at(2026, 3, 20, 12))) == 360
    assert worldclock.offset_minutes(worldclock.local_time(place("israel"), at(2026, 7, 1, 12)), worldclock.local_time(ny, at(2026, 7, 1, 12))) == 420


def test_two_places_and_many():
    now = at(2026, 10, 13, 5, 30)
    assert worldclock.describe([place("israel"), place("california")], now, HOME, difference=True) == \
        "Israel is 10 hours ahead of California: it's 8:30 AM in Israel and 10:30 PM in California."
    assert worldclock.describe([place("tokyo"), worldclock.home_place("Ramat Gan")], now, HOME, difference=True) == \
        "Tokyo is 6 hours ahead of you: it's 2:30 PM in Tokyo and 8:30 AM here."
    assert worldclock.describe([place("london"), place("tokyo"), place("sydney")], now, HOME) == \
        "It's 6:30 AM in London, 2:30 PM in Tokyo and 4:30 PM in Sydney."
    assert worldclock.describe([place("madrid"), place("paris")], now, HOME, difference=True).startswith("Madrid and Paris are on the same time")


def test_daytime_comes_from_the_sun_not_the_clock():
    assert worldclock.describe([place("tokyo")], at(2026, 10, 13, 5, 30), HOME, daylight=True).endswith("It's daytime there.")
    assert worldclock.describe([place("tokyo")], at(2026, 10, 13, 15, 0), HOME, daylight=True).endswith("It's night there.")
    assert worldclock.is_daytime(place("reykjavik"), at(2026, 6, 21, 23, 0)) is True    # 11 PM in June and the Sun is still up
    assert worldclock.is_daytime(place("reykjavik"), at(2026, 6, 22, 1, 30)) is False   # it does set there, for a short night
    assert worldclock.is_daytime({"name": "X", "tz": "UTC", "lat": None, "lon": None}, at(2026, 6, 21, 12)) is None


def test_the_window_is_sent_places_and_zones_never_offsets():
    data = worldclock.window([place("tokyo")])
    assert data == {"mode": "set", "focus": 0, "cities": [{"name": "Tokyo", "country": "Japan", "tz": "Asia/Tokyo", "lat": 35.68, "lon": 139.69, "home": False}]}


# ---- in Jarvis ----
def window(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "ws_loop", object())
    monkeypatch.setattr(app, "connected_clients", {object()})
    monkeypatch.setattr(app, "send_ui_update_once", sent.append)
    return sent


def test_asking_opens_the_clock_and_says_the_time(monkeypatch):
    sent = window(monkeypatch)
    reply = app.handle_direct_command("What time is it in Tokyo?")
    now = worldclock.local_time(place("tokyo"), datetime.now(timezone.utc))
    assert reply.startswith("It's ") and " in Tokyo" in reply and reply.endswith("The world clock is on your screen.")
    assert worldclock.say_time(now) in reply or worldclock.say_time(now.replace(minute=(now.minute - 1) % 60)) in reply
    assert [m["type"] for m in sent] == ["clock"] and sent[0]["data"]["cities"][0]["tz"] == "Asia/Tokyo" and sent[0]["data"]["mode"] == "set"
    assert app.clock_state["open"] and [p["name"] for p in app.clock_state["places"]] == ["Tokyo"]


def test_without_a_window_nothing_is_claimed(monkeypatch):
    reply = app.handle_direct_command("What time is it in Tokyo?")
    assert " in Tokyo" in reply and "world clock" not in reply and not app.clock_state["open"]


def test_asking_twice_keeps_one_tokyo(monkeypatch):
    sent = window(monkeypatch)
    app.handle_direct_command("What time is it in Tokyo?")
    app.handle_direct_command("What time is it in Tokyo?")
    assert len(sent) == 2 and all(m["data"]["mode"] == "set" for m in sent) and len(app.clock_state["places"]) == 1


def test_a_place_that_cannot_be_found_opens_nothing(monkeypatch):
    sent = window(monkeypatch)
    monkeypatch.setattr(app.earth, "resolve", lambda name: (None, None))
    reply = app.handle_direct_command("What time is it in Zzyzxqq Flarb?")
    assert reply.startswith("I couldn't find a place called zzyzxqq flarb") and not sent and not app.clock_state["open"]
    assert app.handle_direct_command("what time is it in the usa").startswith("The United States has more than one time zone")
    assert not sent


def test_an_ambiguous_place_is_asked_about_then_shown(monkeypatch):
    sent = window(monkeypatch)
    two = [{"name": "Valencia, Spain", "country": "Spain", "lat": 39.5, "lon": -0.4, "timezone": "Europe/Madrid"},
           {"name": "Valencia, Carabobo, Venezuela", "country": "Venezuela", "lat": 10.2, "lon": -68.0, "timezone": "America/Caracas"}]
    monkeypatch.setattr(app.earth, "resolve", lambda name: (None, two))
    assert app.handle_direct_command("What time is it in Valencia?") == "Which Valencia do you mean: Valencia, Spain, or Valencia, Venezuela?"
    assert not sent
    reply = app.handle_direct_command("the one in Venezuela")
    assert " in Valencia" in reply and sent[0]["data"]["cities"][0]["tz"] == "America/Caracas"
    assert app.pending_clock_choice is None


def test_follow_ups_use_what_the_clock_shows(monkeypatch):
    sent = window(monkeypatch)
    app.handle_direct_command("Compare the time in Israel and Los Angeles.")
    assert [c["name"] for c in sent[-1]["data"]["cities"]] == ["Israel", "Los Angeles"]
    reply = app.handle_direct_command("and in London?")
    assert sent[-1]["data"]["mode"] == "add" and reply.endswith("I added it to the world clock.")
    assert [p["name"] for p in app.clock_state["places"]] == ["Israel", "Los Angeles", "London"]
    assert app.handle_direct_command("remove LA") == "Removed Los Angeles from the clock."
    assert sent[-1]["data"]["mode"] == "remove" and [p["name"] for p in app.clock_state["places"]] == ["Israel", "London"]
    assert app.handle_direct_command("remove Tokyo") == "Tokyo isn't on the world clock."
    app.clock_window_reports({"open": True, "cities": [{"name": "Kathmandu", "country": "Nepal", "tz": "Asia/Kathmandu"}]})
    assert app.handle_direct_command("remove Kathmandu") == "Removed Kathmandu from the clock."   # a place not known by heart
    app.clock_window_reports({"open": True, "cities": [{"name": "London", "country": "United Kingdom", "tz": "Europe/London"}]})
    assert app.handle_direct_command("close the clock") == "Okay, I closed the clock." and sent[-1] == {"type": "close_clock"}
    assert app.handle_direct_command("and in Paris?") is None   # the clock is closed: this is conversation again


def test_what_time_is_it_there_follows_the_last_place(monkeypatch):
    window(monkeypatch)
    assert app.handle_direct_command("What time is it there?") is None   # nothing says where: left to the AI and its tool
    app.handle_direct_command("What time is it in Tokyo?")
    assert " in Tokyo" in app.handle_direct_command("What time is it there?")
    app.last_place_asked.update(name="Paris", at=__import__("time").time(),   # as a weather question about Paris leaves it
                                place={"name": "Paris", "country": "France", "tz": "Europe/Paris", "lat": 48.85, "lon": 2.35})
    assert " in Paris" in app.handle_direct_command("and what time is it there?")


def test_the_window_reports_what_it_shows():
    app.clock_window_reports({"open": True, "cities": [{"name": "Oslo", "country": "Norway", "tz": "Europe/Oslo", "lat": 59.9, "lon": 10.7}, {"junk": 1}]})
    assert app.clock_state["open"] and [p["name"] for p in app.clock_state["places"]] == ["Oslo"]
    app.clock_window_reports({"open": False, "cities": []})
    assert not app.clock_state["open"]


def test_around_the_world(monkeypatch):
    sent = window(monkeypatch)
    reply = app.handle_direct_command("Show me the current time around the world.")
    assert reply.startswith("It's ") and " in New York" in reply and reply.endswith("The rest are on the world clock.")
    assert len(sent[0]["data"]["cities"]) == 6 and sent[0]["data"]["focus"] == -1


# ---- the AI's tool ----
def test_the_tool_returns_the_real_time_to_the_ai(monkeypatch):
    sent = window(monkeypatch)
    result = app.TOOL_FUNCTIONS["world_clock"](places=["Tokyo", "London"])
    assert result.startswith("It's ") and " in Tokyo" in result and " in London" in result and len(sent) == 1
    assert app.TOOL_FUNCTIONS["world_clock"](places="Tokyo and London").startswith("It's ")
    assert app.TOOL_FUNCTIONS["world_clock"](places=[]) == "No place was named. Ask the user which city they mean."
    monkeypatch.setattr(app.earth, "resolve", lambda name: (None, None))
    assert "couldn't find" in app.TOOL_FUNCTIONS["world_clock"](places=["Zzyzxqq"])   # the AI is told, not given a time
    assert any(t["function"]["name"] == "world_clock" for t in app.TOOLS)


@pytest.mark.parametrize("said,offered", [
    ("what time is it there?", True), ("what's the time difference between here and there", True),
    ("how many hours ahead are they", True), ("I had a great time in Paris", False), ("it's time for bed", False),
    ("what time is it", False), ("my teacher said the timer broke", False),
])
def test_the_tool_is_only_offered_for_time_questions(said, offered):
    assert app.is_clock_question(said) is offered
    assert bool(app.select_tools(said)[0]) is offered
