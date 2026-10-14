"""Geography for the globe, from real data only: points along a great-circle route, the countries a route crosses
(Natural Earth's borders), places near a point (Natural Earth's populated places), a flight-time estimate (labelled as
one), and the Sun's actual position, sunrise and sunset (NOAA's solar formulas). No network, no keys.

The data files in geo_data/ are Natural Earth (public domain), reduced to what this needs (see geo_data/README.md).
"""
import datetime as dt
import json
import math
import os
from functools import lru_cache

import paths

EARTH_KM = 6371.0
KM_PER_MILE = 1.609344


# ---------------------------------------------------------------- the sphere
def great_circle_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _xyz(lat, lon):
    p, l = math.radians(lat), math.radians(lon)
    return (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))


def _latlon(v):
    x, y, z = v
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def route_points(lat1, lon1, lat2, lon2, n: int) -> list:
    """n + 1 points (lat, lon) evenly along the shortest path. Crossing the date line or a pole needs no special case:
    the interpolation happens in 3D, and longitudes come back in -180..180."""
    a, b = _xyz(lat1, lon1), _xyz(lat2, lon2)
    dot = max(-1.0, min(1.0, sum(p * q for p, q in zip(a, b))))
    theta = math.acos(dot)
    if theta < 1e-9:
        return [(lat1, lon1)] * (n + 1)
    s = math.sin(theta)
    out = []
    for i in range(n + 1):
        t = i / n
        fa, fb = math.sin((1 - t) * theta) / s, math.sin(t * theta) / s
        out.append(_latlon(tuple(fa * p + fb * q for p, q in zip(a, b))))
    return out


def destination(lat, lon, bearing_deg, km):
    """The point km away from (lat, lon) heading bearing_deg."""
    d, b = km / EARTH_KM, math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


# ---------------------------------------------------------------- flights (estimates, never presented as schedules)
CRUISE_KMH = 830          # a typical airliner's average cruising ground speed
OVERHEAD_HOURS = 0.5      # taxi, climb and descent
ROUTING_FACTOR = 1.05     # airways and air-traffic routing make real tracks a few percent longer than the great circle


def flight_estimate(km: float) -> dict:
    """An estimate for a direct flight: the likely flown distance and time. Not real flight data."""
    route_km = km * ROUTING_FACTOR
    hours = route_km / CRUISE_KMH + OVERHEAD_HOURS
    total_min = int(round(hours * 60 / 5) * 5)
    return {"route_km": round(route_km), "minutes": total_min, "text": duration_text(total_min),
            "too_short": km < 150}


