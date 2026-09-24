"""Facts about the Sun and the planets of the solar system, and understanding "tell me about Mars" / "show me Jupiter".

All the numbers here are well-known astronomical facts (no lookup needed), used two ways: spoken out loud, and sent to
the window (planet.js) alongside a texture name, so it can show a real, rotating 3D model next to the description.
"""
import re

# radius_km: equatorial radius. day_hours: length of one full spin (negative = spins backward, like Venus).
# year_days: time for one full orbit (in Earth days; None for the Sun itself). distance_million_km: average from the Sun.
BODIES = {
    "sun": {"name": "the Sun", "kind": "star", "texture": "2k_sun.jpg", "radius_km": 696000, "day_hours": 609.12,
            "year_days": None, "distance_million_km": 0, "moons": 0, "temp_c": "about 5,500°C on the surface",
            "color_kind": "star", "fact": "It holds 99.8% of all the mass in the solar system, and about 1.3 million Earths could fit inside it."},
    "mercury": {"name": "Mercury", "kind": "planet", "texture": "2k_mercury.jpg", "radius_km": 2440, "day_hours": 1407.6,
                "year_days": 88, "distance_million_km": 57.9, "moons": 0, "temp_c": "from -180°C at night to 430°C by day",
                "color_kind": "rock", "fact": "A year there is shorter than its own day: it orbits the Sun in 88 Earth days but spins only once every 59."},
    "venus": {"name": "Venus", "kind": "planet", "texture": "2k_venus_surface.jpg", "radius_km": 6052, "day_hours": -5832.5,
              "year_days": 225, "distance_million_km": 108.2, "moons": 0, "temp_c": "about 465°C, hot enough to melt lead",
              "color_kind": "rock", "fact": "It spins backward compared to most planets, and its day is longer than its year."},
    "earth": {"name": "Earth", "kind": "planet", "texture": "../earth/earth_atmos_2048.jpg", "radius_km": 6371, "day_hours": 24,
              "year_days": 365.25, "distance_million_km": 149.6, "moons": 1, "temp_c": "about 15°C on average",
              "color_kind": "earth", "fact": "It's the only known place with liquid water on its surface and life."},
    "mars": {"name": "Mars", "kind": "planet", "texture": "2k_mars.jpg", "radius_km": 3390, "day_hours": 24.66,
             "year_days": 687, "distance_million_km": 227.9, "moons": 2, "temp_c": "about -65°C on average",
             "color_kind": "rock", "fact": "It's home to Olympus Mons, the largest volcano in the solar system, about three times the height of Everest."},
    "jupiter": {"name": "Jupiter", "kind": "planet", "texture": "2k_jupiter.jpg", "radius_km": 69911, "day_hours": 9.93,
                "year_days": 4333, "distance_million_km": 778.5, "moons": 95, "temp_c": "about -110°C at the cloud tops",
                "color_kind": "gas", "fact": "Its Great Red Spot is a storm bigger than Earth that has been raging for at least 350 years."},
    "saturn": {"name": "Saturn", "kind": "planet", "texture": "2k_saturn.jpg", "radius_km": 58232, "day_hours": 10.7,
               "year_days": 10756, "distance_million_km": 1434, "moons": 146, "temp_c": "about -140°C at the cloud tops",
               "color_kind": "gas", "rings": True, "fact": "It's so much less dense than water that, if you found an ocean big enough, it would float."},
    "uranus": {"name": "Uranus", "kind": "planet", "texture": "2k_uranus.jpg", "radius_km": 25362, "day_hours": -17.24,
               "year_days": 30687, "distance_million_km": 2871, "moons": 28, "temp_c": "about -195°C at the cloud tops",
               "color_kind": "ice", "fact": "It spins almost completely on its side, likely tipped over by a massive collision long ago."},
    "neptune": {"name": "Neptune", "kind": "planet", "texture": "2k_neptune.jpg", "radius_km": 24622, "day_hours": 16.11,
                "year_days": 60190, "distance_million_km": 4495, "moons": 16, "temp_c": "about -200°C at the cloud tops",
                "color_kind": "ice", "fact": "It has the fastest winds in the solar system, clocked at over 2,000 km/h."},
    "pluto": {"name": "Pluto", "kind": "dwarf planet", "texture": None, "radius_km": 1188, "day_hours": 153.3,
              "year_days": 90560, "distance_million_km": 5906, "moons": 5, "temp_c": "about -225°C",
              "color_kind": "ice", "fact": "It was reclassified from a planet to a dwarf planet in 2006, and its year is 248 Earth years long."},
    "moon": {"name": "the Moon", "kind": "moon", "texture": "2k_moon.jpg", "radius_km": 1737, "day_hours": 655.7,
             "year_days": None, "distance_million_km": None, "moons": 0, "temp_c": "from -173°C at night to 127°C by day",
             "color_kind": "rock", "fact": "It's slowly drifting away from Earth, by about 3.8 centimeters every year."},
}
ALIASES = {"jarvis": None, "sol": "sun", "the sun": "sun", "planet earth": "earth", "our moon": "moon", "the moon": "moon", "luna": "moon"}
_NAMES = "|".join(sorted([*BODIES, "the sun", "the moon"], key=len, reverse=True))

