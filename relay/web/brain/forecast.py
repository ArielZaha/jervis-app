"""The weather, for the weather window and for spoken answers. Every source is free, needs no account and no key:

  locate()        where: the city from Settings, else this connection's approximate location (GeoJS)
  fetch_raw()     the forecast from Open-Meteo (free for non-commercial use, CC BY 4.0)
  fetch_met()     the backup: MET Norway (free, commercial use allowed, CC BY 4.0), used when Open-Meteo can't answer
  fetch_radar()   the rain-radar frame list from RainViewer (free for personal use; optional, the window works without)
  normalize*()    one plain dict the window draws (weather/*.js) and summary() speaks, the same for either source

Nothing here costs money or can start to: no paid plan is used, and a service that refuses (or disappears) only means
the other one is asked, or the window says the weather is unavailable. Nothing here touches the UI either; app.py
sends the result to the window.
"""
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

import earth

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
IP_LOCATION_URL = "https://get.geojs.io/v1/ip/geo.json"
RADAR_URL = "https://api.rainviewer.com/public/weather-maps.json"
USER_AGENT = "Jarvis/1.0 (+https://github.com/ArielZaha/jervis-app)"   # MET Norway's terms: say who is asking
SOURCES = {
    "open-meteo": {"name": "Open-Meteo.com", "license": "CC BY 4.0"},
    "met": {"name": "MET Norway", "license": "CC BY 4.0"},
}
CACHE_SECONDS = 10 * 60      # a forecast younger than this is shown as is ("refresh" skips it)
STALE_SECONDS = 3 * 3600     # when the service can't be reached, an older one is still better than nothing

# WMO weather codes -> (what to say, which picture/animation: clear, partly, cloudy, fog, drizzle, rain, snow, storm)
CODES = {
    0: ("Clear sky", "clear"), 1: ("Mostly clear", "clear"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm with hail", "storm"), 99: ("Thunderstorm with hail", "storm"),
}

_CURRENT = ("temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,weather_code,cloud_cover,"
            "pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility,uv_index")
_HOURLY = ("temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,cloud_cover,"
           "wind_speed_10m,wind_direction_10m,is_day,uv_index,visibility")
_DAILY = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,"
          "wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset,uv_index_max")

_ip_place = {"at": 0.0, "place": None}
_cache = {}   # place name -> (fetched at, normalized dict)


class WeatherError(Exception):
    """Weather couldn't be shown; the message is fit to say to the user."""


def describe(code) -> tuple:
    return CODES.get(code, ("Clear sky", "clear")) if code is not None else ("Unknown", "cloudy")


# ---------- where ----------
def _approximate_place():
    """This internet connection's rough location (city level). Cached for an hour; None if it can't be found."""
    if _ip_place["place"] and time.time() - _ip_place["at"] < 3600:
        return _ip_place["place"]
    try:
        r = requests.get(IP_LOCATION_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        lat, lon = float(data["latitude"]), float(data["longitude"])
        city, country = (data.get("city") or "").strip(), (data.get("country") or "").strip()
        name = ", ".join(p for p in (city, country) if p) or "Your area"
        place = {"name": name, "country": country, "lat": lat, "lon": lon, "timezone": data.get("timezone") or ""}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    _ip_place.update(at=time.time(), place=place)
    return place


def locate(city: str = "", fallback_city: str = ""):
    """The place to show: `city` if one was asked for, else the city from Settings, else the approximate location.
    Returns (place dict with "source", None) or (None, reason to say)."""
    city = (city or "").strip()
    if city:
        place = earth.geocode(city)
        if place:
            return {**place, "source": "asked"}, None
        return None, f"I couldn't find a place called {city}."
    configured = (fallback_city or "").strip()
    if configured:
        place = earth.geocode(configured)
        if place:
            return {**place, "source": "settings"}, None
    place = _approximate_place()
    if place:
        return {**place, "source": "approximate"}, None
    if configured:
        return None, f"I couldn't find {configured}, the weather city in Settings. Check its spelling there."
    return None, "I don't know where you are. Set your city in Settings, under General, Weather city."


# ---------- fetching ----------
def fetch_raw(place: dict) -> dict:
    params = {"latitude": place["lat"], "longitude": place["lon"], "current": _CURRENT, "hourly": _HOURLY,
              "daily": _DAILY, "timezone": "auto", "forecast_days": 7, "wind_speed_unit": "kmh"}
    last = None
    for attempt in range(2):   # one quick retry: a dropped connection shouldn't mean "no weather"
        try:
            r = requests.get(FORECAST_URL, params=params, timeout=8)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict) or "current" not in data:
                raise ValueError("no current conditions in the answer")
            return data
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(0.6 * (attempt + 1))
    print(f"Weather: Open-Meteo failed for {place.get('name')}: {last!r}", flush=True)
    raise WeatherError("Weather data is temporarily unavailable.")


