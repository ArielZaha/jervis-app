"""Cinematic direction for Jervis's 3D scenes: what a request says about time, cameras, lights and motion, and where
the camera must be to frame what it should — measured on the scene's real geometry (spatial.py), never a preset.

  "a 10-second cinematic where the camera approaches the villa, the pool lights turn on halfway through, and the
   door opens near the end"
  -> parse_direction(): events with times in seconds   (duration 10 s; camera push-in 0-10 s; pool lights on at 5 s;
     the door opens at ~8 s)   -> frames with the scene's own fps
  -> plan_shot() / camera_path(): camera positions and aims that frame the subject, clear of every building and with a
     clear line of sight, eased into keyframes
  -> natural_motion(): which things move by themselves (water, fire, wind in trees, flags...)

Pure Python, no bpy: Jervis plans and verifies with it outside Blender, and the kit loads the very same code inside
Blender (agent_blender.kit_source), so what is planned and what is checked agree.

Space: metres, z up, the ground is z = 0, x left(-)/right(+), y front(-)/back(+). A "thing" is spatial.things()'s dict.
"""
import math
import re

try:
    spatial   # inside Blender: given to this module by the kit's loader
except NameError:
    import spatial

DEFAULT_SECONDS = 8.0
SENSOR = 36.0          # mm, Blender's default sensor width
ASPECT = 16 / 9

# ---------- numbers and time ----------

_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
            "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "a": 1, "an": 1, "half a": 0.5,
            "a couple of": 2, "a few": 3}
_NUM = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _NUMBERS), key=len, reverse=True)) + r")"
_SECONDS = r"(?:seconds?|secs?|s)\b"
_UNIT = r"(?P<unit>seconds?|secs?|s|minutes?|mins?|frames?)\b"


def number(text):
    t = str(text or "").strip().lower()
    if t in _NUMBERS:
        return float(_NUMBERS[t])
    try:
        return float(t)
    except ValueError:
        return None


def _to_seconds(value, unit, fps):
    unit = (unit or "s").lower()
    if unit.startswith("min"):
        return value * 60
    if unit.startswith("frame"):
        return value / float(fps or 24)
    return value


_DURATION = re.compile(r"(?<![\w.])(?P<n>" + _NUM + r")\s*(?:-|\s)?\s*" + _UNIT, re.I)
_EVENT_TIME = re.compile(r"\b(?:after|at|by|around|from|between|until|till|to|and|first|last|final|within|"
                         r"for the first|for the last|in|second)\s*$", re.I)
_VIDEO = re.compile(r"\b(?:cinematic|video|animation|animated|clip|shot|sequence|film|movie|timeline|scene|long|"
                    r"render|reel|trailer|flythrough|fly-through|loop)\b", re.I)


def parse_fps(text):
    m = re.search(r"\b(\d{2,3})\s*(?:fps|frames? (?:per|a) second)\b", str(text or ""), re.I)
    return int(m.group(1)) if m else None


def parse_duration(text, fps=None):
    """How long the whole thing should be, in seconds — "a 10-second cinematic", "make it 12 seconds long",
    "a 1 minute fly-through", "240 frames" — but never an event's time ("after 3 seconds"). None if not said."""
    text = str(text or "")
    best = None
    for m in _DURATION.finditer(text):
        before = text[:m.start()]
        if _EVENT_TIME.search(before.rstrip()):
            continue
        value = number(m.group("n"))
        if value is None or value <= 0:
            continue
        nearby = text[max(0, m.start() - 30):m.end() + 30]
        hyphen = "-" in text[m.start():m.end()]
        lasting = re.search(r"\b(?:over|lasting|across|taking|spanning)\s*$", before, re.I) or \
            re.match(r"\s*(?:long|in total|total)\b", text[m.end():], re.I)
        if hyphen or lasting or _VIDEO.search(nearby) or m.group("unit").lower().startswith(("min", "frame")):
            seconds = _to_seconds(value, m.group("unit"), fps)
            best = seconds if best is None else max(best, seconds)
    return best


_TIME_PATTERNS = [   # (pattern, function(match, D) -> (start, end)); seconds, end None = open
    (r"\bfrom\s+(?P<a>" + _NUM + r")\s*(?:" + _SECONDS + r")?\s*(?:to|until|till|-)\s*(?P<b>" + _NUM + r")\s*" + _SECONDS,
     lambda m, D: (number(m.group("a")), number(m.group("b")))),
    (r"\bbetween\s+(?P<a>" + _NUM + r")\s*(?:" + _SECONDS + r")?\s*and\s+(?P<b>" + _NUM + r")\s*" + _SECONDS,
     lambda m, D: (number(m.group("a")), number(m.group("b")))),
    (r"\b(?:in|during|for|over) the (?:first|opening)\s+(?P<a>" + _NUM + r")\s*" + _SECONDS,
     lambda m, D: (0.0, number(m.group("a")))),
    (r"\b(?:in|during|for|over) the (?:last|final|closing)\s+(?P<a>" + _NUM + r")\s*" + _SECONDS,
     lambda m, D: (max(0.0, D - number(m.group("a"))), D)),
    (r"\bat (?:frame|f)\s*(?P<f>\d+)", None),   # handled with fps
    (r"\b(?:after|at|by|around|from|starting at|beginning at)\s+(?P<a>" + _NUM + r")\s*" + _SECONDS,
     lambda m, D: (number(m.group("a")), None)),
    (r"\b(?:halfway|half way|half-way|midway|in the middle|mid-way)(?: through| point)?\b",
     lambda m, D: (0.5 * D, None)),
    (r"\b(?:two|2) thirds(?: of the way)?(?: through)?\b", lambda m, D: (2 * D / 3, None)),
    (r"\b(?:a|one) third of the way(?: through)?\b|\bafter a third\b", lambda m, D: (D / 3, None)),
    (r"\bthree quarters(?: of the way)?(?: through)?\b", lambda m, D: (0.75 * D, None)),
    (r"\b(?:a|one) quarter of the way(?: through)?\b", lambda m, D: (0.25 * D, None)),
    (r"\b(?:near|towards?|toward|close to|approaching) the end\b|\blate in\b", lambda m, D: (0.75 * D, None)),
    (r"\b(?:at the (?:very )?end|in the end|finally|last of all|to finish)\b", lambda m, D: (0.85 * D, None)),
    (r"\b(?:at the (?:very )?(?:start|beginning)|immediately|right away|at first|to begin with|first)\b",
     lambda m, D: (0.0, None)),
    (r"\b(?:throughout|the whole time|all along|the entire time|continuously|the whole (?:video|cinematic|shot))\b",
     lambda m, D: (0.0, D)),
]
_TIME_RES = [(re.compile(p, re.I), f) for p, f in _TIME_PATTERNS]
_FOR = re.compile(r"\bfor\s+(?P<a>" + _NUM + r")\s*" + _SECONDS, re.I)
_SLOW = re.compile(r"\b(?:slow(?:ly)?|gradual(?:ly)?|gently|gentle|lazily|leisurely|gracefully|softly)\b", re.I)
_FAST = re.compile(r"\b(?:quick(?:ly)?|fast|rapid(?:ly)?|sudden(?:ly)?|swift(?:ly)?|instantly|snap(?:s|py)?)\b", re.I)


def clause_time(clause, duration, fps=24):
    """(start, end, explicit) in seconds for one clause of a request; start/end None where it doesn't say."""
    for rx, fn in _TIME_RES:
        m = rx.search(clause)
        if not m:
            continue
        if fn is None:
            return int(m.group("f")) / float(fps or 24), None, True
        start, end = fn(m, duration)
        if start is None:
            continue
        lasting = _FOR.search(clause)
        if end is None and lasting:
            end = start + number(lasting.group("a"))
        return start, end, True
    lasting = _FOR.search(clause)
    if lasting:
        return None, number(lasting.group("a")), False   # a length with no start: placed in sequence
    return None, None, False


# ---------- easing ----------