def duration_text(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"{m} min"
    return f"{h} h {m:02d} min" if m else f"{h} h"


# ---------------------------------------------------------------- borders: which countries a route crosses
@lru_cache(maxsize=1)
def _countries():
    with open(paths.resource("geo_data", "countries_50m.json"), encoding="utf-8") as f:
        raw = json.load(f)
    countries = []
    for c in raw:
        polys = []
        for poly in c["polys"]:
            outer = poly[0]
            xs, ys = [p[0] for p in outer], [p[1] for p in outer]
            polys.append(((min(xs), min(ys), max(xs), max(ys)), poly))
        countries.append((c["name"], polys))
    return countries


def _in_ring(lon, lat, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def country_at(lat: float, lon: float):
    """The country this point is in (Natural Earth 1:50m borders), or None at sea."""
    for name, polys in _countries():
        for (x0, y0, x1, y1), poly in polys:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _in_ring(lon, lat, poly[0]) \
                    and not any(_in_ring(lon, lat, hole) for hole in poly[1:]):
                return name
    return None


def countries_along(lat1, lon1, lat2, lon2) -> list:
    """The countries the great-circle route passes over, in order, start and end included. Sampled every ~20 km:
    a country the path only clips for less than that may be missed, so this says "passes over", never "only"."""
    km = great_circle_km(lat1, lon1, lat2, lon2)
    n = max(8, min(1500, int(km / 20)))
    seen = []
    for lat, lon in route_points(lat1, lon1, lat2, lon2, n):
        name = country_at(lat, lon)
        if name and (not seen or seen[-1] != name) and name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------- places near a point
@lru_cache(maxsize=1)
def _places():
    with open(paths.resource("geo_data", "places_10m.json"), encoding="utf-8") as f:
        return json.load(f)   # [name, country, region, lat, lon, population, is_capital]


def places_near(lat: float, lon: float, radius_km: float, limit: int = 12, exclude_name: str = "") -> list:
    """Populated places within radius_km, biggest first: [{"name", "country", "lat", "lon", "km", "population"}]."""
    found = []
    skip = (exclude_name or "").split(",")[0].strip().lower()
    for name, country, region, plat, plon, pop, cap in _places():
        if abs(plat - lat) > radius_km / 111.0 + 0.5:
            continue
        km = great_circle_km(lat, lon, plat, plon)
        if km > radius_km or (km < 4 and name.lower() == skip) or km < 0.5:
            continue
        found.append({"name": name, "country": country, "lat": plat, "lon": plon, "km": round(km), "population": pop})
    found.sort(key=lambda p: (-p["population"], p["km"]))
    return found[:limit]


# ---------------------------------------------------------------- the Sun (the Astronomical Almanac's solar formulas, ~0.01°)
def _julian_days(when: dt.datetime) -> float:
    """Days since the J2000.0 epoch (2000-01-01 12:00 UTC)."""
    epoch = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
    return (when.astimezone(dt.timezone.utc) - epoch).total_seconds() / 86400


def _solar_terms(when: dt.datetime):
    """(equation of time in minutes, declination in radians, right ascension in degrees, days since J2000)."""
    n = _julian_days(when)
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    decl = math.asin(math.sin(eps) * math.sin(lam))
    eqtime = 4 * ((L - ra + 540) % 360 - 180)
    return eqtime, decl, ra, n


def subsolar_point(when: dt.datetime = None) -> dict:
    """Where the Sun is straight overhead right now (or at `when`): {"lat", "lon"}."""
    when = when or dt.datetime.now(dt.timezone.utc)
    _, decl, ra, n = _solar_terms(when)
    gmst = (280.46061837 + 360.98564736629 * n) % 360   # Greenwich sidereal time, degrees
    lon = (ra - gmst + 540) % 360 - 180
    return {"lat": round(math.degrees(decl), 3), "lon": round(lon, 3)}


def sun_elevation(lat: float, lon: float, when: dt.datetime = None) -> float:
    """The Sun's height above the horizon there, in degrees (negative: below it)."""
    s = subsolar_point(when)
    a, b = _xyz(lat, lon), _xyz(s["lat"], s["lon"])
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(a, b))))))


def sun_events(lat: float, lon: float, day: dt.date):
    """Sunrise and sunset on that day, as UTC datetimes: {"sunrise", "sunset"}, or {"polar": "day" | "night"}."""
    noon = dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.timezone.utc) - dt.timedelta(hours=lon / 15)
    eqtime, decl, _, _ = _solar_terms(noon)   # the terms at that place's own local noon
    zenith = math.radians(90.833)   # the Sun's upper edge, with atmospheric refraction
    p = math.radians(lat)
    cos_ha = math.cos(zenith) / (math.cos(p) * math.cos(decl)) - math.tan(p) * math.tan(decl)
    if cos_ha < -1:
        return {"polar": "day"}
    if cos_ha > 1:
        return {"polar": "night"}
    ha = math.degrees(math.acos(cos_ha))
    midnight = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    rise = 720 - 4 * (lon + ha) - eqtime
    set_ = 720 - 4 * (lon - ha) - eqtime
    return {"sunrise": midnight + dt.timedelta(minutes=rise), "sunset": midnight + dt.timedelta(minutes=set_)}