def fetch_radar():
    """The latest rain-radar frames ({"host", "frames": [{"time", "path"}]}), or None: the map works without them."""
    try:
        r = requests.get(RADAR_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        frames = [{"time": int(f["time"]), "path": str(f["path"])} for f in (data.get("radar") or {}).get("past") or []
                  if f.get("path")]
        host = str(data.get("host") or "")
        if not frames or not host.startswith("https://"):
            return None
        return {"host": host, "frames": frames[-8:]}
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"Weather: radar frames unavailable ({e!r}); showing the map without them.", flush=True)
        return None


# ---------- shaping ----------
def _num(value, digits=0):
    if value is None:
        return None
    try:
        return round(float(value), digits) if digits else int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _series(block: dict, key: str, i: int):
    values = (block or {}).get(key) or []
    return values[i] if 0 <= i < len(values) else None


def normalize(raw: dict, place: dict, radar=None, fetched_at=None) -> dict:
    """Open-Meteo's answer -> the shape the window draws. Every number may be None (shown as "—"), never missing."""
    fetched_at = fetched_at or time.time()
    cur, hourly, daily = raw.get("current") or {}, raw.get("hourly") or {}, raw.get("daily") or {}
    times = hourly.get("time") or []
    now_local = cur.get("time") or (times[0] if times else "")
    # the hour we're in: the last hourly slot at or before the current observation
    start = 0
    for i, t in enumerate(times):
        if t[:13] <= now_local[:13]:
            start = i
    label, kind = describe(cur.get("weather_code"))
    visibility = cur.get("visibility") if cur.get("visibility") is not None else _series(hourly, "visibility", start)
    uv = cur.get("uv_index") if cur.get("uv_index") is not None else _series(hourly, "uv_index", start)
    current = {
        "temp": _num(cur.get("temperature_2m")), "feels": _num(cur.get("apparent_temperature")),
        "code": cur.get("weather_code"), "label": label, "kind": kind, "is_day": bool(cur.get("is_day", 1)),
        "humidity": _num(cur.get("relative_humidity_2m")), "cloud": _num(cur.get("cloud_cover")),
        "wind": _num(cur.get("wind_speed_10m")), "wind_dir": _num(cur.get("wind_direction_10m")),
        "gusts": _num(cur.get("wind_gusts_10m")), "pressure": _num(cur.get("pressure_msl")),
        "precip": _num(cur.get("precipitation"), 1),
        "visibility_km": _num(visibility / 1000, 1) if isinstance(visibility, (int, float)) else None,
        "uv": _num(uv, 1),
    }
    hours = []
    for i in range(start, min(start + 25, len(times))):
        code = _series(hourly, "weather_code", i)
        h_label, h_kind = describe(code)
        hours.append({
            "time": times[i], "temp": _num(_series(hourly, "temperature_2m", i)),
            "feels": _num(_series(hourly, "apparent_temperature", i)), "code": code, "label": h_label, "kind": h_kind,
            "is_day": bool(_series(hourly, "is_day", i) if _series(hourly, "is_day", i) is not None else 1),
            "rain_chance": _num(_series(hourly, "precipitation_probability", i)),
            "precip": _num(_series(hourly, "precipitation", i), 1), "cloud": _num(_series(hourly, "cloud_cover", i)),
            "wind": _num(_series(hourly, "wind_speed_10m", i)), "wind_dir": _num(_series(hourly, "wind_direction_10m", i)),
        })
    days = []
    for i, date in enumerate(daily.get("time") or []):
        code = _series(daily, "weather_code", i)
        d_label, d_kind = describe(code)
        days.append({
            "date": date, "code": code, "label": d_label, "kind": d_kind,
            "high": _num(_series(daily, "temperature_2m_max", i)), "low": _num(_series(daily, "temperature_2m_min", i)),
            "rain_chance": _num(_series(daily, "precipitation_probability_max", i)),
            "precip": _num(_series(daily, "precipitation_sum", i), 1),
            "wind": _num(_series(daily, "wind_speed_10m_max", i)),
            "wind_dir": _num(_series(daily, "wind_direction_10m_dominant", i)),
            "sunrise": _series(daily, "sunrise", i), "sunset": _series(daily, "sunset", i),
            "uv": _num(_series(daily, "uv_index_max", i), 1),
        })
    today = days[0] if days else {}
    return {
        "place": {"name": place.get("name") or "Your area", "lat": place.get("lat"), "lon": place.get("lon"),
                  "source": place.get("source", "settings")},
        "units": {"temp": "°C", "wind": "km/h", "precip": "mm"},
        "timezone": raw.get("timezone") or "", "utc_offset": int(raw.get("utc_offset_seconds") or 0),
        "observed": now_local, "updated": int(fetched_at),
        "current": current,
        "today": {"high": today.get("high"), "low": today.get("low"), "rain_chance": today.get("rain_chance"),
                  "sunrise": today.get("sunrise"), "sunset": today.get("sunset")},
        "hourly": hours, "daily": days, "radar": radar, "stale": False, "source": SOURCES["open-meteo"],
    }