def ease(t, kind="smooth"):
    """Eased progress 0..1 for t in 0..1: smooth (ease in-out), in, out, linear, back (overshoot), bounce."""
    t = max(0.0, min(1.0, float(t)))
    kind = (kind or "smooth").lower()
    if kind in ("linear", "constant speed", "steady"):
        return t
    if kind in ("in", "ease_in", "accelerate"):
        return t * t * t
    if kind in ("out", "ease_out", "decelerate"):
        return 1 - (1 - t) ** 3
    if kind == "back":
        c = 1.70158
        return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2
    if kind == "bounce":
        n, d = 7.5625, 2.75
        if t < 1 / d:
            return n * t * t
        if t < 2 / d:
            t -= 1.5 / d
            return n * t * t + 0.75
        if t < 2.5 / d:
            t -= 2.25 / d
            return n * t * t + 0.9375
        t -= 2.625 / d
        return n * t * t + 0.984375
    return t * t * (3 - 2 * t) if kind != "smoother" else t * t * t * (t * (6 * t - 15) + 10)


def ease_of(text, default="smooth"):
    """The easing a request implies: "smoothly"/"naturally" -> smooth, "suddenly" -> constant, "bounces" ->
    bounce, "at a steady speed" -> linear, "accelerates" -> in, "slows down" -> out."""
    t = str(text or "").lower()
    for pattern, kind in ((r"\bbounc", "bounce"), (r"\b(?:overshoot|springy|elastic)", "back"),
                          (r"\b(?:sudden(?:ly)?|instant(?:ly)?|snap(?:s|py)?|abrupt(?:ly)?|cut to)\b", "constant"),
                          (r"\b(?:steady|constant speed|linear(?:ly)?|uniform(?:ly)?|evenly)\b", "linear"),
                          (r"\b(?:accelerat\w*|speeds? up|picks? up speed)\b", "in"),
                          (r"\b(?:decelerat\w*|slows? (?:down|to a stop)|comes? to (?:a )?(?:stop|rest)|settles?)\b", "out")):
        if re.search(pattern, t):
            return kind
    return default


# ---------- what the request directs ----------

_THING_NOUNS = None


def _nouns(text):
    return [w for _, w in spatial._nouns(str(text or "")) if w not in spatial._PRONOUN]


_CAMERA_WORD = re.compile(r"\b(?:camera|cam|shot|shots|view|angle|framing|frames?|lens|cinematographer|footage)\b", re.I)
CAMERA_MOVES = [
    (r"\b(?:orbit\w*|circl\w*|goes? (?:all the way )?around|going around|revolv\w*|(?:spin|rotat|swing)\w* around|"
     r"360)\b", "orbit"),
    (r"\b(?:fl(?:y|ies|ying|ew)\s+(?:over|above|across)|flyover|fly-over|aerial (?:pass|sweep))\b", "flyover"),
    (r"\b(?:fl(?:y|ies|ying|ew)\s+(?:through|around|past|between)|fly-?through|walk-?through|tour\w*)\b",
     "fly_through"),
    (r"\b(?:push(?:es|ing)?[- ]in|dolly(?:ing)? in|dollies in|zoom(?:s|ing)? in|approach\w*|"
     r"(?:mov|glid|driv|creep|travel|drift|head)\w* (?:slowly )?(?:toward|towards|closer|in on|up to)|"
     r"closes? in|get(?:s|ting)? closer|comes? closer)\b", "push_in"),
    (r"\b(?:pull(?:s|ing)?[- ](?:out|back|away)|dolly(?:ing)? (?:out|back)|dollies (?:out|back)|zoom(?:s|ing)? out|"
     r"(?:mov|glid|drift|travel)\w* (?:away|back)|backs? away|retreat\w*)\b", "pull_out"),
    (r"\b(?:follow\w*|chas\w*|tail\w*)\b", "follow"),
    (r"\btrack(?:s|ing)?(?: shot)?\b", "track"),
    (r"\bpan(?:s|ning|ned)?\b", "pan"),
    (r"\btilt(?:s|ing|ed)?\b", "tilt"),
    (r"\b(?:crane\w*|boom\w* up|ris(?:es|ing)\b|ascend\w*|lifts? up|jib\w*)", "crane"),
    (r"\breveal\w*\b", "reveal"),
]
CAMERA_SHOTS = [
    (r"\b(?:overhead|top[- ]down|bird'?s[- ]eye|from above|straight down|aerial)\b", "overhead"),
    (r"\b(?:extreme )?close[- ]?ups?\b|\bclose shot\b|\bdetail shot\b", "close"),
    (r"\bmedium(?:[- ]wide)? shot\b|\bmid[- ]shot\b", "medium"),
    (r"\bestablishing\b", "establishing"),
    (r"\bwide(?:[- ]angle)? shot\b|\bwide view\b|\blong shot\b|\bfull shot\b", "wide"),
    (r"\blow[- ]angle\b|\bfrom below\b|\bworm'?s[- ]eye\b|\bheroic\b", "low"),
]
_CAMERA_MOVES = [(re.compile(p, re.I), m) for p, m in CAMERA_MOVES]
_CAMERA_SHOTS = [(re.compile(p, re.I), m) for p, m in CAMERA_SHOTS]

SKIES = [
    (r"\b(?:day(?:time)?|daylight) (?:to|into|turns? (?:to|into)|becom\w* ) ?night\b|\bfrom day to night\b|"
     r"\bnight ?falls?\b|\bnightfall\b|\b(?:it )?(?:gets?|grows?|turns?) dark\b|\bsun (?:goes|sets) down\b",
     "day_to_night"),
    (r"\bnight (?:to|into) (?:day|morning)\b|\bfrom night to day\b|\b(?:it )?gets? light\b", "night_to_day"),
    (r"\b(?:sunrise|dawn|daybreak|first light|sun (?:rises|comes up))\b", "sunrise"),
    (r"\b(?:sunset|dusk|golden hour|twilight|sun ?down)\b", "sunset"),
    (r"\b(?:night(?:time)?|moonlit|moonlight|at night|midnight)\b", "night"),
    (r"\b(?:noon|midday|daylight|daytime|sunny|bright day|clear day|in the day)\b", "day"),
    (r"\b(?:dramatic|moody|noir|high[- ]contrast|chiaroscuro)\b", "dramatic"),
    (r"\b(?:overcast|cloudy|grey day|gray day|stormy)\b", "overcast"),
]
_SKIES = [(re.compile(p, re.I), s) for p, s in SKIES]
_LIGHT_NOUN = r"(?:lights?|lamps?|lanterns?|bulbs?|lighting|spotlights?|street ?lights?|torch(?:es)?)"
_LIGHTS_ON = re.compile(r"\b" + _LIGHT_NOUN + r"\b[^,.;]*?\b(?:turn(?:s|ed|ing)? on|switch\w* on|come(?:s)? on|"
                        r"light(?:s)? up|fade(?:s)? (?:in|up)|glow\w*|illuminat\w*|brighten\w*|flicker\w* on|go(?:es)? on)\b|"
                        r"\b(?:turn(?:s|ing)?|switch(?:es|ing)?|light(?:s|ing)?) (?:on|up) (?:the |all the )?(?:[a-z]+ )?" +
                        _LIGHT_NOUN + r"\b", re.I)
_LIGHTS_OFF = re.compile(r"\b" + _LIGHT_NOUN + r"\b[^,.;]*?\b(?:turn(?:s|ed|ing)? off|switch\w* off|go(?:es)? (?:out|off)|"
                         r"fade(?:s)? (?:out|down)|dim\w*)\b|\b(?:turn(?:s|ing)?|switch(?:es|ing)?) off (?:the |all the )?"
                         r"(?:[a-z]+ )?" + _LIGHT_NOUN + r"\b", re.I)
_WEATHER = [(re.compile(r"\b(?:rain\w*|drizzl\w*|downpour|showers?)\b", re.I), "rain"),
            (re.compile(r"\b(?:snow\w*|blizzard)\b", re.I), "snow")]
_WIND = re.compile(r"\b(?:wind(?:y|s)?|breez\w*|gust\w*|storm\w*|gale|blow\w*)\b", re.I)
_STATIC = re.compile(r"\b(?:static|still|frozen|motionless|no animation|not animated|without (?:any )?animation|"
                     r"don'?t animate|unanimated|no motion|calm and still)\b", re.I)

