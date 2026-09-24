"""Distance between two places, shown on a 3D globe: "what is the distance between New York and Tel Aviv", "show me the
distance from Paris to Tokyo on the globe". Place names are looked up with Open-Meteo's free geocoding service (the same
one weather_loop already uses), so no API key is needed. The globe itself is drawn by the window (earth.js); this module
only finds the two places and works out the great-circle line between them.
"""
import math
import re

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
EARTH_KM = 6371.0
_CACHE = {}  # lowercased name -> place dict (or None once known not to exist), so a repeated name doesn't hit the network


def _title(request):
    text = request.get("request") if isinstance(request, dict) else request
    return None if text is None else str(text)


_LEAD = r"(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets|show me|tell me) )*"
_VERB = r"(?:show|see|view|display|find|calculate|compute|what(?:'s| is)|whats|tell me|get|check)"
_ON_GLOBE = r"(?:on (?:the |a )?(?:3d )?(?:earth|globe|world|planet)(?: model)?)"
_PATTERNS = [
    re.compile(rf"^{_LEAD}(?:{_VERB} )?(?:me )?(?:the )?distance (?:between|from) (?P<a>.+?) (?:and|to) (?P<b>.+?)(?: {_ON_GLOBE})?(?:\?)?$"),
    re.compile(rf"^{_LEAD}how far (?:is it|is the distance) (?:between|from) (?P<a>.+?) (?:and|to) (?P<b>.+?)(?: {_ON_GLOBE})?\??$"),
    re.compile(rf"^{_LEAD}how far (?:is|are) (?P<a>.+?) from (?P<b>.+?)(?: {_ON_GLOBE})?\??$"),
    re.compile(rf"^{_LEAD}(?:show|see|view|display|open|bring up|pull up) (?:me )?(?:the )?(?:3d )?(?:earth|globe|world)(?: model)? "
               r"(?:with |showing |for )?(?:the distance (?:between|from) )?(?P<a>.+?) (?:and|to) (?P<b>.+?)(?:\?)?$"),
]
_CLOSE = re.compile(r"\b(?:close|hide|dismiss)\b.{0,20}\b(?:globe|earth|world)\b")
_RESHOW = re.compile(
    r"\b(?:show|open|bring\s+up|pull\s+up|display|see|reopen|put\s+up|look\s+at|let\s+me\s+see|go\s+back\s+to)\b.*"
    r"\b(?:globe|earth|world)\b.*\b(?:again|last|previous|earlier|before|back|once\s+more|one\s+more\s+time|next|first)\b"
    r"|\b(?:the\s+)?(?:previous|last|next|earlier|first)\s+(?:globe|earth|world)\b|\b(?:globe|earth)\s+(?:again|from\s+before)\b")
_LEAD_WORDS = {"", "hey", "jervis", "jarvis", "ok", "okay", "please", "can", "could", "would", "you", "now", "then", "and",
               "just", "lets", "let", "i", "want", "need", "to", "wanna", "like", "me", "also", "so", "well", "show", "see", "the", "it", "is", "a"}


def _is_command(prefix: str) -> bool:
    return all(w in _LEAD_WORDS for w in re.sub(r"[^a-z ]", " ", prefix).split())


def _clean_name(name: str) -> str:
    name = re.sub(r"^(?:the|a|an)\s+", "", name.strip(" ?.!,"))
    return " ".join(name.split())


def parse_request(text: str):
    """None if this isn't about a distance/globe. Else {"action": "close"}, {"action": "reshow", "which": ...},
    {"action": "ask"} (no two places), or {"action": "distance", "a": name, "b": name}."""
    n = " ".join((text or "").lower().replace("’", "'").split())
    if not n:
        return None
    if _CLOSE.search(n):
        return {"action": "close"}
    if _RESHOW.search(n):
        m = re.search(r"\b(?:show|open|bring|pull|display|see|reopen|put|look|let|go|previous|last|next|earlier|first|globe|earth|world|planet)\b", n)
        if _is_command(n[:m.start()]):
            which = "first" if re.search(r"\bfirst\b", n) else "prev" if re.search(r"\b(?:previous|before|earlier|back)\b", n) else \
                "next" if re.search(r"\bnext\b", n) else "last"
            return {"action": "reshow", "which": which}
    if not re.search(r"\bdistance\b|\bhow far\b|\b(?:3d )?(?:earth|globe)\b", n):
        return None
    for pattern in _PATTERNS:
        m = pattern.match(n)
        if m:
            a, b = _clean_name(m.group("a")), _clean_name(m.group("b"))
            if a and b and a != b:
                return {"action": "distance", "a": a, "b": b}
    if re.search(r"\bdistance\b.*\b(?:between|from)\b|\bhow far\b", n) or re.fullmatch(rf"{_LEAD}(?:show|see|view|display).*\b(?:earth|globe)\b.*", n):
        return {"action": "ask"}
    return None


def geocode(name: str):
    """{"name", "country", "lat", "lon"} for a place, or None if it can't be found. Cached for the session."""
    key = name.strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    place = None
    try:
        response = requests.get(GEOCODE_URL, params={"name": name, "count": 1, "language": "en"}, timeout=6)
        response.raise_for_status()
        results = response.json().get("results") or []
        if results:
            r = results[0]
            label = r["name"] + (f", {r['admin1']}" if r.get("admin1") and r["admin1"] != r["name"] else "") + \
                    (f", {r['country']}" if r.get("country") else "")
            place = {"name": label, "country": r.get("country", ""), "lat": r["latitude"], "lon": r["longitude"]}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        place = None
    _CACHE[key] = place
    return place


def great_circle_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dphi, dl = map(math.radians, (lat1, lat2 - lat1, lat2, lon2 - lon1)) if False else (
        math.radians(lat1), math.radians(lat2), math.radians(lat2 - lat1), math.radians(lon2 - lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2) -> float:
    """Initial compass heading (degrees, 0 = north) from point 1 towards point 2."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def build(a: dict, b: dict) -> dict:
    """Everything the window needs to draw the globe and its arc, plus the numbers for the chat."""
    km = great_circle_km(a["lat"], a["lon"], b["lat"], b["lon"])
    return {"kind": "distance", "a": a, "b": b, "km": round(km), "miles": round(km * 0.621371),
            "bearing": round(bearing(a["lat"], a["lon"], b["lat"], b["lon"]), 1)}


def _round(n: int) -> str:
    return f"{n:,}"


def describe(info: dict) -> str:
    a, b, km, miles = info["a"], info["b"], info["km"], info["miles"]
    lead = f"The distance between {a['name']} and {b['name']} is about {_round(km)} kilometers, or {_round(miles)} miles, in a straight line."
    lines = [f"- **From:** {a['name']}", f"- **To:** {b['name']}", f"- **Great-circle distance:** {_round(km)} km ({_round(miles)} mi)",
             f"- **Initial heading:** {info['bearing']}° from {a['name']}"]
    return lead + "\n\n" + "\n".join(lines)