def summary(data: dict) -> str:
    """One or two spoken sentences: now, today's range, and rain if it's coming."""
    c, t, place = data["current"], data["today"], data["place"]["name"].split(",")[0]
    if c.get("temp") is None:
        return f"I couldn't read the current conditions in {place}."
    text = f"It's {c['temp']} degrees and {c['label'].lower()} in {place}"
    if c.get("feels") is not None and abs(c["feels"] - c["temp"]) >= 2:
        text += f", feeling like {c['feels']}"
    text += "."
    if t.get("high") is not None and t.get("low") is not None:
        text += f" Today: a high of {t['high']} and a low of {t['low']}."
    for hour in data["hourly"][1:13]:   # the next 12 hours
        if (hour.get("rain_chance") or 0) >= 50 and hour["kind"] in ("rain", "drizzle", "storm", "snow"):
            when = datetime.fromisoformat(hour["time"]).strftime("%I %p").lstrip("0")
            word = "snow" if hour["kind"] == "snow" else "rain"
            text += f" Expect {word} around {when}."
            break
    if data.get("stale"):
        text += " (This is the last forecast I could get; the weather service isn't answering right now.)"
    return text


# ---------- the backup source: MET Norway ----------
_met_cache = {}   # (lat, lon) -> (expires at, Last-Modified, raw): their terms ask to respect both headers