ACTIONS = [   # (pattern, action) — what a thing in the scene does
    (r"\b(?:open(?:s|ed|ing)?|swing\w* open)\b", "open"),
    (r"\b(?:clos(?:e|es|ed|ing)|shut(?:s|ting)?|swing\w* shut)\b", "close"),
    (r"\b(?:driv(?:e|es|ing)|roll(?:s|ing)?|travel\w*|ride\w*|cruis\w*|walk(?:s|ing)?|run(?:s|ning)?|"
     r"mov(?:e|es|ing)|go(?:es|ing)?|sail(?:s|ing)?|fl(?:y|ies|ying)|head(?:s|ing)?|comes?|pull(?:s|ing)? (?:in|out))\b",
     "travel"),
    (r"\b(?:sway(?:s|ing)?|rustl\w*|bend(?:s|ing)? in the wind|blow(?:s|ing)? in the wind|wav(?:e|es|ing) in the wind|"
     r"flutter\w*)\b", "sway"),
    (r"\b(?:spin(?:s|ning)?|rotat(?:e|es|ing)|turn(?:s|ing)? (?:around|round)|revolv\w*|twirl\w*)\b", "spin"),
    (r"\b(?:bounc(?:e|es|ing))\b", "bounce"),
    (r"\b(?:ris(?:e|es|ing)|lift(?:s|ing)?(?: off| up)?|float(?:s|ing)? up|levitat\w*|go(?:es)? up)\b", "rise"),
    (r"\b(?:fall(?:s|ing)?|drop(?:s|ping)?|sink(?:s|ing)?|go(?:es)? down|descend\w*)\b", "fall"),
    (r"\b(?:grow(?:s|ing)?|expand\w*|scal(?:e|es|ing) up|get(?:s)? bigger|inflat\w*)\b", "grow"),
    (r"\b(?:shrink(?:s|ing)?|scal(?:e|es|ing) down|get(?:s)? smaller|deflat\w*)\b", "shrink"),
    (r"\b(?:appear(?:s|ing)?|fade(?:s)? in|materiali[sz]\w*|pop(?:s)? (?:in|up))\b", "appear"),
    (r"\b(?:disappear(?:s|ing)?|fade(?:s)? (?:out|away)|vanish\w*)\b", "disappear"),
    (r"\b(?:turn(?:s|ing)?|chang(?:e|es|ing)|fad(?:e|es|ing)|go(?:es)?) (?:to |into )?(?P<colour>red|green|blue|yellow|"
     r"orange|purple|pink|white|black|gr[ae]y|gold|silver|cyan|teal|brown)\b", "colour"),
]
_ACTIONS = [(re.compile(p, re.I), a) for p, a in ACTIONS]
_FROM_TO = re.compile(r"\bfrom\s+(?:the\s+)?(?P<a>[\w' -]+?)\s+(?:to|into|towards?|up to)\s+(?:the\s+)?(?P<b>[\w' -]+?)"
                      r"(?=$|[,.;]|\s+(?:and|while|then|at|after|near|in|over|during|for|before|when|as)\b)", re.I)
_TO = re.compile(r"\b(?:to|into|towards?|toward|up to|out of)\s+(?:the\s+)?(?P<b>[\w' -]+?)"
                 r"(?=$|[,.;]|\s+(?:and|while|then|at|after|near|in|over|during|for|before|when|as)\b)", re.I)
_SPLIT = re.compile(r"\s*(?:[,;]|\.(?:\s|$)|\bthen\b|\band then\b|\bafter that\b|\bwhile\b|\bwhere\b|\bwhereupon\b|"
                    r"\band\b(?=\s+(?:the|a|an|then|finally|after|at|near|its|it|all|some|two|three|lights?|"
                    r"camera|slowly|gradually|make|create|render|film|shoot|add|turn|switch|let|have|animate|"
                    r"light|give)\b))\s*", re.I)


def is_static(text):
    return bool(_STATIC.search(str(text or "")))


def clauses(text):
    return [c.strip() for c in _SPLIT.split(str(text or "")) if c and c.strip()]


def _subject_after(clause, start):
    """The thing a clause is about after position `start` ("approaches the villa" -> villa)."""
    found = _nouns(clause[start:])
    return found[0] if found else None


def _strip_quotes(word):
    return word.strip("'\"") if word else word


def parse_direction(text, fps=None):
    """What a request directs, as {"duration", "fps", "static", "events": [...], "understood", "clauses"}.
    Each event: {"kind": camera|shot|sky|lights|action|weather|wind, "move", "subject", "from", "to", "start", "end",
    "explicit", "ease", "loop", "params", "clause"} — times in seconds (None = to be scheduled)."""
    text = " ".join(str(text or "").split())
    fps = parse_fps(text) or fps
    duration = parse_duration(text, fps)
    D = duration or DEFAULT_SECONDS
    events, understood, parts = [], [], clauses(text)
    main = next(iter(_nouns(text)), None)
    for clause in parts:
        start, end, explicit = clause_time(clause, D, fps or 24)
        found = []
        speed = 1.5 if _SLOW.search(clause) else 0.6 if _FAST.search(clause) else 1.0
        base = {"start": start, "end": end, "explicit": explicit, "ease": ease_of(clause), "speed": speed,
                "loop": bool(re.search(r"\b(?:loop\w*|repeatedly|over and over|keeps? \w+ing|forever|"
                                       r"continuously|endlessly|all the time|non-?stop)\b", clause, re.I)),
                "clause": clause, "params": {}}
        camera_clause = bool(_CAMERA_WORD.search(clause))
        for rx, move in _CAMERA_MOVES:
            m = rx.search(clause)
            if m and (camera_clause or move in ("orbit", "flyover", "fly_through", "pan", "tilt", "crane", "reveal")
                      or (move in ("push_in", "pull_out") and re.search(r"\b(?:zoom|dolly|push(?:es|ing)?[- ]in|"
                                                                 r"pull(?:s|ing)?[- ](?:out|back))", clause, re.I))):
                subject = _subject_after(clause, m.end()) or _subject_after(clause, 0)
                shot = next((s for srx, s in _CAMERA_SHOTS if srx.search(clause)), None)
                sweep = re.search(r"(?P<n>" + _NUM + r")\s*degrees?", clause, re.I)
                params = {"shot": shot}
                if sweep:
                    params["sweep"] = number(sweep.group("n"))
                elif re.search(r"\b(?:full|whole|complete|all the way|360)\b", clause, re.I):
                    params["sweep"] = 360.0
                if move == "pan":
                    ft = _FROM_TO.search(clause)
                    if ft:
                        params["from"], params["to"] = _first(ft.group("a")), _first(ft.group("b"))
                    side = re.search(r"\b(left|right)\b", clause, re.I)
                    if side:
                        params["direction"] = side.group(1).lower()
                if move == "tilt":
                    params["direction"] = "down" if re.search(r"\bdown\b", clause, re.I) else "up"
                found.append(dict(base, kind="camera", move=move, subject=subject, params=params))
                break
        if not found:
            for rx, shot in _CAMERA_SHOTS:
                m = rx.search(clause)
                if m and (camera_clause or shot in ("establishing", "close", "overhead", "medium", "wide")):
                    subject = _subject_after(clause, m.end()) or _subject_after(clause, 0)
                    found.append(dict(base, kind="shot", move=shot, subject=subject))
                    break
        if not found and camera_clause and not _is_framing_only(clause, duration) and \
                re.search(r"\b(?:camera|shot|view)\b", clause, re.I) and \
                re.search(r"\b(?:add|create|place|put|set up|make|frame|show|point|aim|look\w*)\b", clause, re.I):
            found.append(dict(base, kind="shot", move="wide", subject=_subject_after(clause, 0)))
        on, off = _LIGHTS_ON.search(clause), _LIGHTS_OFF.search(clause)
        if on or off:
            m = on or off
            words = clause[:m.end()]
            subject = next((w for w in _nouns(words) if w not in ("light", "lamp", "lantern", "bulb")), None)
            inside = bool(re.search(r"\b(?:inside|interior|indoor|in the (?:house|villa|cabin|building|rooms?))\b",
                                    clause, re.I))
            found.append(dict(base, kind="lights", move="on" if on else "off", subject=subject,
                              params={"inside": inside}))
        for rx, sky in _SKIES:
            if rx.search(clause) and not (sky == "dramatic" and found and found[-1]["kind"] == "camera"):
                found.append(dict(base, kind="sky", move=sky, subject=None))
                break
        for rx, weather in _WEATHER:
            if rx.search(clause) and not re.search(r"\brainbow", clause, re.I):
                found.append(dict(base, kind="weather", move=weather, subject=None,
                                  params={"heavy": bool(re.search(r"\b(?:heavy|storm\w*|downpour|blizzard|pouring)\b",
                                                                  clause, re.I))}))
                break
        if not found or all(f["kind"] in ("sky", "weather") for f in found):
            for rx, action in _ACTIONS:
                m = rx.search(clause)
                if not m:
                    continue
                if action == "travel" and camera_clause:
                    continue
                before = _nouns(clause[:m.start()])
                subject = before[-1] if before else _subject_after(clause, m.end())
                params = {}
                if action == "colour":
                    params["colour"] = m.group("colour").lower()
                if action in ("open", "close"):
                    subject = subject if subject in spatial.DOOR_WORDS or subject in ("gate", "window", "lid") \
                        else next((w for w in _nouns(clause) if w in spatial.DOOR_WORDS or w in ("gate", "window")), subject)
                    # whose door: "the garage door", "the door of the shed", "the villa's door"
                    owners = [m_.group(1).lower() for rx_ in (
                        r"\b([a-z]+)(?:'s)?\s+(?:front\s+|back\s+|main\s+)?(?:door|doors|entrance)\b",
                        r"\b(?:door|doors|entrance) (?:of|to|on) (?:the |a )?([a-z]+)\b")
                        for m_ in re.finditer(rx_, clause, re.I)]
                    whose = next((w for w in owners if w in spatial.VOCAB and w not in spatial.DOOR_WORDS), None)
                    if whose:
                        params["of"] = whose
                if action == "travel":
                    ft = _FROM_TO.search(clause)
                    if ft:
                        params["from"], params["to"] = _first(ft.group("a")), _first(ft.group("b"))
                    else:
                        to = _TO.search(clause[m.end():])
                        if to:
                            params["to"] = _first(to.group("b"))
                    if subject in (params.get("from"), params.get("to")):
                        subject = before[-1] if before else None
                if action == "spin":
                    turns = re.search(r"(?P<n>" + _NUM + r")\s*(?:times|turns|revolutions|full turns)", clause, re.I)
                    deg = re.search(r"(?P<n>" + _NUM + r")\s*degrees?", clause, re.I)
                    params["degrees"] = (number(turns.group("n")) * 360 if turns else
                                         number(deg.group("n")) if deg else 360.0)
                    params["axis"] = "x" if re.search(r"\b(?:flip|somersault|forward)\b", clause, re.I) else "z"
                height = re.search(r"(?P<n>" + _NUM + r")\s*(?:m|metres?|meters?)\b", clause, re.I)
                if height:
                    params["distance"] = number(height.group("n"))
                if subject is None and action not in ("sway",):
                    continue
                found.append(dict(base, kind="action", move=action, subject=subject or main, params=params))
                break
        if _WIND.search(clause) and not any(f["move"] == "sway" for f in found):
            found.append(dict(base, kind="wind", move="sway", subject=None,
                              params={"strength": 2.0 if re.search(r"\b(?:storm\w*|gale|strong|heavy)\b", clause,
                                                                   re.I) else 1.0}))
        for f in found:
            f["subject"] = _strip_quotes(f.get("subject"))
            if f["subject"] is None and f["kind"] in ("camera", "shot", "action") and \
                    re.search(r"\b(?:it|its|them|this|that|him|her)\b", clause, re.I):
                f["subject"] = next((e["subject"] for e in reversed(events) if e.get("subject")), main)
        events += found
        understood.append(bool(found) or _is_framing_only(clause, duration))
    return {"duration": duration, "fps": fps, "static": is_static(text), "events": events,
            "understood": all(understood) if parts else False, "clauses": parts}


