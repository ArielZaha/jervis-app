"""Distance between two places, shown on a 3D globe: "what is the distance between New York and Tel Aviv", "show me the
distance from Paris to Tokyo on the globe". Place names are looked up with Open-Meteo's free geocoding service (the same
one weather_loop already uses), so no API key is needed. The globe itself is drawn by the window (earth.js); this module
only finds the two places and works out the great-circle line between them.
"""
import math
import re
import time

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
EARTH_KM = 6371.0
_CACHE = {}  # lowercased name -> place dict (or None once known not to exist), so a repeated name doesn't hit the network


def _title(request):
    text = request.get("request") if isinstance(request, dict) else request
    return None if text is None else str(text)


_LEAD = r"(?:(?:hey |ok |okay )?(?:jarvis|jervis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets|show me|tell me) )*"
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
_LEAD_WORDS = {"", "hey", "jarvis", "jervis", "ok", "okay", "please", "can", "could", "would", "you", "now", "then", "and",
               "just", "lets", "let", "i", "want", "need", "to", "wanna", "like", "me", "also", "so", "well", "show", "see", "the", "it", "is", "a"}


def _is_command(prefix: str) -> bool:
    return all(w in _LEAD_WORDS for w in re.sub(r"[^a-z ]", " ", prefix).split())


def _clean_name(name: str) -> str:
    name = re.sub(r"^(?:the|a|an)\s+", "", name.strip(" ?.!,"))
    name = re.sub(r"(?:\s+(?:please|now|for me|in (?:km|kilometers|kilometres|miles)))+$", "", name)
    return " ".join(name.split())


_KEYWORDS = ("distance", "between", "far")


def _fix_spelling(n: str) -> str:
    """"distence bettwen", "how farr": the words this needs, however they were typed (only words close to these three)."""
    import difflib

    def fix(match):
        word = match.group(0)
        if len(word) < 3 or word in _KEYWORDS:
            return word
        close = difflib.get_close_matches(word, _KEYWORDS, n=1, cutoff=0.8 if len(word) > 4 else 0.85)
        return close[0] if close and close[0][0] == word[0] else word   # "instance" is not "distance"
    return re.sub(r"[a-z]+", fix, n)


_LOOSE = re.compile(r"\b(?:between|from)\s+(?P<a>.+?)\s+(?:and|to|&)\s+(?P<b>.+?)\s*$")
_TAIL = re.compile(r"\s+(?:in (?:km|kilometers|kilometres|miles)|please|now|for me|on (?:the |a )?(?:3d )?(?:earth|globe|world|map|planet)(?: model)?|"
                   r"(?:pass(?:es)?|fl(?:y|ies)|go(?:es)?|cross(?:es)?|travels?)(?: over| through| across)?|take)$")


def _loose_places(n: str):
    """Any sentence about a distance that names two places: "what is the distance between Ramat Gan to London in km?"."""
    m = _LOOSE.search(n.rstrip(" ?.!"))
    if not m:
        m = re.search(r"\bdistance\s+(?:of\s+)?(?P<a>.+?)\s+(?:to|and)\s+(?P<b>.+?)\s*$", n.rstrip(" ?.!"))
    if not m:
        return None
    b = m.group("b")
    while _TAIL.search(b):
        b = _TAIL.sub("", b)
    a, b = _clean_name(m.group("a")), _clean_name(b)
    if not a or not b or a == b or len(a.split()) > 5 or len(b.split()) > 5:
        return None
    return {"action": "distance", "a": a, "b": b}


