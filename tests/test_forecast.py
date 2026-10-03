"""The weather window's data (forecast.py): where, the shape the window draws, what's said, and failing gracefully."""
import pytest

import forecast


def raw_forecast(code=61, is_day=1):
    hours = [f"2026-10-03T{h:02d}:00" for h in range(24)] + [f"2026-10-04T{h:02d}:00" for h in range(24)]
    return {
        "timezone": "Asia/Jerusalem", "utc_offset_seconds": 10800,
        "current": {"time": "2026-10-03T14:15", "temperature_2m": 23.6, "apparent_temperature": 26.2,
                    "relative_humidity_2m": 64, "is_day": is_day, "precipitation": 0.4, "weather_code": code,
                    "cloud_cover": 80, "pressure_msl": 1012.3, "wind_speed_10m": 18.4, "wind_direction_10m": 250,
                    "wind_gusts_10m": 31.0, "visibility": None, "uv_index": None},
        "hourly": {"time": hours, "temperature_2m": [20 + (i % 10) for i in range(48)],
                   "apparent_temperature": [21] * 48, "precipitation_probability": [10] * 15 + [80] + [10] * 32,
                   "precipitation": [0.0] * 48, "weather_code": [code] * 48, "cloud_cover": [70] * 48,
                   "wind_speed_10m": [12] * 48, "wind_direction_10m": [250] * 48, "is_day": [1] * 48,
                   "uv_index": [3.0] * 48, "visibility": [24000.0] * 48},
        "daily": {"time": ["2026-10-03", "2026-10-04"], "weather_code": [code, 0],
                  "temperature_2m_max": [27.4, 29.0], "temperature_2m_min": [18.6, 19.1],
                  "precipitation_probability_max": [80, 5], "precipitation_sum": [3.2, 0.0],
                  "wind_speed_10m_max": [25, 14], "wind_direction_10m_dominant": [250, 300],
                  "sunrise": ["2026-10-03T06:35", "2026-10-04T06:36"], "sunset": ["2026-10-03T18:23", "2026-10-04T18:21"],
                  "uv_index_max": [5.5, 6.1]},
    }


PLACE = {"name": "Ramat Gan, Israel", "lat": 32.08, "lon": 34.81, "source": "settings"}


def test_normalize_gives_the_window_everything_it_draws():
    d = forecast.normalize(raw_forecast(), PLACE, radar={"host": "https://x", "frames": [{"time": 1, "path": "/p"}]})
    c = d["current"]
    assert (c["temp"], c["feels"], c["kind"], c["label"]) == (24, 26, "rain", "Light rain")
    assert c["visibility_km"] == 24.0 and c["uv"] == 3.0     # missing "now" values come from the current hour
    assert d["today"] == {"high": 27, "low": 19, "rain_chance": 80, "sunrise": "2026-10-03T06:35",
                          "sunset": "2026-10-03T18:23"}
    assert d["hourly"][0]["time"] == "2026-10-03T14:00" and len(d["hourly"]) == 25   # starts at the current hour
    assert [day["date"] for day in d["daily"]] == ["2026-10-03", "2026-10-04"]
    assert d["daily"][1]["kind"] == "clear"
    assert d["radar"]["frames"] and d["place"]["name"] == "Ramat Gan, Israel" and d["utc_offset"] == 10800


def test_summary_says_now_today_and_coming_rain():
    text = forecast.summary(forecast.normalize(raw_forecast(), PLACE))
    assert text.startswith("It's 24 degrees and light rain in Ramat Gan, feeling like 26.")
    assert "high of 27 and a low of 19" in text
    assert "Expect rain around 3 PM." in text


def test_unknown_codes_and_missing_numbers_never_break_it():
    raw = raw_forecast(code=None)
    raw["current"]["temperature_2m"] = None
    d = forecast.normalize(raw, PLACE)
    assert d["current"]["temp"] is None and d["current"]["label"] == "Unknown"
    assert "couldn't read the current conditions" in forecast.summary(d)


def test_location_falls_back_to_the_approximate_one(monkeypatch):
    monkeypatch.setattr(forecast.earth, "geocode", lambda name: None)
    monkeypatch.setattr(forecast, "_approximate_place", lambda: {"name": "Rishon LeZion, Israel", "lat": 31.9, "lon": 34.8})
    place, problem = forecast.locate("", fallback_city="")
    assert place["source"] == "approximate" and problem is None
    place, problem = forecast.locate("Atlantis")          # a place that was asked for must exist
    assert place is None and "Atlantis" in problem