def _first(text):
    found = _nouns(text or "")
    return found[0] if found else (str(text or "").strip() or None)


def _is_framing_only(clause, duration):
    """Clauses that only frame the request ("create a 10-second cinematic", "render it at 30 fps")."""
    return bool(re.fullmatch(r"(?:(?:please|now|also|and)\s+)*(?:create|make|build|give me|do|render|produce|film|"
                             r"shoot|animate)?\s*(?:me\s+)?(?:a|an|the)?\s*(?:" + _NUM + r"[- ]?" + _UNIT +
                             r"\s*)?(?:long\s+)?(?:cinematic|video|animation|clip|sequence|shot|film|movie|scene)?"
                             r"(?:\s+(?:at|in)\s+\d+\s*fps)?(?:\s+(?:of|for|with)\s+(?:it|this|the scene))?",
                             clause.strip(), re.I))


_BUILD = re.compile(r"^(?:(?:please|now|also|then|and|first|jervis|hey|ok|okay|can you|could you)\b[\s,]*)*"
                    r"(?:create|build|make|add|generate|model|design|put|place|give me|i want|i'd like|set up|"
                    r"construct|plant|draw)\b\s+(?:me\s+|us\s+)?(?P<rest>.*)$", re.I)
_INDEFINITE = re.compile(r"^(?:a|an|some|two|three|four|five|six|several|another|a few|a pair of|\d+)\b", re.I)
BUILDABLE = {"river", "stream", "waterfall", "fire", "campfire", "bonfire", "flag", "cloud", "fountain", "pool",
             "pond", "lounger", "villa", "island", "ocean", "sea", "lake", "forest", "park", "garden", "scene",
             "landscape", "cabin", "car", "boat", "statue", "tower"}
_FRAMING = re.compile(r"(?:(?:a|an)\s+)?(?:" + _NUM + r"[- ]?" + r"(?:seconds?|secs?|minutes?)[- ]?(?:long\s+)?)?"
                      r"(?:cinematic|video|animation|clip|film|movie|sequence|fly-?through|reel)\s+"
                      r"(?:of|showing|featuring|about|with|around)\s+", re.I)


def is_build(clause):
    """Does this clause ask to build something new ("create a villa with a pool", "add two palm trees") — rather
    than direct what's there ("make the door open", "the camera approaches the villa")?"""
    clause = _FRAMING.sub("", str(clause or "").strip())
    m = _BUILD.match(clause)
    if not m or not _INDEFINITE.match(m.group("rest").strip()):
        return False
    words = spatial.words_of(m.group("rest"))
    return any(w in spatial.VOCAB or w in spatial.FOOTPRINTS or w in BUILDABLE for w in words)


_SKY_PHRASE = {"day": "daylight", "night": "a night sky", "sunset": "sunset light", "sunrise": "sunrise light",
               "dusk": "dusk light", "dramatic": "dramatic lighting", "overcast": "an overcast sky",
               "day_to_night": "day turning to night", "night_to_day": "night turning to day"}


_SKY_WORDS = re.compile(r"\s*,?\s*\b(?:at|by|during|in(?: the)?|under(?: a| the)?|on a)\s+(?:the\s+)?(?:night(?:time)?|"
                        r"dusk|dawn|sunset|sunrise|twilight|evening|morning|daytime|daylight|moonlight|golden hour|"
                        r"rain|snow|storm|a storm|a stormy day|a sunny day|a rainy day|a snowy day|the wind|"
                        r"(?:a )?(?:windy|breezy|blustery|gusty|stormy) (?:environment|setting|place|area|weather|"
                        r"day|afternoon|evening|morning|climate|conditions))\b",
                        re.I)


def split_stages(text):
    """[what to build, how to direct it] when a request does both ("create a villa with a pool and make a 10-second
    cinematic where the camera approaches it"); None when it is only one of them. Light and weather said inside a
    build clause ("a villa at night") become part of the directing."""
    build, direct = [], []
    for c in clauses(text):
        if is_build(c):
            build.append(c)
        elif build and not direct and not is_direction(c):
            build[-1] += " and " + c   # still describing what to build ("... and the ocean beside it")
        else:
            direct.append(c)
    events = parse_direction(", ".join(direct))["events"] if direct else []
    extra = []
    for c in build:
        for e in parse_direction(c)["events"]:
            if e["kind"] == "sky":
                extra.append(f"with {_SKY_PHRASE.get(e['move'], e['move'])}")
            elif e["kind"] == "weather":
                extra.append(f"make it {e['move']}")
            elif e["kind"] == "wind":
                extra.append("make it windy")
    if not build or not (events or extra):
        return None
    build_text = " and ".join(_SKY_WORDS.sub("", _FRAMING.sub("", c)).strip(" ,") for c in build)
    duration = parse_duration(text)
    direct_text = ", ".join(extra + direct)
    if duration and parse_duration(direct_text) is None:
        direct_text = f"a {duration:g}-second cinematic, " + direct_text
    return [build_text, direct_text]


