"""Everyday questions Jarvis answers himself, exactly and at once, instead of handing them to the AI: sums, one fact
about a planet, the weather on a named day, and the small slips (typos, "go to …", what was heard) around them."""
import copy

import pytest

import arithmetic
import app_launcher
import documents
import forecast
import planets
from speech_fixes import fix_spoken
from typos import fix_typos

from test_forecast import PLACE, raw_forecast


# ---- sums ----
@pytest.mark.parametrize("asked,answer", [
    ("what is fifteen percent of eighty", "12"), ("What is 15% of 80?", "12"), ("what's 12 times 12", "144"),
    ("calculate 144 divided by 12", "12"), ("2 to the power of 10", "1,024"), ("square root of 144", "12"),
    ("what is three point five plus two", "5.5"), ("(3 + 4) * 5", "35"), ("seven squared", "49"),
    ("what's 1,250 plus 300", "1,550"), ("two thirds of 90", "60"), ("half of 50", "25"), ("20% off 50", "40"),
    ("what is 0.1 + 0.2", "0.3"), ("what's 7 times 8 plus 2", "58"),
])
def test_sums_are_answered_exactly(asked, answer):
    assert arithmetic.answer(asked).endswith(f" is {answer}.")


@pytest.mark.parametrize("asked", ["what is 5", "what is 9/11", "what is the capital of france", "2x + 4 = 24",
                                   "set a timer for 5 minutes", "10 minutes", "what is 5 km in miles", "1 hour and 1 day",
                                   "", "what is love", "call 555 1234"])
def test_what_is_not_a_sum_is_left_alone(asked):
    assert arithmetic.answer(asked) is None


def test_dividing_by_zero_is_said_plainly():
    assert arithmetic.answer("what is 10 divided by 0") == "You can't divide by zero."


# ---- one fact about a planet ----
@pytest.mark.parametrize("asked,body,fact,says", [
    ("how big is jupiter", "jupiter", "size", "69,911 kilometers"),
    ("How many moons does Saturn have?", "saturn", "moons", "146 known moons"),
    ("does saturn have rings", "saturn", "rings", "Yes."),
    ("how long is a day on venus", "venus", "day", "spins backward"),
    ("how long is a year on neptune", "neptune", "year", "Earth years"),
    ("how hot is the sun", "sun", "temperature", "5,500"),
    ("how far is mars from earth", "mars", "distance", "between about 78 and 378 million kilometers"),
    ("how far is the moon", "moon", "distance", "384,400 kilometers"),
])
def test_one_fact_about_a_planet_is_answered_first(asked, body, fact, says):
    request = planets.parse_request(asked)
    assert (request["body"], request["fact"]) == (body, fact)
    assert says in planets.answer(body, fact, request["from_earth"])


@pytest.mark.parametrize("asked", ["how far is jupiter from london", "how hot is it", "how big is my screen"])
def test_other_questions_are_not_planet_facts(asked):
    assert planets.parse_request(asked) is None


# ---- the weather on a day ----
@pytest.mark.parametrize("asked,expect", [
    ("weather in paris", {"city": "paris", "when": "", "about": ""}),
    ("will it rain tomorrow", {"city": "", "when": "tomorrow", "about": "rain"}),
    ("what's the weather like in tokyo this weekend", {"city": "tokyo", "when": "weekend", "about": ""}),
    ("will it rain on friday in london", {"city": "london", "when": "friday", "about": "rain"}),
    ("weather for tomorrow in paris", {"city": "paris", "when": "tomorrow", "about": ""}),
    ("how hot is it in dubai", {"city": "dubai", "when": "", "about": ""}),
    ("what's the temperature in new york", {"city": "new york", "when": "", "about": ""}),
    ("do i need an umbrella tomorrow", {"city": "", "when": "tomorrow", "about": "rain"}),
    ("is it going to rain", {"city": "", "when": "", "about": "rain"}),
])
def test_weather_questions_keep_their_place_day_and_subject(asked, expect):
    assert forecast.parse_request(asked) == expect


@pytest.mark.parametrize("said", ["what's the temperature of the sun", "how hot is the sun", "it will be nice to see you",
                                  "will it be ready in time", "will it work"])
def test_sentences_that_only_sound_like_weather(said):
    assert forecast.parse_request(said) is None


def week():
    data = forecast.normalize(raw_forecast(), {**PLACE, "name": "Paris, France"})
    day = data["daily"][1]
    data["daily"] = [data["daily"][0]] + [{**day, "date": f"2026-10-{4 + i:02d}"} for i in range(6)]   # Sat 3 … Fri 9
    return data


def test_a_named_day_gets_that_days_forecast():
    data = week()
    assert forecast.day_summary(data, "tomorrow") == "Tomorrow in Paris: clear sky, a high of 29 and a low of 19."
    assert forecast.day_summary(data, "wednesday").startswith("Wednesday in Paris: clear sky")
    assert forecast.day_summary(data, "weekend").startswith("This weekend in Paris. Today: light rain")
    assert forecast.day_summary(data) == forecast.summary(data)