def test_no_location_at_all_says_how_to_fix_it(monkeypatch):
    monkeypatch.setattr(forecast.earth, "geocode", lambda name: None)
    monkeypatch.setattr(forecast, "_approximate_place", lambda: None)
    with pytest.raises(forecast.WeatherError, match="Settings"):
        forecast.get()


def test_service_down_shows_the_last_forecast_marked_stale(monkeypatch):
    monkeypatch.setattr(forecast.earth, "geocode", lambda name: {"name": "Testville", "lat": 1, "lon": 2})
    monkeypatch.setattr(forecast, "fetch_radar", lambda: None)
    monkeypatch.setattr(forecast, "_cache", {})
    monkeypatch.setattr(forecast, "fetch_raw", lambda place: raw_forecast())
    fresh = forecast.get(fallback_city="Testville")
    assert not fresh["stale"]

    def down(place):
        raise forecast.WeatherError("Weather data is temporarily unavailable.")
    monkeypatch.setattr(forecast, "fetch_raw", down)
    monkeypatch.setattr(forecast, "fetch_met", down)   # the backup is down too
    old = forecast.get(fallback_city="Testville", refresh=True)
    assert old["stale"] and old["current"]["temp"] == fresh["current"]["temp"]
    monkeypatch.setattr(forecast, "_cache", {})
    with pytest.raises(forecast.WeatherError, match="temporarily unavailable"):
        forecast.get(fallback_city="Testville")


def met_forecast():
    """A small MET Norway answer: hourly for a day, then 6-hourly (times in UTC, wind in m/s)."""
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
    series = []
    for h in range(30):
        moment = start + timedelta(hours=h)
        series.append({"time": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {
            "instant": {"details": {"air_temperature": 20 + (h % 8), "relative_humidity": 60, "wind_speed": 5.0,
                                    "wind_from_direction": 270, "cloud_area_fraction": 40,
                                    "air_pressure_at_sea_level": 1015, "ultraviolet_index_clear_sky": 5.0}},
            "next_1_hours": {"summary": {"symbol_code": "lightrainshowers_day" if h < 3 else "partlycloudy_night"},
                             "details": {"precipitation_amount": 0.4 if h < 3 else 0.0}},
            "next_6_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"air_temperature_max": 28,
                                                                              "air_temperature_min": 19}}}})
    return {"properties": {"timeseries": series}}


def test_met_norway_backup_gives_the_same_shape():
    place = {**PLACE, "timezone": "Asia/Jerusalem"}
    d = forecast.normalize_met(met_forecast(), place)
    c = d["current"]
    assert (c["temp"], c["kind"], c["label"], c["wind"]) == (20, "rain", "Light showers", 18)   # 5 m/s = 18 km/h
    assert c["visibility_km"] is None and c["feels"] is not None
    assert d["hourly"][0]["time"] == "2026-10-03T12:00"           # 09:00 UTC is noon in Israel (UTC+3)
    assert d["utc_offset"] == 3 * 3600 and d["source"]["name"] == "MET Norway"
    assert d["today"]["sunrise"].startswith("2026-10-03T06:3")     # computed, no extra service
    assert d["daily"][0]["high"] == 28 and d["daily"][0]["precip"] == 1.2
    assert "light showers" in forecast.summary(d)


def test_sunrise_math_matches_a_known_day():
    from datetime import date
    rise, setting = forecast.sun_times(32.08, 34.81, date(2026, 10, 3))   # Ramat Gan: 06:35 / 18:23 local (UTC+3)
    assert rise.strftime("%H:%M") in ("03:34", "03:35", "03:36") and setting.strftime("%H:%M") in ("15:22", "15:23", "15:24")


def test_open_meteo_down_means_met_norway_answers(monkeypatch):
    monkeypatch.setattr(forecast.earth, "geocode", lambda name: {"name": "Testville", "lat": 32.08, "lon": 34.81})
    monkeypatch.setattr(forecast, "fetch_radar", lambda: None)
    monkeypatch.setattr(forecast, "_cache", {})

    def down(place):
        raise forecast.WeatherError("Weather data is temporarily unavailable.")
    monkeypatch.setattr(forecast, "fetch_raw", down)
    monkeypatch.setattr(forecast, "fetch_met", lambda place: met_forecast())
    d = forecast.get(fallback_city="Testville")
    assert d["source"]["name"] == "MET Norway" and not d["stale"]