DIRECTION_HINT = re.compile(r"\b(?:camera|cinematic|animat\w*|keyframe\w*|timeline|frames?|fps|seconds?|orbit\w*|"
                            r"pan(?:s|ning)?|tilt\w*|dolly|zoom\w*|fly-?through|flyover|close[- ]?up|establishing|"
                            r"shot|sunrise|sunset|dusk|dawn|night|daytime|day to night|lighting|lights?|lamps?|"
                            r"open(?:s|ing)?|clos(?:e|es|ing)|driv(?:e|es|ing)|sway\w*|spin\w*|rotat\w*|bounc\w*|"
                            r"rain\w*|snow\w*|wind\w*|fade\w*|appear\w*|disappear\w*)\b", re.I)


def is_direction(text):
    """Is this request (also) about motion, cameras, light or time? Cheap test before parsing."""
    return bool(DIRECTION_HINT.search(str(text or "")))


# ---------- scheduling ----------

_DEFAULT_LENGTH = {"open": 1.8, "close": 1.4, "lights": 0.8, "spin": 2.0, "bounce": 2.0, "rise": 2.0, "fall": 1.2,
                   "grow": 1.5, "shrink": 1.5, "appear": 1.2, "disappear": 1.2, "colour": 1.5, "travel": None,
                   "sway": None}


def schedule(direction, duration=None):
    """Give every event a start and an end in seconds within the whole: camera moves, skies, weather and wind span
    it (unless timed); actions follow one another; lights take a moment (longer when "gradually")."""
    D = duration or direction.get("duration")
    if not D:   # not said: long enough for what was timed, or the default when nothing was
        timed = [x for e in direction["events"] for x in (e.get("start"), e.get("end")) if x is not None]
        D = max(timed) if timed else DEFAULT_SECONDS
        if any(e.get("start") is not None and e.get("end") is None for e in direction["events"]):
            D = max(D + 2.0, DEFAULT_SECONDS)
    D = float(D)
    cursor = 0.0
    out = []
    for e in direction["events"]:
        e = dict(e)
        start, end = e.get("start"), e.get("end")
        if e["kind"] in ("camera", "sky", "weather", "wind") or (e["kind"] == "action" and e["move"] in ("sway",)):
            start = 0.0 if start is None else start
            end = D if end is None or end <= start else end
        elif e["kind"] == "shot":
            start = 0.0 if start is None else start
            end = D if end is None else end
        else:
            length = _DEFAULT_LENGTH.get(e["move"] if e["kind"] == "action" else "lights") or 0.0
            length *= e.get("speed", 1.0)
            if e["kind"] == "lights" and re.search(r"\b(?:gradual\w*|slow\w*|fade\w*|gently|softly)\b", e["clause"],
                                                   re.I):
                length = max(length, 2.5)
            if end is not None and start is None and not e.get("explicit"):   # "for 3 seconds" with no start
                length, end = end, None
            if start is None:
                start = cursor
            if end is None:
                end = (start + length) if length else D
            cursor = max(cursor, end)
        start = max(0.0, min(D, start))
        end = max(start + 0.2, min(D, end)) if end > start else min(D, start + 0.2)
        if end > D:
            start, end = max(0.0, D - (end - start)), D
        e["start"], e["end"] = round(start, 3), round(end, 3)
        out.append(e)
    return out, D


def to_frame(seconds, fps, frame_start=1):
    return int(round(frame_start + float(seconds) * float(fps)))


# ---------- cameras: framing on the real scene ----------

LENS = {"establishing": 24, "wide": 28, "medium": 40, "close": 65, "overhead": 30, "low": 30, "follow": 35,
        "track": 35, "orbit": 30, "flyover": 24, "fly_through": 24}
FILL = {"establishing": 0.42, "wide": 0.62, "medium": 0.78, "close": 0.85, "overhead": 0.7, "low": 0.62}
ELEVATION = {"establishing": 22, "wide": 14, "medium": 9, "close": 5, "overhead": 87, "low": 4}


def fov(lens, sensor=SENSOR, aspect=ASPECT):
    """(horizontal, vertical) field of view in radians for a focal length in mm."""
    h = 2 * math.atan(sensor / 2 / float(lens))
    v = 2 * math.atan(sensor / aspect / 2 / float(lens))
    return h, v


def subject_box(t):
    """(lo, hi) 3D box of a thing worth framing: a building with its roof but not its long path, a sunken pool with
    its water but not its underground basin."""
    lo, hi = list(t["lo"]), list(t["hi"])
    r = t["outer"] if t.get("outer") else (lo[0], lo[1], hi[0], hi[1])
    lo[0], lo[1], hi[0], hi[1] = r[0], r[1], r[2], r[3]
    if t.get("category") in ("sunken", "ground", "path", "surface"):
        lo[2] = max(lo[2], -0.3)
        hi[2] = max(hi[2], lo[2] + 0.5)
    return lo, hi


def _union(boxes):
    return ([min(b[0][i] for b in boxes) for i in range(3)], [max(b[1][i] for b in boxes) for i in range(3)])


def _center(lo, hi):
    return [(lo[i] + hi[i]) / 2 for i in range(3)]


def _radius(lo, hi, shot="wide"):
    dx, dy, dz = (hi[0] - lo[0]), (hi[1] - lo[1]), (hi[2] - lo[2])
    if shot == "overhead":
        return max(dx, dy / ASPECT) / 2 * 1.05
    return max(0.3, 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz))


def distance_for(lo, hi, shot="wide", lens=None, elevation=None):
    """How far the camera stands for the subject to fill the frame as the shot type wants: its apparent width (a
    three-quarter view sees across its diagonal) against the horizontal field of view, its apparent height (its
    height, plus its depth seen from above) against the vertical one — whichever needs more room."""
    lens = lens or LENS.get(shot, 30)
    h, v = fov(lens)
    fill = FILL.get(shot, 0.62)
    dx, dy, dz = (hi[0] - lo[0]), (hi[1] - lo[1]), (hi[2] - lo[2])
    if shot == "overhead":
        return max(dx / 2 / (fill * math.tan(h / 2)), dy / 2 / (fill * math.tan(v / 2))) + dz
    el = math.radians(ELEVATION.get(shot, 14) if elevation is None else elevation)
    width = 0.85 * math.hypot(dx, dy)
    height = dz * math.cos(el) + 0.85 * max(dx, dy) * math.sin(el)
    depth = 0.5 * min(dx, dy)
    return max(0.6, max(width / 2 / (fill * math.tan(h / 2)), height / 2 / (fill * math.tan(v / 2))) + depth)


SIGHT_PAD = 0.35   # metres a line of sight keeps clear of what it passes over (no grazing a roof's parapet)


def _seg_hits_box(p, q, lo, hi, pad=0.0):
    """Does the segment p->q pass through the box (grown by `pad`)?"""
    lo, hi = [v - pad for v in lo], [v + pad for v in hi]
    t0, t1 = 0.0, 1.0
    for i in range(3):
        d = q[i] - p[i]
        if abs(d) < 1e-9:
            if p[i] < lo[i] or p[i] > hi[i]:
                return False
            continue
        a, b = (lo[i] - p[i]) / d, (hi[i] - p[i]) / d
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return True


def _inside_box(p, lo, hi, pad=0.0):
    return all(lo[i] - pad <= p[i] <= hi[i] + pad for i in range(3))


def obstacles_3d(ts, exclude=()):
    """The 3D boxes a camera must stay out of and see past: every thing but ground, sky and what's being filmed."""
    out = []
    for t in ts:
        if t["name"] in exclude or t["category"] in ("ground", "sky", "surface", "path", "backdrop"):
            continue
        lo, hi = list(t["lo"]), list(t["hi"])
        for r in spatial.footprints(t):
            out.append((t["name"], [r[0], r[1], max(lo[2], -0.5)], [r[2], r[3], hi[2]]))
    return out


def clear_view(cam, aim, boxes, subject_points=()):
    """(camera free, how many of the subject's points it can see) among the obstacle boxes."""
    if any(_inside_box(cam, lo, hi, 0.4) for _, lo, hi in boxes):
        return False, 0
    pts = list(subject_points) or [aim]
    seen = sum(1 for p in pts if not any(_seg_hits_box(cam, p, lo, hi, SIGHT_PAD) for _, lo, hi in boxes))
    return True, seen


def _dir(az_deg, el_deg):
    a, e = math.radians(az_deg), math.radians(el_deg)
    return (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))


def base_azimuth(t):
    """The direction (degrees) the camera looks at a thing FROM: in front of a building, a little to one side (a
    three-quarter view); the scene's front (-y) for anything else."""
    fx, fy = (t or {}).get("front") or (0.0, -1.0)
    return math.degrees(math.atan2(fy, fx)) + 32.0