# ---------------------------------------------------------------- more kinds of questions
_PAIR = r"(?:from |between )?(?P<{a}>[a-z][\w .'-]*?) (?:to|and|&) (?P<{b}>[a-z][\w .'-]*?)"
_COMPARE = [
    re.compile(rf"^{_LEAD}compare (?:the )?(?:distances? |flights? |routes? )?{_PAIR.format(a='a', b='b')} "
               rf"(?:with|and|vs\.?|versus|to|against) (?:the )?(?:distance |flight |route )?{_PAIR.format(a='c', b='d')}\??$"),
    re.compile(rf"^{_LEAD}{_PAIR.format(a='a', b='b')} (?:vs\.?|versus|compared to|or) {_PAIR.format(a='c', b='d')}\??$"),
]
_WHICH = [   # "which is farther from Tel Aviv, London or Paris?" / "is Tel Aviv closer to London or Paris?"
    re.compile(rf"^{_LEAD}(?:which|what) (?:city |place |one )?is (?P<word>farther|further|closer|nearer)(?: away)? "
               r"(?:from|to) (?P<a>[\w .'-]+?)[,:]? (?P<b>[\w .'-]+?) or (?P<c>[\w .'-]+?)\??$"),
    re.compile(rf"^{_LEAD}(?:which|what) (?:city |place |one )?is (?P<word>farther|further|closer|nearer)(?: away)?[,:]? "
               r"(?P<b>[\w .'-]+?) or (?P<c>[\w .'-]+?),? (?:from|to) (?P<a>[\w .'-]+?)\??$"),
    re.compile(rf"^{_LEAD}is (?P<a>[\w .'-]+?) (?P<word>farther|further|closer|nearer) (?:from|to) (?P<b>[\w .'-]+?) or (?:to |from )?(?P<c>[\w .'-]+?)\??$"),
]
_RADIUS = [
    re.compile(rf"^{_LEAD}(?:what |which |show (?:me )?|find |list )?(?:are )?(?:the )?(?:big |biggest |largest |main )?"
               r"(?:cities|places|towns) (?:that are |are )?(?:within|in a radius of|less than|under) (?P<n>\d+(?:\.\d+)?) ?"
               r"(?P<unit>km|kilometers|kilometres|miles|mi)\b(?: radius)? (?:of|from|around|near) (?P<a>[\w .'-]+?)\??$"),
    re.compile(rf"^{_LEAD}(?:what |which |show (?:me )?|find |list )?(?:are )?(?:the )?(?:big |biggest |largest |main )?(?:cities|places|towns) "
               r"(?:are )?(?:near|close to|around|nearby|next to) (?P<a>[\w .'-]+?)\??$"),
    re.compile(rf"^{_LEAD}(?:what(?:'s| is) |what are |show (?:me )?)?(?:the )?(?:nearby|nearest|closest) (?:cities|places|towns|city) "
               r"(?:to |of |around |near |from )(?P<a>[\w .'-]+?)\??$"),
]
_SUN = [
    ("night_view", re.compile(rf"^{_LEAD}(?:show|see|view|display)? ?(?:me )?(?:the )?(?:earth|world|globe|planet) (?:at|by) night\b.*$")),
    ("where_day", re.compile(r"\bwhere (?:is it|in the world is it|on earth is it) (?:currently |now |right now )?"
                             r"(?:day|daytime|daylight|light|night|nighttime|night time|dark)\b")),
    ("where_day", re.compile(r"\b(?:show|see) (?:me )?(?:where )?(?:the )?(?:day and night|day/night|daylight|terminator)\b")),
    ("sunrise", re.compile(rf"^{_LEAD}(?:show (?:me )?|when is |what time is )?(?:the )?sunrise (?:over|in|at|for) (?P<a>[\w .'-]+?)"
                           r"(?: (?:today|tomorrow))?\??$")),
    ("sunset", re.compile(rf"^{_LEAD}(?:show (?:me )?|when is |what time is )?(?:the )?sunset (?:over|in|at|for) (?P<a>[\w .'-]+?)"
                          r"(?: (?:today|tomorrow))?\??$")),
    ("is_day", re.compile(rf"^{_LEAD}is it (?:currently |now )?(?:day|daytime|night|nighttime|dark|light) (?:in|at) (?P<a>[\w .'-]+?)(?: (?:now|right now))?\??$")),
]
_FLIGHT = re.compile(r"\bhow long (?:is|does|would|will) (?:the |a |it )?(?:flight|it take to fly|take to fly|flying)\b|"
                     r"\bflight (?:time|duration)\b|\bhow long to fly\b")
_COUNTRIES = re.compile(r"\b(?:which|what) countries\b.*\b(?:over|cross|crosses|along|through|pass|passes|fly|flies)\b")


def _place(name: str) -> str:
    name = _clean_name(re.sub(r"^(?:the city of|city of)\s+", "", (name or "").strip()))
    return name if name and len(name.split()) <= 5 and not re.fullmatch(r"(?:it|there|here|that|this)", name) else ""


