"""The world clock: "what time is it in Tokyo?", "compare the time in Israel and Los Angeles", "time around the world".

  parse_request()   is this about the time somewhere right now, and where
  resolve()         a spoken place -> a real place with its IANA time zone ("Asia/Tokyo"), or a reason it can't be
  describe()        what Jarvis says: the time there, the day if it differs, how far ahead or behind
  window()          what the clock window is sent (it keeps its own live time from then on)

Time zones are never offsets written down here: every place carries an IANA zone name and the time is worked out from
Python's zoneinfo database, so daylight saving and rule changes are followed. Places Jarvis doesn't know by heart are
looked up with the same geocoder as the globe (earth.resolve), which answers with the zone. Nothing here touches the
UI; app.py sends the result to the window.
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import geo

# Places asked about most, known by heart so the answer needs no network: said name -> (shown, country, zone, lat, lon).
# The coordinates are only for sunrise and sunset; a country stands for its capital there.
_KNOWN = {
    # Asia and the Pacific
    "tokyo": ("Tokyo", "Japan", "Asia/Tokyo", 35.68, 139.69), "osaka": ("Osaka", "Japan", "Asia/Tokyo", 34.69, 135.50),
    "japan": ("Japan", "", "Asia/Tokyo", 35.68, 139.69),
    "seoul": ("Seoul", "South Korea", "Asia/Seoul", 37.57, 126.98), "south korea": ("South Korea", "", "Asia/Seoul", 37.57, 126.98),
    "korea": ("South Korea", "", "Asia/Seoul", 37.57, 126.98),
    "beijing": ("Beijing", "China", "Asia/Shanghai", 39.90, 116.41), "shanghai": ("Shanghai", "China", "Asia/Shanghai", 31.23, 121.47),
    "china": ("China", "", "Asia/Shanghai", 39.90, 116.41), "hong kong": ("Hong Kong", "", "Asia/Hong_Kong", 22.32, 114.17),
    "taipei": ("Taipei", "Taiwan", "Asia/Taipei", 25.03, 121.57), "taiwan": ("Taiwan", "", "Asia/Taipei", 25.03, 121.57),
    "singapore": ("Singapore", "", "Asia/Singapore", 1.35, 103.82), "bangkok": ("Bangkok", "Thailand", "Asia/Bangkok", 13.76, 100.50),
    "thailand": ("Thailand", "", "Asia/Bangkok", 13.76, 100.50), "hanoi": ("Hanoi", "Vietnam", "Asia/Bangkok", 21.03, 105.85),
    "vietnam": ("Vietnam", "", "Asia/Ho_Chi_Minh", 21.03, 105.85), "manila": ("Manila", "Philippines", "Asia/Manila", 14.60, 120.98),
    "philippines": ("Philippines", "", "Asia/Manila", 14.60, 120.98), "jakarta": ("Jakarta", "Indonesia", "Asia/Jakarta", -6.21, 106.85),
    "kuala lumpur": ("Kuala Lumpur", "Malaysia", "Asia/Kuala_Lumpur", 3.14, 101.69),
    "mumbai": ("Mumbai", "India", "Asia/Kolkata", 19.08, 72.88), "bombay": ("Mumbai", "India", "Asia/Kolkata", 19.08, 72.88),
    "delhi": ("Delhi", "India", "Asia/Kolkata", 28.61, 77.21), "new delhi": ("New Delhi", "India", "Asia/Kolkata", 28.61, 77.21),
    "bangalore": ("Bangalore", "India", "Asia/Kolkata", 12.97, 77.59), "india": ("India", "", "Asia/Kolkata", 28.61, 77.21),
    "karachi": ("Karachi", "Pakistan", "Asia/Karachi", 24.86, 67.01), "pakistan": ("Pakistan", "", "Asia/Karachi", 33.69, 73.06),
    "dubai": ("Dubai", "United Arab Emirates", "Asia/Dubai", 25.20, 55.27), "abu dhabi": ("Abu Dhabi", "United Arab Emirates", "Asia/Dubai", 24.45, 54.38),
    "uae": ("United Arab Emirates", "", "Asia/Dubai", 24.45, 54.38), "united arab emirates": ("United Arab Emirates", "", "Asia/Dubai", 24.45, 54.38),
    "the emirates": ("United Arab Emirates", "", "Asia/Dubai", 24.45, 54.38),
    "riyadh": ("Riyadh", "Saudi Arabia", "Asia/Riyadh", 24.71, 46.68), "saudi arabia": ("Saudi Arabia", "", "Asia/Riyadh", 24.71, 46.68),
    "doha": ("Doha", "Qatar", "Asia/Qatar", 25.29, 51.53), "qatar": ("Qatar", "", "Asia/Qatar", 25.29, 51.53),
    "tel aviv": ("Tel Aviv", "Israel", "Asia/Jerusalem", 32.08, 34.78), "jerusalem": ("Jerusalem", "Israel", "Asia/Jerusalem", 31.77, 35.21),
    "haifa": ("Haifa", "Israel", "Asia/Jerusalem", 32.79, 34.99), "israel": ("Israel", "", "Asia/Jerusalem", 31.77, 35.21),
    "istanbul": ("Istanbul", "Turkey", "Europe/Istanbul", 41.01, 28.98), "turkey": ("Turkey", "", "Europe/Istanbul", 39.93, 32.86),
    "sydney": ("Sydney", "Australia", "Australia/Sydney", -33.87, 151.21), "melbourne": ("Melbourne", "Australia", "Australia/Melbourne", -37.81, 144.96),
    "brisbane": ("Brisbane", "Australia", "Australia/Brisbane", -27.47, 153.03), "perth": ("Perth", "Australia", "Australia/Perth", -31.95, 115.86),
    "auckland": ("Auckland", "New Zealand", "Pacific/Auckland", -36.85, 174.76), "wellington": ("Wellington", "New Zealand", "Pacific/Auckland", -41.29, 174.78),
    "new zealand": ("New Zealand", "", "Pacific/Auckland", -41.29, 174.78),
    "honolulu": ("Honolulu", "United States", "Pacific/Honolulu", 21.31, -157.86), "hawaii": ("Hawaii", "United States", "Pacific/Honolulu", 21.31, -157.86),
    # Europe and Africa
    "london": ("London", "United Kingdom", "Europe/London", 51.51, -0.13), "uk": ("United Kingdom", "", "Europe/London", 51.51, -0.13),
    "the uk": ("United Kingdom", "", "Europe/London", 51.51, -0.13), "united kingdom": ("United Kingdom", "", "Europe/London", 51.51, -0.13),
    "britain": ("United Kingdom", "", "Europe/London", 51.51, -0.13), "great britain": ("United Kingdom", "", "Europe/London", 51.51, -0.13),
    "england": ("England", "United Kingdom", "Europe/London", 51.51, -0.13), "scotland": ("Scotland", "United Kingdom", "Europe/London", 55.95, -3.19),
    "manchester": ("Manchester", "United Kingdom", "Europe/London", 53.48, -2.24), "edinburgh": ("Edinburgh", "United Kingdom", "Europe/London", 55.95, -3.19),
    "dublin": ("Dublin", "Ireland", "Europe/Dublin", 53.35, -6.26), "ireland": ("Ireland", "", "Europe/Dublin", 53.35, -6.26),
    "paris": ("Paris", "France", "Europe/Paris", 48.85, 2.35), "france": ("France", "", "Europe/Paris", 48.85, 2.35),
    "berlin": ("Berlin", "Germany", "Europe/Berlin", 52.52, 13.41), "munich": ("Munich", "Germany", "Europe/Berlin", 48.14, 11.58),
    "frankfurt": ("Frankfurt", "Germany", "Europe/Berlin", 50.11, 8.68), "germany": ("Germany", "", "Europe/Berlin", 52.52, 13.41),
    "madrid": ("Madrid", "Spain", "Europe/Madrid", 40.42, -3.70), "barcelona": ("Barcelona", "Spain", "Europe/Madrid", 41.39, 2.17),
    "spain": ("Spain", "", "Europe/Madrid", 40.42, -3.70), "lisbon": ("Lisbon", "Portugal", "Europe/Lisbon", 38.72, -9.14),
    "portugal": ("Portugal", "", "Europe/Lisbon", 38.72, -9.14),
    "rome": ("Rome", "Italy", "Europe/Rome", 41.90, 12.50), "milan": ("Milan", "Italy", "Europe/Rome", 45.46, 9.19),
    "italy": ("Italy", "", "Europe/Rome", 41.90, 12.50),
    "amsterdam": ("Amsterdam", "Netherlands", "Europe/Amsterdam", 52.37, 4.90), "netherlands": ("Netherlands", "", "Europe/Amsterdam", 52.37, 4.90),
    "the netherlands": ("Netherlands", "", "Europe/Amsterdam", 52.37, 4.90), "holland": ("Netherlands", "", "Europe/Amsterdam", 52.37, 4.90),
    "brussels": ("Brussels", "Belgium", "Europe/Brussels", 50.85, 4.35), "belgium": ("Belgium", "", "Europe/Brussels", 50.85, 4.35),
    "zurich": ("Zurich", "Switzerland", "Europe/Zurich", 47.38, 8.54), "geneva": ("Geneva", "Switzerland", "Europe/Zurich", 46.20, 6.14),
    "switzerland": ("Switzerland", "", "Europe/Zurich", 46.95, 7.45),
    "vienna": ("Vienna", "Austria", "Europe/Vienna", 48.21, 16.37), "austria": ("Austria", "", "Europe/Vienna", 48.21, 16.37),
    "prague": ("Prague", "Czechia", "Europe/Prague", 50.08, 14.44), "budapest": ("Budapest", "Hungary", "Europe/Budapest", 47.50, 19.04),
    "warsaw": ("Warsaw", "Poland", "Europe/Warsaw", 52.23, 21.01), "poland": ("Poland", "", "Europe/Warsaw", 52.23, 21.01),
    "stockholm": ("Stockholm", "Sweden", "Europe/Stockholm", 59.33, 18.07), "sweden": ("Sweden", "", "Europe/Stockholm", 59.33, 18.07),
    "oslo": ("Oslo", "Norway", "Europe/Oslo", 59.91, 10.75), "norway": ("Norway", "", "Europe/Oslo", 59.91, 10.75),
    "copenhagen": ("Copenhagen", "Denmark", "Europe/Copenhagen", 55.68, 12.57), "denmark": ("Denmark", "", "Europe/Copenhagen", 55.68, 12.57),
    "helsinki": ("Helsinki", "Finland", "Europe/Helsinki", 60.17, 24.94), "finland": ("Finland", "", "Europe/Helsinki", 60.17, 24.94),
    "reykjavik": ("Reykjavik", "Iceland", "Atlantic/Reykjavik", 64.15, -21.94), "iceland": ("Iceland", "", "Atlantic/Reykjavik", 64.15, -21.94),
    "athens": ("Athens", "Greece", "Europe/Athens", 37.98, 23.73), "greece": ("Greece", "", "Europe/Athens", 37.98, 23.73),
    "kyiv": ("Kyiv", "Ukraine", "Europe/Kyiv", 50.45, 30.52), "kiev": ("Kyiv", "Ukraine", "Europe/Kyiv", 50.45, 30.52),
    "ukraine": ("Ukraine", "", "Europe/Kyiv", 50.45, 30.52), "moscow": ("Moscow", "Russia", "Europe/Moscow", 55.76, 37.62),
    "cairo": ("Cairo", "Egypt", "Africa/Cairo", 30.04, 31.24), "egypt": ("Egypt", "", "Africa/Cairo", 30.04, 31.24),
    "johannesburg": ("Johannesburg", "South Africa", "Africa/Johannesburg", -26.20, 28.05),
    "cape town": ("Cape Town", "South Africa", "Africa/Johannesburg", -33.92, 18.42),
    "south africa": ("South Africa", "", "Africa/Johannesburg", -25.75, 28.19),
    "nairobi": ("Nairobi", "Kenya", "Africa/Nairobi", -1.29, 36.82), "kenya": ("Kenya", "", "Africa/Nairobi", -1.29, 36.82),
    "lagos": ("Lagos", "Nigeria", "Africa/Lagos", 6.52, 3.38), "nigeria": ("Nigeria", "", "Africa/Lagos", 9.08, 7.40),
    "casablanca": ("Casablanca", "Morocco", "Africa/Casablanca", 33.57, -7.59), "morocco": ("Morocco", "", "Africa/Casablanca", 34.02, -6.84),
    # The Americas
    "new york": ("New York", "United States", "America/New_York", 40.71, -74.01), "new york city": ("New York", "United States", "America/New_York", 40.71, -74.01),
    "nyc": ("New York", "United States", "America/New_York", 40.71, -74.01), "manhattan": ("New York", "United States", "America/New_York", 40.71, -74.01),
    "boston": ("Boston", "United States", "America/New_York", 42.36, -71.06), "miami": ("Miami", "United States", "America/New_York", 25.76, -80.19),
    "washington": ("Washington, D.C.", "United States", "America/New_York", 38.91, -77.04), "washington dc": ("Washington, D.C.", "United States", "America/New_York", 38.91, -77.04),
    "atlanta": ("Atlanta", "United States", "America/New_York", 33.75, -84.39), "florida": ("Florida", "United States", "America/New_York", 25.76, -80.19),
    "chicago": ("Chicago", "United States", "America/Chicago", 41.88, -87.63), "houston": ("Houston", "United States", "America/Chicago", 29.76, -95.37),
    "dallas": ("Dallas", "United States", "America/Chicago", 32.78, -96.80), "texas": ("Texas", "United States", "America/Chicago", 30.27, -97.74),
    "denver": ("Denver", "United States", "America/Denver", 39.74, -104.99), "colorado": ("Colorado", "United States", "America/Denver", 39.74, -104.99),
    "phoenix": ("Phoenix", "United States", "America/Phoenix", 33.45, -112.07), "arizona": ("Arizona", "United States", "America/Phoenix", 33.45, -112.07),
    "los angeles": ("Los Angeles", "United States", "America/Los_Angeles", 34.05, -118.24), "la": ("Los Angeles", "United States", "America/Los_Angeles", 34.05, -118.24),
    "l a": ("Los Angeles", "United States", "America/Los_Angeles", 34.05, -118.24),
    "san francisco": ("San Francisco", "United States", "America/Los_Angeles", 37.77, -122.42), "sf": ("San Francisco", "United States", "America/Los_Angeles", 37.77, -122.42),
    "san diego": ("San Diego", "United States", "America/Los_Angeles", 32.72, -117.16), "seattle": ("Seattle", "United States", "America/Los_Angeles", 47.61, -122.33),
    "las vegas": ("Las Vegas", "United States", "America/Los_Angeles", 36.17, -115.14), "california": ("California", "United States", "America/Los_Angeles", 34.05, -118.24),
    "silicon valley": ("Silicon Valley", "United States", "America/Los_Angeles", 37.39, -122.08),
    "anchorage": ("Anchorage", "United States", "America/Anchorage", 61.22, -149.90), "alaska": ("Alaska", "United States", "America/Anchorage", 61.22, -149.90),
    "toronto": ("Toronto", "Canada", "America/Toronto", 43.65, -79.38), "montreal": ("Montreal", "Canada", "America/Toronto", 45.50, -73.57),
    "vancouver": ("Vancouver", "Canada", "America/Vancouver", 49.28, -123.12),
    "mexico city": ("Mexico City", "Mexico", "America/Mexico_City", 19.43, -99.13),
    "sao paulo": ("São Paulo", "Brazil", "America/Sao_Paulo", -23.55, -46.63), "rio": ("Rio de Janeiro", "Brazil", "America/Sao_Paulo", -22.91, -43.17),
    "rio de janeiro": ("Rio de Janeiro", "Brazil", "America/Sao_Paulo", -22.91, -43.17),
    "buenos aires": ("Buenos Aires", "Argentina", "America/Argentina/Buenos_Aires", -34.60, -58.38),
    "argentina": ("Argentina", "", "America/Argentina/Buenos_Aires", -34.60, -58.38),
    "bogota": ("Bogotá", "Colombia", "America/Bogota", 4.71, -74.07), "lima": ("Lima", "Peru", "America/Lima", -12.05, -77.04),
    "santiago": ("Santiago", "Chile", "America/Santiago", -33.45, -70.67),
}
# Countries and regions with more than one time zone: the honest answer is a question, not a guess.
_MANY_ZONES = {
    "usa": "The United States", "us": "The United States", "the us": "The United States", "the usa": "The United States",
    "united states": "The United States", "the united states": "The United States", "america": "The United States",
    "the states": "The United States", "canada": "Canada", "russia": "Russia", "australia": "Australia", "brazil": "Brazil",
    "mexico": "Mexico", "indonesia": "Indonesia", "kazakhstan": "Kazakhstan", "mongolia": "Mongolia", "europe": "Europe",
    "asia": "Asia", "africa": "Africa", "south america": "South America", "north america": "North America",
}
_HOME_WORDS = {"here", "home", "me", "us", "my time", "my city", "my place", "local", "local time", "where i am", "my location"}
AROUND_THE_WORLD = ("los angeles", "new york", "london", "dubai", "tokyo", "sydney")
MAX_PLACES = 6

_LEAD = r"(?:(?:hey |ok |okay )?(?:jarvis|jervis)[ ,]+)?(?:(?:please|can you|could you|would you|and|so|now|also) )*"
_ASK = (r"(?:what(?:'s| is|s)? (?:the )?(?:current |local |exact |right )?time(?: is it| it is)?|what time(?: is it| it is)?|"
        r"(?:tell|show|give) me (?:the |what )?(?:current |local |exact )?time(?: it is| is it)?|do you know (?:what )?(?:the )?time(?: it is| is it)?|"
        r"check the time|how late is it)")
_NOW = r"(?: right now| now| currently| at the moment| at this moment| today)?"
_IN = r"(?:in|at|over in|out in)"
_PATTERNS = [
    ("time", re.compile(rf"^{_LEAD}{_ASK}{_NOW} {_IN} (?P<p>.+)$")),
    ("bare", re.compile(rf"^{_LEAD}(?:the |current |local )*time{_NOW} in (?P<p>.+)$")),   # "time in dubai": only places known by heart
    ("time", re.compile(rf"^{_LEAD}(?:open|show|bring up|pull up|put up|launch)(?: me)? (?:the |a |my )?(?:world )?clock(?: window)? (?:in|for|at|on|with) (?P<p>.+)$")),
    ("time", re.compile(rf"^{_LEAD}(?:open|show|bring up|pull up|put up)(?: me)? (?:the )?(?:current |local )?time {_IN} (?P<p>.+)$")),
    ("difference", re.compile(rf"^{_LEAD}(?:what(?:'s| is|s) |show me |tell me )?(?:the )?time (?:difference|gap|zone difference) (?:between|from) (?P<p>.+)$")),
    ("difference", re.compile(rf"^{_LEAD}(?:what(?:'s| is|s) )?(?:the )?(?:hour|hours) difference between (?P<p>.+)$")),
    ("difference", re.compile(rf"^{_LEAD}how many hours (?:is |are )?(?P<p>.+?) (?:ahead|behind|apart)(?: (?:of|from|than) (?P<q>.+))?$")),
    ("difference", re.compile(rf"^{_LEAD}how (?:far|many hours) (?:ahead|behind) (?:is|are) (?P<p>.+?)(?: (?:of|from|than|compared to) (?P<q>.+))?$")),
    ("difference", re.compile(rf"^{_LEAD}is (?P<p>.+?) (?:ahead of|behind) (?P<q>.+)$")),
    ("compare", re.compile(rf"^{_LEAD}compare (?:the )?(?:current |local )?times? (?:in|of|between|for) (?P<p>.+)$")),
    ("sidebyside", re.compile(rf"^{_LEAD}(?:show|put)(?: me)? (?:the )?(?:times? (?:in|for) )?(?P<p>.+?) (?:side by side|next to each other)(?: on the (?:world )?clock)?$")),
]
_WORLD = re.compile(rf"^{_LEAD}(?:{_ASK}{_NOW} |(?:open|show|bring up|pull up|put up|launch)(?: me)? (?:the )?(?:current )?(?:time )?)?"
                    r"(?:(?:around|across|all over|all around) the (?:world|globe)|(?:in |for )?(?:the )?(?:major|big|main) cities(?: of the world| around the world)?)$"
                    rf"|^{_LEAD}(?:open|show|bring up|pull up|put up|launch)(?: me)? (?:the |my )?world (?:clock|time|times)(?: window)?$"
                    rf"|^{_LEAD}(?:the )?world (?:clock|times?)$")
_THERE = re.compile(rf"^{_LEAD}(?:and )?(?:{_ASK}|(?:the )?time){_NOW} (?:over )?there{_NOW}$")
_CLOSE = re.compile(rf"^{_LEAD}(?:close|hide|dismiss|exit) (?:the |my )?(?:world )?clock(?: window)?$")
_ADD = re.compile(rf"^{_LEAD}(?:add|include|put|and add) (?P<p>.+?)(?: (?:to|on|in) (?:the |my )?(?:world )?clock| too| as well)*$")
_ALSO = re.compile(rf"^{_LEAD}(?:and |what about |how about |and what about |and how about )(?:{_IN} )?(?P<p>.+)$")
_REMOVE = re.compile(rf"^{_LEAD}(?:remove|take off|take away|drop|delete) (?P<p>.+?)(?: (?:from|off) (?:the |my )?(?:world )?clock)?$")
# Not the time right now: a time in the past or the future, an event, or a sum ("when it's 5 pm here", "in 3 hours").
_NOT_NOW = re.compile(r"\b(?:when|if|was|were|will|would|ago|later|earlier|yesterday|tomorrow|tonight|last|next|meeting|flight|"
                      r"event|game|match|starts?|opens?|closes?|at \d|\d ?(?:am|pm)|\d o'?clock|noon|midnight|in \d+ |in (?:an?|one|two|three|"
                      r"four|five|six|ten|twelve) (?:hours?|minutes?|days?))\b")
_DAYLIGHT = re.compile(r"\s*,?\s*(?:and |also |plus )?(?:(?:tell me )?(?:if|whether) it(?:'s| is)|is it)(?: still| already| currently)? "
                       r"(?:day|daytime|day time|daylight|light|night|nighttime|night time|dark|morning|evening)(?: or (?:day|night|daytime|nighttime))?"
                       r"(?: time)?(?: (?:over )?there| out)?(?: right now| now)?$")
_TRIM = re.compile(r"(?:\s+(?:right now|now|currently|at the moment|please|today|exactly|then))+$")


def _normal(text: str) -> str:
    n = (text or "").lower().replace("’", "'").replace("“", "").replace("”", "")
    return " ".join(re.sub(r"[^a-z0-9',&/. -]", " ", n).replace(" vs. ", " vs ").split()).strip(" .,!?")


def _key(name: str) -> str:
    key = " ".join(re.sub(r"[^a-z' ]", " ", (name or "").lower()).split())
    return re.sub(r"^(?:the )?(?:city of |state of )", "", key)


def _by_heart(name: str) -> bool:
    key = _key(name)
    return key in _KNOWN or key in _MANY_ZONES or key in _HOME_WORDS


def known_name(name: str) -> str:
    """The name a place known by heart is shown under ("nyc" -> "New York"), else the name as said."""
    known = _KNOWN.get(_key(name))
    return known[0] if known else name


def _unglue(name: str) -> list:
    """"london tokyo" (said without a comma) -> ["london", "tokyo"], when every piece is a place known by heart."""
    if _by_heart(name):
        return [name]
    words, out, i = name.split(), [], 0
    while i < len(words):
        for size in range(min(3, len(words) - i), 0, -1):
            piece = " ".join(words[i:i + size])
            if _by_heart(piece):
                out.append(piece)
                i += size
                break
        else:
            return [name]
    return out


def _places(spoken: str) -> list:
    """"israel and los angeles" / "london, tokyo and here" -> the names, in the order said."""
    spoken = _TRIM.sub("", spoken.strip(" ,.?!"))
    parts = re.split(r"\s*(?:,|&|/|\band\b|\bvs\b|\bversus\b|\bor\b|\bwith\b|\bto\b|\bcompared to\b)\s*", spoken)
    names = []
    for part in parts:
        name = re.sub(r"^(?:the time in |time in |in |the city of |city of )", "", _TRIM.sub("", part.strip(" ,.?!"))).strip()
        for piece in _unglue(name) if name else []:
            if piece not in names:
                names.append(piece)
    return names


def parse_request(text: str, clock_open: bool = False, shown=()):
    """None when this isn't about the time somewhere right now. Else one of:
      {"action": "show", "places": [...], "difference": bool, "daylight": bool}   places as they were said
      {"action": "world"} · {"action": "there"} · {"action": "close"}
      {"action": "add" | "remove", "places": [...]}    only while the clock is in use (clock_open).
    shown: the names on the clock now, so "remove Kathmandu" is understood for a place not known by heart."""
    n = _normal(text)
    if not n:
        return None
    if _CLOSE.match(n):
        return {"action": "close"}
    daylight = bool(_DAYLIGHT.search(n))
    asked = _DAYLIGHT.sub("", n).strip(" ,") if daylight else n
    if _WORLD.match(asked):
        return {"action": "world"}
    if _THERE.match(asked):
        return {"action": "there", "daylight": daylight}
    for kind, pattern in _PATTERNS:
        m = pattern.match(asked)
        if not m:
            continue
        spoken = m.group("p") + (" and " + m.group("q") if m.groupdict().get("q") else "")
        if _NOT_NOW.search(spoken):
            return None
        names = _places(spoken)
        if not names or len(names) > MAX_PLACES or any(len(name.split()) > 5 for name in names):
            return None
        if kind in ("compare", "sidebyside") and len(names) < 2:
            return None
        if kind == "bare" and not all(_by_heart(name) for name in names):
            return None            # "time in a bottle"
        if kind == "sidebyside" and not (clock_open or all(_by_heart(name) for name in names)):
            return None            # "show me the two photos side by side"
        if kind == "difference" and len(names) == 1:
            names.append("here")   # "how many hours ahead is Tokyo": than me
        if all(name in _HOME_WORDS for name in names):
            return None            # "what time is it here": the ordinary clock, not this window
        return {"action": "show", "places": names, "daylight": daylight,
                "difference": kind == "difference" or (kind in ("compare", "sidebyside") and len(names) == 2)}
    if clock_open:   # short follow-ups while the clock is up: only for the clock by name, or for places known by heart
        named = bool(re.search(r"\bclock\b", n))
        m = _REMOVE.match(n)
        if m:
            names = _places(m.group("p"))
            on_clock = {_key(name) for name in shown}
            if names and (named or all(_by_heart(name) or _key(name) in on_clock for name in names)):
                return {"action": "remove", "places": names}
        m = _ADD.match(n) or _ALSO.match(asked)
        if m and not _NOT_NOW.search(m.group("p")):
            names = _places(m.group("p"))
            if names and len(names) <= MAX_PLACES and all(len(name.split()) <= 4 for name in names) \
                    and (named or all(_by_heart(name) for name in names)):
                return {"action": "add", "places": names, "daylight": daylight}
    return None


# ---------------------------------------------------------------- where
def _place(name: str, country: str, zone: str, lat=None, lon=None) -> dict:
    return {"name": name, "country": country, "tz": zone, "lat": lat, "lon": lon}


def home_place(city: str = "", zone: str = "") -> dict:
    """The user's own place: the computer's time zone, named after the weather city when there is one."""
    return {"name": (city or "").split(",")[0].strip() or "Your time", "country": "", "tz": zone, "lat": None, "lon": None, "home": True}


def resolve(name: str, lookup=None) -> tuple:
    """A place as it was said -> ("ok", place) · ("home", None) · ("ambiguous", [place, place]) · ("many", what to
    say) · ("missing", what to say). lookup is earth.resolve (or a stand-in): name -> (place, options)."""
    key = _key(name)
    if key in _HOME_WORDS:
        return "home", None
    if key in _KNOWN:
        return "ok", _place(*_KNOWN[key])
    if key in _MANY_ZONES:
        return "many", f"{_MANY_ZONES[key]} has more than one time zone. Which city do you mean?"
    if lookup is None:
        import earth
        lookup = earth.resolve
    try:
        found, options = lookup(name)
    except Exception as e:   # a lookup bug must never become a wrong time
        print(f"World clock: looking up {name!r} failed: {e!r}", flush=True)
        found, options = None, None
    if options:
        both = [_from_geocoder(option) for option in options[:2]]
        if all(both):
            return "ambiguous", both
    place = _from_geocoder(found) if found else None
    if not place:
        if found:
            return "missing", f"I found {found['name']}, but not its time zone, so I won't guess the time there."
        return "missing", f"I couldn't find a place called {name}. Try the city's name, maybe with its country."
    return "ok", place


def _from_geocoder(found: dict):
    zone = (found or {}).get("timezone") or ""
    try:
        ZoneInfo(zone)
    except Exception:
        return None
    parts = [p.strip() for p in (found.get("name") or "").split(",") if p.strip()]
    country = found.get("country") or (parts[-1] if len(parts) > 1 else "")
    return _place(parts[0] if parts else zone.split("/")[-1].replace("_", " "), country if parts and country != parts[0] else "",
                  zone, found.get("lat"), found.get("lon"))


# ---------------------------------------------------------------- when
def local_time(place: dict, now: datetime, home=None) -> datetime:
    """`now` on that place's clock. A home place without a zone name uses the computer's own zone."""
    if place.get("tz"):
        return now.astimezone(ZoneInfo(place["tz"]))
    return now.astimezone(home) if home is not None else now.astimezone()


def say_time(moment: datetime) -> str:
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _gap(minutes: int) -> str:
    hours, rest = divmod(abs(minutes), 60)
    if rest == 30:
        return "half an hour" if hours == 0 else f"{hours} and a half hours"
    if rest:
        return f"{hours} hours {rest} minutes" if hours else f"{rest} minutes"
    return f"{hours} hour{'' if hours == 1 else 's'}"


def offset_minutes(a: datetime, b: datetime) -> int:
    """How far a's clock is ahead of b's at this moment, in minutes."""
    return round((a.utcoffset() - b.utcoffset()).total_seconds() / 60)


def is_daytime(place: dict, now: datetime):
    """True / False from the Sun's real position there; None when the place has no coordinates."""
    if place.get("lat") is None or place.get("lon") is None:
        return None
    return geo.sun_elevation(place["lat"], place["lon"], now) > -0.833