def _ground_z(x, y, ts):
    z = 0.0
    for t in ts:
        if t["category"] == "ground" and t["outer"][0] <= x <= t["outer"][2] and t["outer"][1] <= y <= t["outer"][3]:
            z = max(z, min(t["hi"][2], 3.0)) if t.get("asset_type") == "island" else z
    return z


def plan_shot(ts, subject, shot="wide", lens=None, azimuth=None, elevation=None, distance=None, exclude=()):
    """A camera position for one shot of `subject` (a thing, a list of things, or None for the whole scene):
    {"location", "aim", "lens", "azimuth", "elevation", "distance", "clear", "seen"} — framed as the shot type wants,
    outside every building and with a clear line of sight (other angles are tried, nearest first)."""
    things_ = [t for t in ([subject] if isinstance(subject, dict) else (subject or []))]
    if not things_:
        things_ = [t for t in ts if t["category"] not in ("ground", "sky", "backdrop")] or ts
    if not things_:
        return {"location": (8.0, -12.0, 5.0), "aim": (0.0, 0.0, 1.0), "lens": lens or 30, "azimuth": -56,
                "elevation": 18, "distance": 15, "clear": True, "seen": 1}
    lo, hi = _union([subject_box(t) for t in things_])
    c = _center(lo, hi)
    if shot == "close":
        c[2] = lo[2] + (hi[2] - lo[2]) * 0.45
    lens = lens or LENS.get(shot, 30)
    d0 = distance or distance_for(lo, hi, shot, lens)
    az0 = base_azimuth(things_[0] if len(things_) == 1 else None) if azimuth is None else azimuth
    el0 = ELEVATION.get(shot, 14) if elevation is None else elevation
    names = {t["name"] for t in things_} | set(exclude)
    boxes = obstacles_3d(ts, exclude=names)
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2] + 0.2, hi[2])] + [tuple(c)]
    best = None
    for d_az in [0, 15, -15, 30, -30, 50, -50, 75, -75, 100, -100, 130, -130, 160, -160, 180]:
        for d_el in (0, 8, 18, 30):
            for k in (1.0, 0.85, 1.25, 0.7, 1.6):
                el = min(88, el0 + d_el)
                d = d0 * k
                v = _dir(az0 + d_az, el)
                cam = (c[0] + v[0] * d, c[1] + v[1] * d, max(_ground_z(c[0] + v[0] * d, c[1] + v[1] * d, ts) + 0.6,
                                                             c[2] + v[2] * d))
                free, seen = clear_view(cam, c, boxes, corners)
                if not free:
                    continue
                score = abs(d_az) / 25 + d_el / 12 + abs(math.log(k)) * 3 + (len(corners) - seen) * 1.5
                if best is None or score < best[0]:
                    best = (score, {"location": tuple(round(x, 3) for x in cam), "aim": tuple(round(x, 3) for x in c),
                                    "lens": lens, "azimuth": round(az0 + d_az, 2), "elevation": el,
                                    "distance": round(d, 3), "clear": True, "seen": seen / len(corners)})
                if best and best[0] < 0.5:
                    break
            if best and best[0] < 0.5:
                break
        if best and best[0] < 0.5:
            break
    if best is None:   # nowhere clear at ground level: from high above
        v = _dir(az0, 70)
        cam = (c[0] + v[0] * d0, c[1] + v[1] * d0, c[2] + v[2] * d0 + max(0.0, hi[2]))
        return {"location": tuple(round(x, 3) for x in cam), "aim": tuple(round(x, 3) for x in c), "lens": lens,
                "azimuth": az0, "elevation": 70, "distance": d0, "clear": False, "seen": 0}
    return best[1]


def _shot_at(ts, things_, c, az, el, d, boxes, lens):
    """A camera position at azimuth/elevation/distance from c; lifted (a crane over it) while it would be inside
    something or something stands between it and the subject."""
    v = _dir(az, el)
    cam = [c[0] + v[0] * d, c[1] + v[1] * d, c[2] + v[2] * d]
    cam[2] = max(cam[2], _ground_z(cam[0], cam[1], ts) + 0.6)
    for _ in range(40):
        inside = any(_inside_box(cam, lo, hi, 0.4) for _, lo, hi in boxes)
        blocked = any(_seg_hits_box(cam, c, lo, hi, SIGHT_PAD) for _, lo, hi in boxes)
        if not inside and not blocked:
            break
        cam[2] += 0.75
    return tuple(round(x, 3) for x in cam)


def clear_position(cam, aim, boxes, step=0.75, tries=40, see_past=()):
    """The camera position lifted (a crane up) until it is outside every box and sees `aim` past them — past all
    but `see_past` (the names of what it is looking AT: a point inside a building is seen by seeing the building)."""
    cam = list(cam)
    sight = [b for b in boxes if b[0] not in set(see_past)]
    for _ in range(tries):
        if not any(_inside_box(cam, lo, hi, 0.4) for _, lo, hi in boxes) and \
                not any(_seg_hits_box(cam, aim, lo, hi, SIGHT_PAD) for _, lo, hi in sight):
            break
        cam[2] += step
    return tuple(round(x, 3) for x in cam)