def parse_more(n: str):
    """The questions beyond one distance: comparisons, places nearby, the Sun, flight times, countries on the way."""
    for what, pattern in _SUN:
        m = pattern.search(n)
        if m:
            place = _place(m.groupdict().get("a") or "")
            if what in ("sunrise", "sunset", "is_day") and not place:
                continue
            return {"action": "sun", "what": what, "place": place or None}
    for pattern in _COMPARE:
        m = pattern.match(n.rstrip(" ?.!"))
        if m:
            pairs = [(_place(m.group("a")), _place(m.group("b"))), (_place(m.group("c")), _place(m.group("d")))]
            if all(x and y and x != y for x, y in pairs):
                return {"action": "compare", "pairs": pairs, "question": None}
    for pattern in _WHICH:
        m = pattern.match(n.rstrip(" ?.!"))
        if m:
            a, b, c = _place(m.group("a")), _place(m.group("b")), _place(m.group("c"))
            if a and b and c and len({a, b, c}) == 3:
                word = "farther" if m.group("word") in ("farther", "further") else "closer"
                return {"action": "compare", "pairs": [(a, b), (a, c)], "question": word}
    for pattern in _RADIUS:
        m = pattern.match(n.rstrip(" ?.!"))
        if m:
            place = _place(m.group("a"))
            if not place:
                continue
            groups = m.groupdict()
            km = float(groups["n"]) * (1.609344 if (groups.get("unit") or "").startswith("mi") else 1) if groups.get("n") else 150.0
            return {"action": "radius", "a": place, "km": max(5.0, min(km, 2000.0))}
    if _FLIGHT.search(n) or _COUNTRIES.search(n):
        wants = "countries" if _COUNTRIES.search(n) else "flight"
        loose = _loose_places(n)
        if loose:
            return {**loose, "wants": wants}
        return {"action": "route_followup", "wants": wants}   # "which countries does it fly over?": the last route
    return None


def parse_request(text: str):
    """None if this isn't about a distance/globe. Else {"action": "close"}, {"action": "reshow", "which": ...},
    {"action": "ask"} (no two places), or {"action": "distance", "a": name, "b": name}."""
    n = _fix_spelling(" ".join((text or "").lower().replace("’", "'").split()))
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
    more = parse_more(n)
    if more:
        return more
    if not re.search(r"\bdistance\b|\bhow far\b|\b(?:3d )?(?:earth|globe)\b", n):
        return None
    for pattern in _PATTERNS:
        m = pattern.match(n)
        if m:
            a, b = _clean_name(m.group("a")), _clean_name(m.group("b"))
            if a and b and a != b:
                return {"action": "distance", "a": a, "b": b}
    if re.search(r"\bdistance\b|\bhow far\b", n):
        loose = _loose_places(n)
        if loose:
            return loose
    if re.search(r"\bdistance\b.*\b(?:between|from)\b|\bhow far (?:is|are|away)\b", n) or re.fullmatch(rf"{_LEAD}(?:show|see|view|display).*\b(?:earth|globe)\b.*", n):
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
            place = {"name": label, "country": r.get("country", ""), "lat": r["latitude"], "lon": r["longitude"],
                     "timezone": r.get("timezone") or ""}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        place = _geocode_osm(name)   # the service is down (not "no such place"): ask OpenStreetMap instead
        if place is None:
            return None              # don't remember a failure as "not found"
    _CACHE[key] = place
    return place


def _label(r: dict) -> str:
    return r["name"] + (f", {r['admin1']}" if r.get("admin1") and r["admin1"] != r["name"] else "") + \
        (f", {r['country']}" if r.get("country") else "")