def describe(places: list, now: datetime = None, home=None, difference: bool = False, daylight: bool = False) -> str:
    """What Jarvis says about these places' time right now. home: the user's own tzinfo (the computer's by default)."""
    now = now or datetime.now(timezone.utc)
    here = now.astimezone(home) if home is not None else now.astimezone()
    times = [local_time(place, now, home) for place in places]
    named = lambda place: "here" if place.get("home") else place["name"]
    if difference and len(places) == 2:
        (a, b), (ta, tb) = places, times
        gap = offset_minutes(ta, tb)
        if gap == 0:
            lead = f"{named(a).capitalize() if a.get('home') else named(a)} and {named(b)} are on the same time"
        else:
            lead = f"{'You are' if a.get('home') else named(a) + ' is'} {_gap(gap)} {'ahead of' if gap > 0 else 'behind'} " \
                   f"{'you' if b.get('home') else named(b)}"
        text = f"{lead}: it's {say_time(ta)} {'here' if a.get('home') else 'in ' + named(a)} and {say_time(tb)} " \
               f"{'here' if b.get('home') else 'in ' + named(b)}."
    elif len(places) == 1:
        place, there = places[0], times[0]
        text = f"It's {say_time(there)} in {place['name']}"
        gap = offset_minutes(there, here)
        text += ", the same time as here." if gap == 0 else f", {_gap(gap)} {'ahead of' if gap > 0 else 'behind'} you."
        if there.date() != here.date():
            text += f" It's {'already' if there.date() > here.date() else 'still'} {there.strftime('%A')} there."
    else:
        said = [f"{say_time(t)} {'here' if p.get('home') else 'in ' + p['name']}" for p, t in zip(places, times)]
        text = "It's " + ", ".join(said[:-1]) + " and " + said[-1] + "."
        days = {t.date() for t in times} | {here.date()}
        if len(days) > 1:
            other = [f"{t.strftime('%A')} in {p['name']}" for p, t in zip(places, times) if t.date() != here.date() and not p.get("home")]
            if other:
                text += " It's " + " and ".join(other[:3]) + "."
    if daylight:
        lit = [(place, is_daytime(place, now)) for place in places if not place.get("home")]
        lit = [(place, day) for place, day in lit if day is not None]
        if len(lit) == 1:
            text += f" It's {'daytime' if lit[0][1] else 'night'} there."
        elif lit:
            text += " " + " ".join(f"It's {'daytime' if day else 'night'} in {place['name']}." for place, day in lit)
    return text


def window(places: list, mode: str = "set", focus: int = 0) -> dict:
    """What the clock window is sent: the places (it works out their time itself, from one clock, every second).
    mode: "set" replaces what it shows, "add" adds to it, "remove" takes these away."""
    return {"mode": mode, "focus": focus,
            "cities": [{"name": p["name"], "country": p.get("country", ""), "tz": p.get("tz", ""), "lat": p.get("lat"),
                        "lon": p.get("lon"), "home": bool(p.get("home"))} for p in places]}


def around_the_world() -> list:
    return [_place(*_KNOWN[name]) for name in AROUND_THE_WORLD]