def camera_path(ts, subject, move="push_in", shot_from=None, shot_to=None, sweep=None, direction=None,
                subject_to=None, motion=None, lens=None):
    """Camera keys for a move: [(progress 0..1, camera location, aim point, lens)] — a push-in, pull-out, orbit,
    crane, reveal, pan, tilt, overhead drift, fly-over/through, or a follow/track of a moving subject (`motion`:
    [(progress, (x, y, z), heading (dx, dy))] sampled from the scene). Every key is clear of the scene's things."""
    things_ = [t for t in ([subject] if isinstance(subject, dict) else (subject or []))]
    if not things_:
        things_ = [t for t in ts if t["category"] not in ("ground", "sky")] or ts
    names = {t["name"] for t in things_}
    boxes = obstacles_3d(ts, exclude=names)
    lo, hi = _union([subject_box(t) for t in things_]) if things_ else ([-5, -5, 0], [5, 5, 3])
    c = _center(lo, hi)
    keys = []
    if move in ("push_in", "pull_out"):
        far_shot = shot_from or ("establishing" if move == "push_in" else "medium")
        near_shot = shot_to or ("medium" if move == "push_in" else "establishing")
        if move == "pull_out":
            far_shot, near_shot = (shot_to or "establishing"), (shot_from or "medium")
        first = plan_shot(ts, things_, far_shot)
        az, el = first["azimuth"], first["elevation"]
        lens_far, lens_near = LENS.get(far_shot, 28), LENS.get(near_shot, 40)
        d_far = first["distance"]
        lo_n, hi_n = lo, hi
        d_near = max(_radius(lo_n, hi_n) * 1.15, distance_for(lo_n, hi_n, near_shot, lens_near))
        for k in range(6):   # a straight dolly, checked along its whole length
            p = k / 5
            d = d_far + (d_near - d_far) * p
            e = el + (ELEVATION.get(near_shot, 9) - el) * p * 0.6
            cam = _shot_at(ts, things_, c, az, e, d, boxes, lens_far)
            keys.append((p, cam, tuple(c), round(lens_far + (lens_near - lens_far) * p * 0.35, 2)))
        keys = [keys[0], keys[2], keys[3], keys[-1]]
        if move == "pull_out":
            keys = [(1 - p, cam, aim, ln) for p, cam, aim, ln in reversed(keys)]
    elif move == "orbit":
        first = plan_shot(ts, things_, shot_from or "wide", lens=lens or LENS["orbit"])
        sweep = float(sweep if sweep is not None else 120.0)
        n = max(3, int(abs(sweep) / 30) + 1)
        sign = -1 if direction == "right" else 1
        for k in range(n):
            p = k / (n - 1)
            az = first["azimuth"] + sign * sweep * p
            d = first["distance"]
            cam = _shot_at(ts, things_, c, az, first["elevation"], d, boxes, first["lens"])
            keys.append((p, cam, tuple(c), first["lens"]))
    elif move == "crane":
        first = plan_shot(ts, things_, "wide")
        for k, el in enumerate((2, 12, 24, 36)):
            keys.append((k / 3, _shot_at(ts, things_, c, first["azimuth"], el, first["distance"] * (0.85 + k * 0.08),
                                         boxes, first["lens"]), tuple(c), first["lens"]))
    elif move == "reveal":
        end = plan_shot(ts, things_, shot_to or "establishing")
        low = _shot_at(ts, things_, c, end["azimuth"], 2.0, end["distance"] * 0.7, boxes, end["lens"])
        ground_aim = (low[0] + (c[0] - low[0]) * 0.25, low[1] + (c[1] - low[1]) * 0.25, 0.0)
        mid = _shot_at(ts, things_, c, end["azimuth"], end["elevation"] * 0.5, end["distance"] * 0.85, boxes,
                       end["lens"])
        keys = [(0.0, low, ground_aim, end["lens"]), (0.55, mid, tuple(c), end["lens"]),
                (1.0, end["location"], end["aim"], end["lens"])]
    elif move in ("pan", "tilt"):
        shot = plan_shot(ts, things_ + ([subject_to] if isinstance(subject_to, dict) else []), "wide")
        cam = shot["location"]
        if move == "pan":
            if isinstance(subject_to, dict):
                a = _center(*subject_box(things_[0]))
                b = _center(*subject_box(subject_to))
            else:
                v = _dir(shot["azimuth"], 0)
                side = (-v[1], v[0], 0.0)
                half = _radius(lo, hi) * 0.8 * (1 if direction != "left" else -1)
                a = [c[0] - side[0] * half, c[1] - side[1] * half, c[2]]
                b = [c[0] + side[0] * half, c[1] + side[1] * half, c[2]]
        else:
            a, b = [c[0], c[1], lo[2] + 0.3], [c[0], c[1], hi[2]]
            if direction == "down":
                a, b = b, a
        keys = [(0.0, cam, tuple(round(x, 3) for x in a), shot["lens"]),
                (1.0, cam, tuple(round(x, 3) for x in b), shot["lens"])]
    elif move == "overhead":
        shot = plan_shot(ts, things_, "overhead")
        loc = shot["location"]
        keys = [(0.0, loc, shot["aim"], shot["lens"]),
                (1.0, (loc[0], loc[1], loc[2] * 0.85 + c[2] * 0.15), shot["aim"], shot["lens"])]
    elif move in ("flyover", "fly_through"):
        order = sorted(things_, key=lambda t: (_center(*subject_box(t))[0], _center(*subject_box(t))[1]))
        if len(order) == 1:   # one thing: sweep past it at a height that clears everything in the way
            first = plan_shot(ts, order, "establishing")
            az = first["azimuth"]
            for k, d_az in enumerate((-60, -20, 20, 60)):
                el = 30 if move == "flyover" else 10
                keys.append((k / 3, _shot_at(ts, order, c, az + d_az, el, first["distance"] * 0.9, boxes,
                                             first["lens"]), tuple(c), first["lens"]))
        else:
            top = max([hi[2]] + [b[2][2] for b in boxes]) + 4.0
            for k, t in enumerate(order):
                tlo, thi = subject_box(t)
                tc = _center(tlo, thi)
                shot = plan_shot(ts, [t], "wide")
                cam = list(shot["location"])
                if move == "flyover":
                    cam[2] = max(cam[2], top)
                keys.append((k / (len(order) - 1), tuple(round(x, 3) for x in cam), tuple(tc), LENS[move]))
    elif move in ("follow", "track") and motion:
        dist, height = (max(6.0, _radius(lo, hi) * 3.5), max(2.0, (hi[2] - lo[2]) * 1.2)) \
            if move == "follow" else (max(7.0, _radius(lo, hi) * 4), 1.6)
        previous, seen = None, []
        for p, pos, heading in motion:
            hx, hy = heading
            n = math.hypot(hx, hy) or 1.0
            hx, hy = hx / n, hy / n
            body = (pos[0], pos[1], pos[2] + 0.8)   # what must stay in sight: the subject itself
            if move == "follow":   # behind it, looking a little ahead of it
                back = (-hx, -hy)
                aim = (pos[0] + hx * 3, pos[1] + hy * 3, pos[2] + 0.8)
            else:   # a tracking shot alongside it
                back = (-hy, hx)
                aim = body
            cam = _clear_around(pos, body, back, dist, height, boxes, previous)
            previous = cam
            seen.append(body)
            keys.append((p, cam, tuple(round(x, 3) for x in aim), LENS[move]))
        keys = _smooth_keys(keys)
        # smoothing cuts corners: a key it pulled into a wall, or behind one, is craned clear again
        keys = [(p, clear_position(cam, body, boxes), aim, ln) for (p, cam, aim, ln), body in zip(keys, seen)]
    else:   # a still shot
        shot = plan_shot(ts, things_, shot_from or move if move in FILL else "wide")
        keys = [(0.0, shot["location"], shot["aim"], shot["lens"])]
    return keys


def _clear_around(pos, aim, back, dist, height, boxes, previous=None):
    """A camera `dist` behind `pos` (direction `back`) at `height` — or, where a building stands in the way or the
    camera would be inside one, swung round the subject to the nearest clear angle (near the last key, so the camera
    doesn't jump); craned up only when no angle is clear."""
    best = None
    for k, d_az in enumerate((0, 25, -25, 50, -50, 80, -80, 120, -120, 180)):
        a = math.radians(d_az)
        bx, by = back[0] * math.cos(a) - back[1] * math.sin(a), back[0] * math.sin(a) + back[1] * math.cos(a)
        cam = (pos[0] + bx * dist, pos[1] + by * dist, pos[2] + height)
        if any(_inside_box(cam, lo, hi, 0.4) for _, lo, hi in boxes) or \
                any(_seg_hits_box(cam, aim, lo, hi, SIGHT_PAD) for _, lo, hi in boxes):
            continue
        score = abs(d_az) / 30 + (math.dist(cam, previous) / max(1.0, dist) * 2 if previous else 0.0)
        if best is None or score < best[0]:
            best = (score, cam)
    if best is None:
        return clear_position((pos[0] + back[0] * dist, pos[1] + back[1] * dist, pos[2] + height), aim, boxes)
    return tuple(round(x, 3) for x in best[1])


def _smooth_keys(keys, passes=2):
    """A moving subject's samples, smoothed so the camera glides instead of jittering."""
    for _ in range(passes):
        if len(keys) < 3:
            return keys
        out = [keys[0]]
        for a, b, c in zip(keys, keys[1:], keys[2:]):
            cam = tuple(round((a[1][i] + 2 * b[1][i] + c[1][i]) / 4, 3) for i in range(3))
            aim = tuple(round((a[2][i] + 2 * b[2][i] + c[2][i]) / 4, 3) for i in range(3))
            out.append((b[0], cam, aim, b[3]))
        out.append(keys[-1])
        keys = out
    return keys