_LEAD = r"(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
_VERB = r"(?:tell me about|show me|show|see|view|display|describe|what is|whats|what's|what do you know about|give me (?:info|information|facts) (?:on|about))"
_FILLER = r"(?:\s*(?:[-:,]|from (?:the )?solar system|in (?:the )?solar system|called|named))*\s*"
_PATTERNS = [
    re.compile(rf"^{_LEAD}{_VERB} (?:a |the )?(?:planet|moon|dwarf planet|star)?s?{_FILLER}(?P<name>{_NAMES})\b.*$"),
    re.compile(rf"^{_LEAD}(?P<name>{_NAMES}) facts\b.*$"),
]
_GENERIC = re.compile(r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you) )*tell me about (?:a |the )?planet\b\s*[:.,-]?\s*$")
_CLOSE = re.compile(r"\b(?:close|hide|dismiss)\b.{0,20}\b(?:planet|globe|model)\b")
_RESHOW = re.compile(
    r"\b(?:show|open|bring\s+up|pull\s+up|display|see|reopen|put\s+up|look\s+at|let\s+me\s+see|go\s+back\s+to)\b.*"
    r"\b(?:planet|model)\b.*\b(?:again|last|previous|earlier|before|back|once\s+more|one\s+more\s+time|next|first)\b"
    r"|\b(?:the\s+)?(?:previous|last|next|earlier|first)\s+planet\b|\bplanet\s+(?:again|from\s+before)\b")
_LEAD_WORDS = {"", "hey", "jervis", "jarvis", "ok", "okay", "please", "can", "could", "would", "you", "now", "then", "and",
               "just", "lets", "let", "i", "want", "need", "to", "wanna", "like", "me", "also", "so", "well", "show", "see", "the"}


def _is_command(prefix: str) -> bool:
    return all(w in _LEAD_WORDS for w in re.sub(r"[^a-z ]", " ", prefix).split())


def parse_request(text: str):
    """None if this isn't about a planet. Else {"action": "close"}, {"action": "reshow", "which": ...},
    {"action": "ask"} (no body named), or {"action": "show", "body": key}."""
    n = " ".join((text or "").lower().replace("’", "'").split())
    if not n:
        return None
    if _CLOSE.search(n):
        return {"action": "close"}
    if _RESHOW.search(n):
        m = re.search(r"\b(?:show|open|bring|pull|display|see|reopen|put|look|let|go|previous|last|next|earlier|first|planet|model)\b", n)
        if _is_command(n[:m.start()]):
            which = "first" if re.search(r"\bfirst\b", n) else "prev" if re.search(r"\b(?:previous|before|earlier|back)\b", n) else \
                "next" if re.search(r"\bnext\b", n) else "last"
            return {"action": "reshow", "which": which}
    for pattern in _PATTERNS:
        m = pattern.match(n)
        if m:
            key = ALIASES.get(m.group("name"), m.group("name"))
            if key and key in BODIES:
                return {"action": "show", "body": key}
    if _GENERIC.match(n):
        return {"action": "ask"}
    return None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _say_number(n: float) -> str:
    return f"{n:,.0f}" if n == int(n) else f"{n:,.2f}".rstrip("0").rstrip(".")


def _day_length(hours: float) -> str:
    spin = "backward, " if hours < 0 else ""
    h = abs(hours)
    return f"{spin}about {_say_number(h)} hours" if h < 72 else f"{spin}about {_say_number(h / 24)} Earth days"


def _year_length(days):
    if days is None:
        return None
    return f"about {_say_number(days)} days" if days < 900 else f"about {_say_number(days / 365.25)} Earth years"


def describe(body: dict) -> str:
    """A spoken-style lead sentence, then the key facts as a list for the screen (the same shape as graphs/earth)."""
    lead = f"{body['name']} is {'a' if body['kind'][0] not in 'aeiou' else 'an'} {body['kind']}"
    if body["distance_million_km"]:
        lead += f", about {_say_number(body['distance_million_km'])} million kilometers from the Sun"
    lead += ". " + body["fact"]
    lines = [f"- **Radius:** {_say_number(body['radius_km'])} km ({_say_number(body['radius_km'] / 6371)}× Earth's)"]
    if body["distance_million_km"]:
        lines.append(f"- **Distance from the Sun:** {_say_number(body['distance_million_km'])} million km")
    lines.append(f"- **Day length:** {_day_length(body['day_hours'])}")
    year = _year_length(body["year_days"])
    if year:
        lines.append(f"- **Year length:** {year}")
    lines.append(f"- **Moons:** {body['moons']}" if body["kind"] != "moon" else f"- **Orbits:** Earth")
    lines.append(f"- **Temperature:** {body['temp_c']}")
    if body.get("rings"):
        lines.append("- **Rings:** yes, a wide system of ice and rock")
    return lead + "\n\n" + "\n".join(lines)


def chips(body: dict) -> list:
    """The short label/value pairs shown under the model, the same shape as the graph and globe windows use."""
    out = [["Radius", f"{_say_number(body['radius_km'])} km"], ["Day length", _day_length(body["day_hours"])]]
    year = _year_length(body["year_days"])
    if year:
        out.append(["Year length", year])
    if body["distance_million_km"]:
        out.append(["Distance from Sun", f"{_say_number(body['distance_million_km'])} million km"])
    out.append(["Moons", str(body["moons"])] if body["kind"] != "moon" else ["Orbits", "Earth"])
    out.append(["Temperature", body["temp_c"]])
    if body.get("rings"):
        out.append(["Rings", "Yes"])
    return out


def build(key: str) -> dict:
    """Everything the window needs to draw the body, plus what Jervis says about it."""
    body = BODIES[key]
    return {"kind": "planet", "key": key, "name": body["name"], "bodyKind": body["kind"], "texture": body["texture"],
            "colorKind": body["color_kind"], "rings": bool(body.get("rings")), "radiusKm": body["radius_km"],
            "moons": body["moons"], "chips": chips(body), "text": describe(body)}