def test_will_it_rain_is_a_yes_or_a_no():
    data = week()
    assert forecast.day_summary(data, "tomorrow", "rain") == "No, rain isn't expected in Paris tomorrow: the chance is 5 percent."
    wet = copy.deepcopy(data)
    wet["daily"][1].update(rain_chance=85, kind="rain", label="Rain")
    assert forecast.day_summary(wet, "tomorrow", "rain") == "Yes, rain is likely in Paris tomorrow, with an 85 percent chance."
    assert "tomorrow (85 percent)" in forecast.day_summary(wet, "week", "rain")
    assert forecast.day_summary(data, "", "rain").startswith("Yes. Right now in Paris: light rain.")


def test_a_day_past_the_forecast_says_so():
    data = forecast.normalize(raw_forecast(), PLACE)   # two days only: Saturday and Sunday
    assert "only reaches seven days" in forecast.day_summary(data, "wednesday")


def test_a_doubled_letter_in_a_city_is_forgiven(monkeypatch):
    monkeypatch.setattr(forecast.earth, "geocode", lambda name: {"name": "Paris, France", "lat": 48.85, "lon": 2.35} if name == "paris" else None)
    place, problem = forecast.locate("pariss")
    assert place["name"] == "Paris, France" and problem is None


# ---- what was heard keeps its punctuation and symbols ----
@pytest.mark.parametrize("heard,kept", [
    ("Solve 2x + 4 = 24.", "Solve 2x + 4 = 24."),
    ("What is 15% of 80?", "What is 15% of 80?"),
    ("Which is farther from Tel Aviv, London or New York?", "Which is farther from Tel Aviv, London or New York?"),
])
def test_spoken_sentences_are_not_stripped(heard, kept):
    assert fix_spoken(heard) == kept


def test_spoken_names_are_still_repaired():
    assert "netflix" in fix_spoken("Open Net flicks.").lower()
    assert "whatsapp" in fix_spoken("Send it on whats app").lower()


# ---- typos and "go to" ----
@pytest.mark.parametrize("typed,fixed", [
    ("whats the wether tommorow", "whats the weather tomorrow"),
    ("sett a timr for 5 minuts", "set a timer for 5 minutes"),
    ("paly some musci", "play some music"),
    ("opne yotube", "open youtube"),
])
def test_everyday_typos_are_fixed(typed, fixed):
    assert fix_typos(typed) == fixed


@pytest.mark.parametrize("said,site", [("go to wikipedia", "wikipedia"), ("take me to youtube", "youtube"), ("pull up gmail", "gmail")])
def test_go_to_a_known_website_opens_it(said, site):
    assert app_launcher.parse_open_request(said) == site


@pytest.mark.parametrize("said", ["go to sleep", "go to the store", "visit my grandmother", "bring up the graph again"])
def test_go_to_anything_else_is_conversation(said):
    assert app_launcher.parse_open_request(said) is None


# ---- documents: the app's name is not part of the story ----
@pytest.mark.parametrize("asked,writes", [
    ("write a short story about a dragon in Google Docs", "write a short story about a dragon"),
    ("Open Google Docs and write a poem about the sea", "write a poem about the sea"),
    ("write a letter to my teacher in word", "write a letter to my teacher"),
    ("write a story in Google Docs about a robot", "write a story about a robot"),
    ("write an essay on google docs and why people use it", "write an essay on google docs and why people use it"),
    ("write a story about a word that changed the world", "write a story about a word that changed the world"),
])
def test_the_app_is_left_out_of_what_gets_written(asked, writes):
    assert documents.what_to_write(asked) == writes


# ---- "which is farther" typed without its comma ----
def test_a_missing_comma_still_finds_where_the_first_place_ends(monkeypatch):
    import earth
    request = earth.parse_request("which is farther from tel aviv london or new york")
    assert request["pairs"][0] == ("tel", "aviv london") and request["splits"] == [("tel aviv", "london")]
    real = {"tel aviv", "london", "new york", "tel"}
    monkeypatch.setattr(earth, "geocode", lambda name: {"name": name} if name in real else None)
    settled = earth.settle_split(request)
    assert settled["pairs"] == [("tel aviv", "london"), ("tel aviv", "new york")] and "splits" not in settled
    assert "splits" not in earth.parse_request("Which is farther from Tel Aviv, London or New York?")


# ---- the windows mark what was asked about ----
def test_the_planet_window_is_told_which_fact_was_asked_for():
    assert planets.build("saturn", "moons")["asked"] == "Moons"
    assert planets.build("saturn")["asked"] == ""
    assert planets.build("saturn", "moons")["asked"] in [label for label, _ in planets.build("saturn")["chips"]]


def test_the_weather_window_is_told_which_days_were_asked_about():
    data = week()   # Saturday 3 October … Friday 9
    assert forecast.asked_dates(data, "tomorrow") == ["2026-10-04"]
    assert forecast.asked_dates(data, "weekend") == ["2026-10-03", "2026-10-04"]
    assert forecast.asked_dates(data, "wednesday") == ["2026-10-07"]
    assert forecast.asked_dates(data, "") == [] and forecast.asked_dates(data, "week") == []