def project(point, cam, aim, lens, aspect=ASPECT, sensor=SENSOR):
    """Where a point lands in the camera's frame: (x, y in -1..1 when in frame, depth > 0 when in front)."""
    f = [aim[i] - cam[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in f)) or 1.0
    f = [v / n for v in f]
    up = (0.0, 0.0, 1.0)
    r = [f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2], f[0] * up[1] - f[1] * up[0]]
    rn = math.sqrt(sum(v * v for v in r)) or 1.0
    if rn < 1e-6:   # looking straight down
        r, rn = [1.0, 0.0, 0.0], 1.0
    r = [v / rn for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    v = [point[i] - cam[i] for i in range(3)]
    depth = sum(v[i] * f[i] for i in range(3))
    if depth <= 1e-6:
        return 0.0, 0.0, depth
    h, vv = fov(lens, sensor, aspect)
    x = sum(v[i] * r[i] for i in range(3)) / depth / math.tan(h / 2)
    y = sum(v[i] * u[i] for i in range(3)) / depth / math.tan(vv / 2)
    return x, y, depth


def framing(cam, aim, lens, lo, hi):
    """How a box sits in the frame: {"visible": share of its corners in frame (0..1), "center": its centre's (x,
    y), "size": how much of the frame's height/width it fills}."""
    pts = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    proj = [project(p, cam, aim, lens) for p in pts]
    inside = [p for p in proj if p[2] > 0 and abs(p[0]) <= 1.02 and abs(p[1]) <= 1.02]
    cx, cy, cz = project(_center(lo, hi), cam, aim, lens)
    front = [p for p in proj if p[2] > 0]
    size = 0.0
    if front:
        size = max(max(p[0] for p in front) - min(p[0] for p in front),
                   max(p[1] for p in front) - min(p[1] for p in front)) / 2
    return {"visible": len(inside) / len(pts), "center": (round(cx, 3), round(cy, 3)), "in_front": cz > 0,
            "size": round(size, 3)}


# ---------- light ----------

def kelvin(k):
    """RGB (0..1) of a colour temperature in kelvin (Tanner Helland's fit)."""
    t = max(1000.0, min(40000.0, float(k))) / 100
    r = 255.0 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return tuple(round(max(0.0, min(255.0, v)) / 255, 4) for v in (r, g, b))


SKY = {   # time of day: sun elevation / azimuth (degrees; east = +x), colour temperature, sun strength, sky colour
    "sunrise": dict(elevation=4, azimuth=10, kelvin=2600, strength=2.2, sky=(0.75, 0.5, 0.42), sky_strength=0.55),
    "morning": dict(elevation=22, azimuth=70, kelvin=4600, strength=3.2, sky=(0.5, 0.64, 0.86), sky_strength=0.85),
    "afternoon": dict(elevation=38, azimuth=225, kelvin=5300, strength=3.7, sky=(0.44, 0.6, 0.86), sky_strength=0.95),
    "golden hour": dict(elevation=11, azimuth=235, kelvin=3100, strength=2.8, sky=(0.78, 0.62, 0.46),
                        sky_strength=0.7),
    "day": dict(elevation=58, azimuth=140, kelvin=5800, strength=4.0, sky=(0.42, 0.6, 0.88), sky_strength=1.0),
    "sunset": dict(elevation=5, azimuth=200, kelvin=2400, strength=2.0, sky=(0.86, 0.48, 0.3), sky_strength=0.55),
    "dusk": dict(elevation=-3, azimuth=205, kelvin=7000, strength=0.25, sky=(0.12, 0.13, 0.28), sky_strength=0.25),
    "night": dict(elevation=35, azimuth=300, kelvin=8500, strength=0.12, sky=(0.01, 0.015, 0.04), sky_strength=0.05),
    "dramatic": dict(elevation=14, azimuth=230, kelvin=3800, strength=3.2, sky=(0.06, 0.07, 0.1), sky_strength=0.15),
    "overcast": dict(elevation=50, azimuth=150, kelvin=6800, strength=1.2, sky=(0.55, 0.58, 0.62), sky_strength=0.9),
}
TRANSITIONS = {"day_to_night": ["day", "sunset", "dusk", "night"], "night_to_day": ["night", "sunrise", "day"],
               "sunset": ["day", "sunset"], "sunrise": ["night", "sunrise"]}


def sky_keys(look, duration_hint=None, transition=False):
    """[(progress, sky setting)] for a look ("day", "sunset", "night", "dramatic"...) or a change of it over time
    ("day_to_night", "night_to_day", or "sunset"/"sunrise" when it should happen during the shot)."""
    if transition and look in TRANSITIONS:
        stages = TRANSITIONS[look]
    elif look in TRANSITIONS and look not in SKY:
        stages = TRANSITIONS[look]
    else:
        stages = [look if look in SKY else "day"]
    n = len(stages)
    return [(k / (n - 1) if n > 1 else 0.0, dict(SKY[s], name=s, color=kelvin(SKY[s]["kelvin"])))
            for k, s in enumerate(stages)]


def light_spots_inside(t, spacing=4.0):
    """Where ceiling lights go in a building: a grid over its floor, clear of the walls, a little under the ceiling
    of the ground floor (and of the floor above, when it has one)."""
    core = spatial.grow(t["core"], -0.8)
    if core[2] - core[0] < 0.4 or core[3] - core[1] < 0.4:
        core = spatial.grow(t["core"], -0.3)
    floor = spatial.floor_level(t)
    top = t["hi"][2]
    nx = max(1, int(round((core[2] - core[0]) / spacing)))
    ny = max(1, int(round((core[3] - core[1]) / spacing)))
    levels = [floor + 2.35]
    if top - floor > 6.5:
        levels.append(floor + 2.9 + 2.35)
    pts = []
    for z in levels:
        for i in range(nx):
            for j in range(ny):
                pts.append((round(core[0] + (i + 0.5) * (core[2] - core[0]) / nx, 3),
                            round(core[1] + (j + 0.5) * (core[3] - core[1]) / ny, 3), round(z, 3)))
    return pts


def pool_light_spots(water_lo, water_hi, spacing=3.5):
    """Lights set into a pool's walls, under the water, looking across it: [((x, y, z), (dx, dy) facing)]."""
    x0, y0, z0 = water_lo
    x1, y1, z1 = water_hi
    z = max(z0 + 0.3, z1 - 0.45)
    out = []
    long_x = (x1 - x0) >= (y1 - y0)
    if long_x:
        n = max(1, int((x1 - x0) / spacing))
        for k in range(n):
            x = x0 + (k + 0.5) * (x1 - x0) / n
            out += [((round(x, 3), round(y0 + 0.02, 3), z), (0.0, 1.0)), ((round(x, 3), round(y1 - 0.02, 3), z), (0.0, -1.0))]
    else:
        n = max(1, int((y1 - y0) / spacing))
        for k in range(n):
            y = y0 + (k + 0.5) * (y1 - y0) / n
            out += [((round(x0 + 0.02, 3), round(y, 3), z), (1.0, 0.0)), ((round(x1 - 0.02, 3), round(y, 3), z), (-1.0, 0.0))]
    return out


# ---------- what moves by itself ----------

NATURAL = [   # (words, motion) — checked against a thing's kind and name
    ({"sea", "ocean", "lake", "water", "island", "wave", "bay", "lagoon"}, "waves"),
    ({"pool", "pond", "fountain", "jacuzzi", "spa", "hottub", "puddle", "basin"}, "ripples"),
    ({"river", "stream", "creek", "brook", "canal"}, "flow"),
    ({"waterfall", "cascade"}, "falls"),
    ({"fire", "flame", "campfire", "bonfire", "torch", "fireplace", "candle", "brazier"}, "fire"),
    ({"smoke", "steam", "mist"}, "smoke"),
    ({"rain", "drizzle", "downpour"}, "rain"),
    ({"snow", "snowfall", "blizzard"}, "snow"),
    ({"cloud", "clouds"}, "drift"),
    ({"flag", "banner", "pennant", "windsock", "curtain", "sail"}, "flutter"),
    ({"windmill", "turbine", "pinwheel"}, "spin"),
]
WIND_SWAYS = {"tree", "palm", "pine", "oak", "birch", "maple", "willow", "bush", "shrub", "hedge", "grass", "reed",
              "bamboo", "flower", "plant", "fern", "sunflower"}


def natural_motion(t, text=""):
    """The motion a thing has by itself, or None: waves on open water, ripples in a pool, a flowing river, falling
    water, flickering fire, rising smoke, rain, snow, drifting clouds, a fluttering flag, a turning windmill — and
    trees swaying, but only when the request says there's wind. Nothing when the request asks for it static."""
    if is_static(text):
        return None
    kind = (t.get("asset_type") or "").lower()
    words = set(spatial.words_of(t.get("name"))) | {kind}
    if kind == "island":
        return "waves"
    for vocab, motion in NATURAL:
        if words & vocab:
            return motion
    if words & WIND_SWAYS and _WIND.search(str(text or "")):
        return "sway"
    return None


# ---------- verifying motion ----------

_EPS = {"rot": 0.0012, "loc": 0.004, "lo": 0.004, "hi": 0.004, "scale": 0.002, "sig": 0.004, "energy": 0.01,
        "lens": 0.05, "particles": 0.5, "shader": 0.001}


def moved(samples, eps=None):
    """Did anything about a sampled object change over time? samples: [{frame, lo, hi, loc, rot, scale, energy,
    sig...}] — a change bigger than what's measurable for that quantity (a tenth of a degree, a few millimetres)
    counts; `eps` overrides it for everything."""
    if len(samples) < 2:
        return False
    keys = [k for k in samples[0] if k != "frame"]
    for k in keys:
        vals = [s.get(k) for s in samples]
        if any(v is None for v in vals):
            continue
        flat = [list(v) if isinstance(v, (list, tuple)) else [v] for v in vals]
        for i in range(len(flat[0])):
            col = [f[i] for f in flat if i < len(f)]
            if isinstance(col[0], (int, float)) and max(col) - min(col) > (eps if eps is not None else
                                                                          _EPS.get(k, 0.01)):
                return True
    return False
