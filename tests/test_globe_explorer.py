"""The globe as a geographic explorer: distances, routes (date line, poles), the countries a route crosses, places
within a radius, flight estimates, comparisons, the Sun's real position, sunrise and sunset, ambiguous place names.
Place lookups are simulated (no network); the geography, borders and solar maths are the real code and data."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

import earth
import geo
import sandbox

app = None
UTC = dt.timezone.utc


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


PLACES = {   # real coordinates, as Open-Meteo's geocoder returns them
    "tokyo": {"name": "Tokyo, Japan", "country": "Japan", "lat": 35.6895, "lon": 139.69171, "timezone": "Asia/Tokyo"},
    "new york": {"name": "New York, United States", "country": "United States", "lat": 40.71427, "lon": -74.00597, "timezone": "America/New_York"},
    "tel aviv": {"name": "Tel Aviv, Israel", "country": "Israel", "lat": 32.08088, "lon": 34.78057, "timezone": "Asia/Jerusalem"},
    "london": {"name": "London, England, United Kingdom", "country": "United Kingdom", "lat": 51.50853, "lon": -0.12574, "timezone": "Europe/London"},
    "sydney": {"name": "Sydney, New South Wales, Australia", "country": "Australia", "lat": -33.86785, "lon": 151.20732, "timezone": "Australia/Sydney"},
    "los angeles": {"name": "Los Angeles, California, United States", "country": "United States", "lat": 34.05223, "lon": -118.24368, "timezone": "America/Los_Angeles"},
    "haifa": {"name": "Haifa, Haifa District, Israel", "country": "Israel", "lat": 32.81841, "lon": 34.9885, "timezone": "Asia/Jerusalem"},
    "madrid": {"name": "Madrid, Spain", "country": "Spain", "lat": 40.4165, "lon": -3.70256, "timezone": "Europe/Madrid"},
}
VALENCIAS = [{"name": "Valencia, Carabobo, Venezuela", "country": "Venezuela", "lat": 10.16202, "lon": -68.00765, "timezone": "America/Caracas"},
             {"name": "Valencia, Spain", "country": "Spain", "lat": 39.46975, "lon": -0.37739, "timezone": "Europe/Madrid"}]


@pytest.fixture
def places(monkeypatch):
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda m: sent.append(m))
    monkeypatch.setattr(app, "speak", lambda *a, **k: None)
    monkeypatch.setattr(app, "pending_earth_choice", None)
    monkeypatch.setattr(app, "last_globe_route", {"a": None, "b": None, "at": 0.0})
    def resolve(name):
        key = name.lower()
        if key == "valencia":
            return None, VALENCIAS
        return PLACES.get(key), None
    monkeypatch.setattr(app.earth, "resolve", resolve)
    return sent


# ---------------------------------------------------------------- the geography itself
def test_known_distances():
    assert round(geo.great_circle_km(51.5074, -0.1278, 40.7128, -74.0060)) == pytest.approx(5570, abs=15)   # London-NYC
    assert round(geo.great_circle_km(35.6895, 139.6917, 40.7143, -74.006)) == pytest.approx(10849, abs=10)


def test_route_points_cross_the_date_line_and_the_pole_without_detours():
    pts = geo.route_points(-33.87, 151.21, 34.05, -118.24, 200)   # Sydney -> Los Angeles
    lons = [lon for _, lon in pts]
    # it crosses 180°: the longitudes jump from about +180 to -180 exactly once, never sweeping back across the map
    assert sum(1 for a, b in zip(lons, lons[1:]) if abs(a - b) > 300) == 1
    km = geo.great_circle_km(-33.87, 151.21, 34.05, -118.24)
    steps = sum(geo.great_circle_km(*p, *q) for p, q in zip(pts, pts[1:]))
    assert steps == pytest.approx(km, rel=1e-3)   # the points lie on the shortest path itself
    polar = geo.route_points(70, 0, 70, 180, 50)   # over the North Pole
    assert max(lat for lat, _ in polar) == pytest.approx(90, abs=0.5)


def test_antipodes_and_identical_points_do_not_break():
    assert geo.route_points(10, 20, 10, 20, 4) == [(10, 20)] * 5
    assert len(geo.route_points(0, 0, 0, 180, 10)) == 11


@pytest.mark.parametrize("a, b, expected, absent", [
    ("tel aviv", "london", ["Israel", "Turkey", "Greece", "Italy", "Germany", "France", "United Kingdom"], ["Spain", "Egypt"]),
    ("tokyo", "new york", ["Japan", "Russia", "United States of America", "Canada"], ["China"]),
    ("sydney", "los angeles", ["Australia", "United States of America"], ["Japan"]),
])
def test_countries_along_a_route_come_from_real_borders(a, b, expected, absent):
    pa, pb = PLACES[a], PLACES[b]
    crossed = geo.countries_along(pa["lat"], pa["lon"], pb["lat"], pb["lon"])
    assert [c for c in crossed if c in expected] == expected   # all of them, in flying order
    assert not set(absent) & set(crossed)


def test_points_at_sea_are_in_no_country():
    assert geo.country_at(0, -30) is None and geo.country_at(48.8566, 2.3522) == "France"


def test_places_near_are_real_and_within_the_radius():
    near = geo.places_near(32.81841, 34.9885, 100, limit=12, exclude_name="Haifa")
    assert near and all(p["km"] <= 100 for p in near)
    assert "Haifa" not in [p["name"] for p in near]
    assert near == sorted(near, key=lambda p: -p["population"])


def test_flight_estimates_are_labelled_and_sensible():
    long = geo.flight_estimate(9115)
    assert 11 * 60 <= long["minutes"] <= 13 * 60 and long["route_km"] > 9115
    assert geo.flight_estimate(54)["too_short"]


# ---------------------------------------------------------------- the Sun
@pytest.mark.parametrize("when, lat, lon", [
    (dt.datetime(2026, 3, 20, 14, 46, tzinfo=UTC), 0.0, -39.5),     # March equinox: overhead on the equator
    (dt.datetime(2026, 6, 21, 8, 24, tzinfo=UTC), 23.44, 54.5),     # June solstice: the Tropic of Cancer
    (dt.datetime(2026, 12, 21, 20, 50, tzinfo=UTC), -23.44, -133.3),
])
def test_the_subsolar_point(when, lat, lon):
    s = geo.subsolar_point(when)
    assert s["lat"] == pytest.approx(lat, abs=0.05) and s["lon"] == pytest.approx(lon, abs=0.6)


@pytest.mark.parametrize("place, day, rise, set_", [
    ("tokyo", dt.date(2026, 10, 10), "05:43", "17:13"),
    ("new york", dt.date(2026, 10, 10), "07:03", "18:24"),
    ("london", dt.date(2026, 6, 21), "04:43", "21:21"),
])
def test_sunrise_and_sunset_match_published_times(place, day, rise, set_):
    p = PLACES[place]
    events = geo.sun_events(p["lat"], p["lon"], day)
    zone = ZoneInfo(p["timezone"])
    def minutes(hhmm):
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m
    got_rise = events["sunrise"].astimezone(zone); got_set = events["sunset"].astimezone(zone)
    assert abs(got_rise.hour * 60 + got_rise.minute - minutes(rise)) <= 2
    assert abs(got_set.hour * 60 + got_set.minute - minutes(set_)) <= 2


def test_midnight_sun_and_polar_night():
    assert geo.sun_events(78.2, 15.6, dt.date(2026, 6, 21)) == {"polar": "day"}
    assert geo.sun_events(78.2, 15.6, dt.date(2026, 12, 21)) == {"polar": "night"}


# ---------------------------------------------------------------- understanding the question
@pytest.mark.parametrize("said, action, extra", [
    ("What is the distance between Tokyo and New York?", "distance", {"a": "tokyo", "b": "new york"}),
    ("how long is the flight from tel aviv to new york", "distance", {"wants": "flight"}),
    ("which countries does a flight from tel aviv to london pass over", "distance", {"b": "london", "wants": "countries"}),
    ("which countries does it fly over", "route_followup", {"wants": "countries"}),
    ("compare the distance from tel aviv to london with tel aviv to new york", "compare", {"question": None}),
    ("paris to rome vs paris to madrid", "compare", {"pairs": [("paris", "rome"), ("paris", "madrid")]}),
    ("which is farther from tel aviv, london or new york?", "compare", {"question": "farther"}),
    ("is tokyo closer to seoul or beijing?", "compare", {"pairs": [("tokyo", "seoul"), ("tokyo", "beijing")], "question": "closer"}),
    ("cities within 100 km of haifa", "radius", {"a": "haifa", "km": 100.0}),
    ("what cities are near haifa", "radius", {"a": "haifa"}),
    ("show me earth at night", "sun", {"what": "night_view"}),
    ("where is it currently daytime?", "sun", {"what": "where_day"}),
    ("show sunrise over tokyo", "sun", {"what": "sunrise", "place": "tokyo"}),
    ("is it night in sydney", "sun", {"what": "is_day", "place": "sydney"}),
])
def test_questions_are_understood(said, action, extra):
    request = earth.parse_request(said)
    assert request["action"] == action
    for key, value in extra.items():
        assert request[key] == value, key


@pytest.mark.parametrize("said", ["i like the city near me", "is it night", "show me jupiter", "how far did you get"])
def test_other_sentences_are_left_alone(said):
    assert earth.parse_request(said) is None


# ---------------------------------------------------------------- answering, and what the window is sent
def test_a_distance_question_sends_a_full_journey(places):
    reply = app.handle_direct_command("What is the distance between Tokyo and New York?")
    data = places[-1]["data"]
    assert data["mode"] == "route" and data["km"] == 10849 and data["routes"][0]["countries"][0] == "Japan"
    assert "sun" in data and -24 <= data["sun"]["lat"] <= 24
    assert "straight line" in reply and "(estimate)" in reply


def test_follow_ups_use_the_last_route(places):
    app.handle_direct_command("distance between tel aviv and london")
    reply = app.handle_direct_command("which countries does it fly over")
    assert reply.startswith("Flying the shortest path from Tel Aviv, Israel to London") and "Turkey" in reply


def test_a_comparison_measures_each_route_on_its_own(places):
    reply = app.handle_direct_command("which is farther from tel aviv, london or new york?")
    data = places[-1]["data"]
    assert data["mode"] == "compare" and [r["km"] for r in data["routes"]] == [3557, 9115]
    assert reply.startswith("New York is farther from Tel Aviv")


def test_a_radius_question_lists_real_places(places):
    reply = app.handle_direct_command("cities within 100 km of haifa")
    data = places[-1]["data"]
    assert data["mode"] == "radius" and data["radius"]["places"]
    assert all(p["km"] <= 100 for p in data["radius"]["places"]) and "Within 100 km of Haifa" in reply


def test_sunrise_and_day_or_night_answers(places):
    reply = app.handle_direct_command("show sunrise over tokyo")
    assert reply.startswith("The Sun rises in Tokyo at") and "local time" in reply
    sun = places[-1]["data"]["sun"]
    # the globe is lit as at that sunrise: Tokyo sits on the dawn line
    assert abs(geo.sun_elevation(35.6895, 139.69171, dt.datetime.fromisoformat(sun["at"].replace("Z", "+00:00")))) < 1.5
    assert app.handle_direct_command("is it night in sydney").split(" in Sydney")[0] in ("It's daytime", "It's twilight", "It's night")


def test_an_ambiguous_place_is_asked_about_once_then_answered(places):
    question = app.handle_direct_command("what is the distance between valencia and madrid")
    assert question == "Which Valencia do you mean: Valencia, Carabobo, Venezuela, or Valencia, Spain?"
    assert not places
    reply = app.handle_direct_command("the one in spain")
    assert reply.startswith("The distance between Valencia, Spain and Madrid, Spain is about 302 kilometers")


def test_an_unknown_place_is_said_plainly_and_nothing_is_invented(places):
    reply = app.handle_direct_command("distance between xqzzyy and london")
    assert reply.startswith("I couldn't find xqzzyy") and not places


def test_consecutive_questions_each_get_their_own_globe(places):
    app.handle_direct_command("distance between tokyo and new york")
    app.handle_direct_command("distance between sydney and los angeles")
    assert [m["data"]["title"] for m in places] == ["Tokyo, Japan → New York, United States",
                                                    "Sydney, New South Wales, Australia → Los Angeles, California, United States"]


def test_missing_border_data_leaves_countries_out_instead_of_guessing(places, monkeypatch):
    def missing(*a):
        raise OSError("no data")
    monkeypatch.setattr(geo, "countries_along", missing)
    reply = app.handle_direct_command("distance between tel aviv and london")
    assert places[-1]["data"]["routes"][0]["countries"] is None and "Passes over" not in reply