# MET's symbol codes ("lightrainshowers_day") -> (what to say, kind), by the part before "_day"/"_night"
MET_SYMBOLS = {
    "clearsky": ("Clear sky", "clear"), "fair": ("Mostly clear", "clear"), "partlycloudy": ("Partly cloudy", "partly"),
    "cloudy": ("Overcast", "cloudy"), "fog": ("Fog", "fog"),
    "lightrain": ("Light rain", "rain"), "rain": ("Rain", "rain"), "heavyrain": ("Heavy rain", "rain"),
    "lightrainshowers": ("Light showers", "rain"), "rainshowers": ("Rain showers", "rain"),
    "heavyrainshowers": ("Heavy showers", "rain"),
    "lightsleet": ("Light sleet", "snow"), "sleet": ("Sleet", "snow"), "heavysleet": ("Heavy sleet", "snow"),
    "lightsleetshowers": ("Sleet showers", "snow"), "sleetshowers": ("Sleet showers", "snow"),
    "heavysleetshowers": ("Heavy sleet showers", "snow"),
    "lightsnow": ("Light snow", "snow"), "snow": ("Snow", "snow"), "heavysnow": ("Heavy snow", "snow"),
    "lightsnowshowers": ("Light snow showers", "snow"), "snowshowers": ("Snow showers", "snow"),
    "heavysnowshowers": ("Heavy snow showers", "snow"),
}


def describe_met(symbol: str) -> tuple:
    base = (symbol or "").split("_")[0]
    if "thunder" in base:
        return "Thunderstorm", "storm"
    return MET_SYMBOLS.get(base, ("Cloudy", "cloudy"))


def fetch_met(place: dict) -> dict:
    lat, lon = round(float(place["lat"]), 4), round(float(place["lon"]), 4)   # their terms: at most 4 decimals
    cached = _met_cache.get((lat, lon))
    if cached and time.time() < cached[0]:
        return cached[2]
    headers = {"User-Agent": USER_AGENT}
    if cached and cached[1]:
        headers["If-Modified-Since"] = cached[1]
    r = requests.get(MET_URL, params={"lat": lat, "lon": lon}, headers=headers, timeout=10)
    if r.status_code == 304 and cached:
        raw = cached[2]
    else:
        r.raise_for_status()
        raw = r.json()
    try:
        expires = parsedate_to_datetime(r.headers["Expires"]).timestamp()
    except (KeyError, TypeError, ValueError):
        expires = time.time() + CACHE_SECONDS
    _met_cache[(lat, lon)] = (max(expires, time.time() + 60), r.headers.get("Last-Modified", ""), raw)
    return raw


def _zone(place: dict):
    """The place's time zone (from the geocoder), else this computer's: MET Norway gives times in UTC."""
    try:
        from zoneinfo import ZoneInfo
        if place.get("timezone"):
            return ZoneInfo(place["timezone"])
    except Exception:
        pass
    return datetime.now().astimezone().tzinfo


def sun_times(lat: float, lon: float, day: date):
    """Sunrise and sunset (UTC datetimes) by NOAA's solar equations, or (None, None) in polar day or night."""
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(lat)
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl)) - math.tan(phi) * math.tan(decl)
    if not -1 <= cos_ha <= 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return (midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime),
            midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime))


def apparent_temperature(temp, humidity, wind_ms):
    """"Feels like" (the Australian Bureau of Meteorology's formula: temperature, humidity and wind)."""
    if temp is None or humidity is None or wind_ms is None:
        return None
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temp / (237.7 + temp))
    return temp + 0.33 * vapour - 0.70 * wind_ms - 4.00