def resolve(name: str):
    """(place, None) when the name clearly means one place, (None, [two candidates]) when it could fairly mean
    either (both big, in different countries: "Valencia"), or (None, None) when there's no such place.
    "Paris, Texas" or "Valencia Spain" narrows the search to that region or country."""
    raw = " ".join((name or "").split())
    where = ""
    m = re.match(r"^(?P<n>.+?)(?:,\s*|\s+in\s+)(?P<w>[^,]+)$", raw)
    if m:
        raw, where = m.group("n"), m.group("w").strip().lower()
    try:
        response = requests.get(GEOCODE_URL, params={"name": raw, "count": 10, "language": "en"}, timeout=6)
        response.raise_for_status()
        results = [r for r in (response.json().get("results") or []) if "latitude" in r]
    except (requests.RequestException, ValueError):
        return geocode(name), None   # the service can't be reached: the single best guess from elsewhere
    if where:
        narrowed = [r for r in results if where in f"{r.get('admin1', '')} {r.get('country', '')} {r.get('country_code', '')}".lower()]
        results = narrowed or results
    if not results:
        return geocode(name), None   # Open-Meteo has nothing under that name: OpenStreetMap may still know it
    as_place = lambda r: {"name": _label(r), "country": r.get("country", ""), "lat": r["latitude"], "lon": r["longitude"],
                          "timezone": r.get("timezone") or ""}
    by_size = sorted(results, key=lambda r: -(r.get("population") or 0))
    first = by_size[0]
    if not where and len(by_size) > 1:
        second = by_size[1]
        big = lambda r: (r.get("population") or 0) >= 100_000
        if big(first) and big(second) and second.get("country") != first.get("country") \
                and (second.get("population") or 0) >= 0.4 * (first.get("population") or 1):
            return None, [as_place(first), as_place(second)]
    # Open-Meteo lists the most likely match first; a much bigger namesake further down still wins ("Paris" is France)
    chosen = first if (first.get("population") or 0) > 3 * (results[0].get("population") or 0) else results[0]
    place = as_place(chosen)
    _CACHE[" ".join((name or "").lower().split())] = place
    return place, None


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Jarvis/1.0 (+https://github.com/ArielZaha/jervis-app)"   # Nominatim's policy: say who is asking


def _geocode_osm(name: str):
    """OpenStreetMap's free geocoder (Nominatim), used only when Open-Meteo's can't be reached. One request, cached."""
    try:
        response = requests.get(NOMINATIM_URL, params={"q": name, "format": "jsonv2", "limit": 1, "addressdetails": 1,
                                                       "accept-language": "en"},
                                headers={"User-Agent": USER_AGENT}, timeout=8)
        response.raise_for_status()
        results = response.json()
        if not results:
            return None
        r = results[0]
        address = r.get("address") or {}
        city = address.get("city") or address.get("town") or address.get("village") or r.get("name") or name
        country = address.get("country", "")
        return {"name": ", ".join(p for p in (city, address.get("state"), country) if p), "country": country,
                "lat": float(r["lat"]), "lon": float(r["lon"]), "timezone": ""}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


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


def route(a: dict, b: dict, countries: bool = True) -> dict:
    """One route: the straight-line (great-circle) distance, the initial heading, a direct flight's estimate, and the
    countries the path passes over."""
    import geo
    km = great_circle_km(a["lat"], a["lon"], b["lat"], b["lon"])
    out = {"a": a, "b": b, "km": round(km), "miles": round(km * 0.621371),
           "bearing": round(bearing(a["lat"], a["lon"], b["lat"], b["lon"]), 1), "flight": geo.flight_estimate(km)}
    if countries:
        try:
            out["countries"] = geo.countries_along(a["lat"], a["lon"], b["lat"], b["lon"])
        except (OSError, ValueError):
            out["countries"] = None   # the border data is missing: say nothing rather than guess
    return out


def _sun_now() -> dict:
    import geo
    return {**geo.subsolar_point(), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def build(a: dict, b: dict) -> dict:
    """Everything the window needs to draw the globe, fly the route and fill its panel, plus the numbers for the chat.
    The top-level a/b/km/miles/bearing keep older windows (and saved chat chips) working."""
    r = route(a, b)
    return {"kind": "distance", "mode": "route", **r, "routes": [r], "sun": _sun_now(),
            "title": f"{a['name']} \u2192 {b['name']}"}


def build_compare(pairs: list) -> dict:
    """Two or more routes, each measured on its own."""
    routes = [route(a, b, countries=False) for a, b in pairs]
    first = routes[0]
    return {"kind": "distance", "mode": "compare", **first, "routes": routes, "sun": _sun_now(),
            "title": " vs ".join(f"{r['a']['name'].split(',')[0]} \u2192 {r['b']['name'].split(',')[0]}" for r in routes)}


def build_radius(center: dict, km: float, places: list) -> dict:
    return {"kind": "distance", "mode": "radius", "a": center, "b": center, "km": round(km), "miles": round(km * 0.621371),
            "bearing": 0, "routes": [], "radius": {"center": center, "km": round(km), "places": places},
            "sun": _sun_now(), "title": f"Within {round(km):,} km of {center['name']}"}


def build_sun(what: str, place, sun: dict, title: str) -> dict:
    focus = place or {"name": "", "lat": sun["lat"] * (-1 if what == "night_view" else 1),
                      "lon": ((sun["lon"] + 180 + 540) % 360 - 180) if what == "night_view" else sun["lon"]}
    return {"kind": "distance", "mode": "sun", "what": what, "a": focus, "b": focus, "km": 0, "miles": 0, "bearing": 0,
            "routes": [], "sun": sun, "focus": focus, "title": title}


def _round(n: int) -> str:
    return f"{n:,}"


def describe(info: dict, wants: str = "") -> str:
    a, b, km, miles = info["a"], info["b"], info["km"], info["miles"]
    flight = info.get("flight") or {}
    countries = info.get("countries")
    if wants == "flight" and flight:
        lead = (f"A direct flight from {a['name']} to {b['name']} would take roughly {flight['text']}. That's an estimate, "
                f"not a schedule: real flights vary with winds and routing.")
    elif wants == "countries" and countries is not None:
        lead = (f"Flying the shortest path from {a['name']} to {b['name']}, you'd pass over "
                + (_join(countries) if countries else "no land at all") + ".")
    else:
        lead = f"The distance between {a['name']} and {b['name']} is about {_round(km)} kilometers, or {_round(miles)} miles, in a straight line."
    lines = [f"- **From:** {a['name']}", f"- **To:** {b['name']}",
             f"- **Straight-line (great-circle) distance:** {_round(km)} km ({_round(miles)} mi)",
             f"- **Initial heading:** {info['bearing']}° from {a['name']}"]
    if flight and not flight.get("too_short"):
        lines.append(f"- **Direct flight (estimate):** about {_round(flight['route_km'])} km flown, roughly {flight['text']}")
    if countries:
        lines.append(f"- **Passes over:** {_join(countries)}")
    return lead + "\n\n" + "\n".join(lines)


def _join(items: list) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def describe_compare(info: dict, question=None) -> str:
    routes = info["routes"]
    short = lambda p: p["name"].split(",")[0]
    if question and len(routes) == 2:
        a = routes[0]["a"]
        near, far = sorted(routes, key=lambda r: r["km"])
        pick = far if question == "farther" else near
        other = near if pick is far else far
        lead = (f"{short(pick['b'])} is {question} from {short(a)}: {_round(pick['km'])} km, against "
                f"{_round(other['km'])} km to {short(other['b'])}, in a straight line.")
    else:
        longest = max(routes, key=lambda r: r["km"])
        diff = abs(routes[0]["km"] - routes[1]["km"]) if len(routes) == 2 else 0
        lead = (f"{short(longest['a'])} to {short(longest['b'])} is the longer one"
                + (f", by about {_round(diff)} km." if diff else "."))
    lines = [f"- **{short(r['a'])} \u2192 {short(r['b'])}:** {_round(r['km'])} km ({_round(r['miles'])} mi), "
             f"a direct flight roughly {r['flight']['text']} (estimate)" for r in routes]
    return lead + "\n\n" + "\n".join(lines)


def describe_radius(info: dict) -> str:
    r = info["radius"]
    places = r["places"]
    name = r["center"]["name"]
    if not places:
        return f"I don't have any towns or cities within {_round(r['km'])} km of {name} in my map data."
    lead = f"Within {_round(r['km'])} km of {name}, the biggest places are " + _join([p["name"] for p in places[:5]]) + "."
    lines = [f"- **{p['name']}**{', ' + p['country'] if p['country'] and p['country'] not in name else ''}: "
             f"{_round(p['km'])} km away" for p in places]
    return lead + "\n\n" + "\n".join(lines)