def normalize_met(raw: dict, place: dict, radar=None, fetched_at=None) -> dict:
    """MET Norway's answer -> the same shape normalize() gives for Open-Meteo."""
    fetched_at = fetched_at or time.time()
    zone = _zone(place)
    series = (raw.get("properties") or {}).get("timeseries") or []
    if not series:
        raise WeatherError("Weather data is temporarily unavailable.")
    lat, lon = float(place["lat"]), float(place["lon"])
    suns = {}

    def is_day(moment: datetime) -> bool:
        local_day = moment.astimezone(zone).date()
        if local_day not in suns:
            suns[local_day] = sun_times(lat, lon, local_day)
        rise, setting = suns[local_day]
        if rise is None:   # polar: day if the sun is up at noon
            return abs(lat) < 66 or (lat > 0) == (3 <= local_day.month <= 9)
        return rise <= moment < setting

    def symbol(entry):
        data = entry.get("data") or {}
        for block in ("next_1_hours", "next_6_hours", "next_12_hours"):
            code = ((data.get(block) or {}).get("summary") or {}).get("symbol_code")
            if code:
                return code
        return ""

    entries = []
    for entry in series:
        moment = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
        details = ((entry.get("data") or {}).get("instant") or {}).get("details") or {}
        one = ((entry.get("data") or {}).get("next_1_hours") or {}).get("details") or {}
        six = ((entry.get("data") or {}).get("next_6_hours") or {}).get("details") or {}
        entries.append((moment, details, one, six, symbol(entry)))

    def kmh(ms):
        return None if ms is None else ms * 3.6

    now_moment, now, now_one, _now_six, now_symbol = entries[0]
    label, kind = describe_met(now_symbol)
    uv = now.get("ultraviolet_index_clear_sky")
    current = {
        "temp": _num(now.get("air_temperature")),
        "feels": _num(apparent_temperature(now.get("air_temperature"), now.get("relative_humidity"), now.get("wind_speed"))),
        "code": None, "label": label, "kind": kind, "is_day": is_day(now_moment),
        "humidity": _num(now.get("relative_humidity")), "cloud": _num(now.get("cloud_area_fraction")),
        "wind": _num(kmh(now.get("wind_speed"))), "wind_dir": _num(now.get("wind_from_direction")),
        "gusts": _num(kmh(now.get("wind_speed_of_gust"))), "pressure": _num(now.get("air_pressure_at_sea_level")),
        "precip": _num(now_one.get("precipitation_amount"), 1), "visibility_km": None,
        "uv": _num(uv, 1) if (uv is not None and is_day(now_moment)) else (0.0 if uv is not None else None),
    }
    hours = []
    for moment, details, one, _six, code in entries:
        if len(hours) >= 25:
            break
        if hours and moment - datetime.fromisoformat(hours[-1]["_utc"]) > timedelta(hours=1):
            break   # MET goes 6-hourly after the first days: the hourly chart stops there
        h_label, h_kind = describe_met(code)
        hours.append({
            "_utc": moment.isoformat(), "time": moment.astimezone(zone).strftime("%Y-%m-%dT%H:%M"),
            "temp": _num(details.get("air_temperature")),
            "feels": _num(apparent_temperature(details.get("air_temperature"), details.get("relative_humidity"),
                                               details.get("wind_speed"))),
            "code": None, "label": h_label, "kind": h_kind, "is_day": is_day(moment),
            "rain_chance": _num(one.get("probability_of_precipitation")),
            "precip": _num(one.get("precipitation_amount"), 1), "cloud": _num(details.get("cloud_area_fraction")),
            "wind": _num(kmh(details.get("wind_speed"))), "wind_dir": _num(details.get("wind_from_direction")),
        })
    for hour in hours:
        hour.pop("_utc", None)

    by_day = {}
    for moment, details, one, six, code in entries:
        local = moment.astimezone(zone)
        day = by_day.setdefault(local.date(), {"temps": [], "rain": [], "precip": 0.0, "wind": [], "uv": [], "symbols": []})
        if details.get("air_temperature") is not None:
            day["temps"].append(details["air_temperature"])
        for key in ("air_temperature_max", "air_temperature_min"):
            if six.get(key) is not None:
                day["temps"].append(six[key])
        chance = one.get("probability_of_precipitation", six.get("probability_of_precipitation"))
        if chance is not None:
            day["rain"].append(chance)
        if one:            # hourly steps: each hour's own amount
            day["precip"] += one.get("precipitation_amount") or 0.0
        elif moment.hour % 6 == 0:   # 6-hourly steps (later days, on UTC 00/06/12/18): each block once
            day["precip"] += six.get("precipitation_amount") or 0.0
        if details.get("wind_speed") is not None:
            day["wind"].append(details["wind_speed"])
        if details.get("ultraviolet_index_clear_sky") is not None:
            day["uv"].append(details["ultraviolet_index_clear_sky"])
        if code and 9 <= local.hour <= 15:
            day["symbols"].append(code)
        elif code and not day["symbols"]:
            day["symbols"].append(code)
    days = []
    for local_day in sorted(by_day)[:7]:
        d = by_day[local_day]
        if not d["temps"]:
            continue
        d_label, d_kind = describe_met(d["symbols"][len(d["symbols"]) // 2] if d["symbols"] else "")
        rise, setting = suns.get(local_day) or sun_times(lat, lon, local_day)
        days.append({
            "date": local_day.isoformat(), "code": None, "label": d_label, "kind": d_kind,
            "high": _num(max(d["temps"])), "low": _num(min(d["temps"])),
            "rain_chance": _num(max(d["rain"])) if d["rain"] else None, "precip": _num(d["precip"], 1),
            "wind": _num(kmh(max(d["wind"]))) if d["wind"] else None, "wind_dir": None,
            "sunrise": rise.astimezone(zone).strftime("%Y-%m-%dT%H:%M") if rise else None,
            "sunset": setting.astimezone(zone).strftime("%Y-%m-%dT%H:%M") if setting else None,
            "uv": _num(max(d["uv"]), 1) if d["uv"] else None,
        })
    today = days[0] if days else {}
    offset = now_moment.astimezone(zone).utcoffset()
    return {
        "place": {"name": place.get("name") or "Your area", "lat": place.get("lat"), "lon": place.get("lon"),
                  "source": place.get("source", "settings")},
        "units": {"temp": "°C", "wind": "km/h", "precip": "mm"},
        "timezone": place.get("timezone") or "", "utc_offset": int(offset.total_seconds()) if offset else 0,
        "observed": now_moment.astimezone(zone).strftime("%Y-%m-%dT%H:%M"), "updated": int(fetched_at),
        "current": current,
        "today": {"high": today.get("high"), "low": today.get("low"), "rain_chance": today.get("rain_chance"),
                  "sunrise": today.get("sunrise"), "sunset": today.get("sunset")},
        "hourly": hours, "daily": days, "radar": radar, "stale": False, "source": SOURCES["met"],
    }


# ---------- all together ----------
def get(city: str = "", fallback_city: str = "", radar: bool = True, refresh: bool = False) -> dict:
    """The weather to show, from cache when it's fresh. Raises WeatherError with a sentence to say if there's none."""
    place, problem = locate(city, fallback_city)
    if not place:
        raise WeatherError(problem)
    key = re.sub(r"\s+", " ", place["name"].lower())
    cached = _cache.get(key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS and (cached[1].get("radar") or not radar):
        return cached[1]
    radar_frames = fetch_radar() if radar else None
    try:
        data = normalize(fetch_raw(place), place, radar_frames)
    except WeatherError:
        try:   # Open-Meteo is down or refusing: the free backup, before falling back to an old forecast
            data = normalize_met(fetch_met(place), place, radar_frames)
            print(f"Weather: used MET Norway for {place.get('name')} (Open-Meteo didn't answer).", flush=True)
        except (WeatherError, requests.RequestException, ValueError, KeyError, TypeError) as e:
            print(f"Weather: MET Norway failed too for {place.get('name')}: {e!r}", flush=True)
            if cached and time.time() - cached[0] < STALE_SECONDS:
                return {**cached[1], "stale": True}
            raise WeatherError("Weather data is temporarily unavailable.") from e
    _cache[key] = (time.time(), data)
    return data
