"""Jarvis's brain as it runs on the phone, with no computer needed.

The phone app ("On this phone") loads this file and the same pure modules Jarvis uses on the computer (equations,
graphs, functions, earth, geo, planets, forecast, timers, music, typos) into Python running inside the phone's
browser (Pyodide, see phone_brain_worker.js). So a graph, a worked equation, a route on the globe, a planet or the
weather comes out exactly as it does on the computer, because it is the same code.

Nothing here acts on anything: handle() reads one message and returns what to say plus what the app should show or
do (a graph to draw, a timer to start, music to find). The app (phone_client.html) does the showing and doing.

The glue in this file mirrors app.py's own handlers of the same names (handle_math_followup, handle_graph_command,
handle_planet_command, handle_earth_command, answer_earth_request, handle_weather_command, handle_timer_command):
app.py's are tied to the computer's window and voice, these to nothing. tests/test_phone_brain.py holds the two to
the same answers.
"""
import re
import time
from datetime import datetime, timedelta, timezone

import earth
import equations
import forecast
import functions
import geo
import graphs
import music
import planets
import timers
from typos import fix_typos

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def _clock(moment) -> str:
    """"7:05 PM" (strftime's %-I isn't available everywhere this runs)."""
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _local(when, place: dict):
    """The time there, with its zone's name, when the place's time zone is known; else UTC, said as such."""
    try:
        from zoneinfo import ZoneInfo
        return when.astimezone(ZoneInfo(place.get("timezone") or "")), "local time"
    except Exception:
        return when.astimezone(timezone.utc), "UTC"


# ---------------------------------------------------------------- math follow-ups (app.py: handle_math_followup)
_ASK_STEPS = re.compile(
    r"\b(?:steps?|solution|answer|working|method|process|way\s+to)\b.*\b(?:show|give|tell|explain|what|how)\b"
    r"|\b(?:show|give|tell|explain|walk|what|whats|what's)\b.*\b(?:steps?|solution|working|method|process|way)\b"
    r"|\bhow\s+(?:did|do|can|would|should)\s+(?:you|i|we)\s+(?:get|solve|find|work\s+out|calculate|got)\s+(?:that|it|this|x|the\s+(?:answer|solution))\b"
    r"|\bexplain\s+(?:that|it|this|the\s+(?:solution|answer|steps?|way))\b"
    r"|\bwhy\b.*\b(?:answer|solution)\b")
_FOLLOWUP_WORDS = set("""what whats what's is are the way to solution solutions answer answers steps step show me give tell explain how did do you i we get got solve
find work out calculate that it this its why please can could method process working of for roots root zeros zero vertex minimum maximum lowest
highest intercept intercepts y where does cross touch hit jarvis hey and a an function parabola graph equation curve problem one more detail
details again solved by from came come up with was were so then x point points turning""".split())
_ASK_ROOTS = re.compile(r"\b(?:roots?|zeros?|solutions?|x\s*intercepts?|solve)\b|\bwhere\s+does\s+it\s+(?:cross|touch|hit)\b")
_ASK_VERTEX = re.compile(r"\b(?:vertex|minimum|maximum|lowest|highest|turning\s+point|extrema)\b")
_ASK_YINT = re.compile(r"\by\s*intercept\b")
_REFERS = re.compile(r"\b(?:it|its|that|this|them|the\s+(?:function|parabola|graph|equation|curve|solution|answer|problem)|that\s+one)\b")

# ---------------------------------------------------------------- weather (app.py: parse_weather_request)
_WEATHER_ASK = re.compile(
    r"\b(?:what'?s|what is|how'?s|how is|check|tell me|show me|show|open|give me|get me|bring up|display)\b.*\bweather\b"
    r"|\bweather\b.*\b(?:like|today|tonight|tomorrow|now|outside|forecast|this week|right now)\b"
    r"|^(?:the )?(?:weather|forecast|weather forecast|weather report)(?: please)?$"
    r"|\b(?:what'?s|what is|show me|show|open|check|give me) (?:the |my )?(?:weather )?forecast\b"
    r"|\bis it (?:raining|snowing|sunny|cloudy|cold|hot|windy)(?: outside| now| right now| today)?$"
    r"|\b(?:temperature|forecast)\b.*\b(?:outside|today|now)\b"
    r"|\bdo i need (?:an umbrella|a jacket|a coat)\b")
_WEATHER_TALK = re.compile(r"^(?:i|we|my|our|he|she|they|it was|the weather (?:was|has been))\b")


def parse_weather_request(text: str):
    """{"city": "" | "Paris"} for a weather request, else None."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower().replace("’", "'")).split())
    n = re.sub(r"^(?:(?:hey|ok|okay) )?(?:jarvis|jervis) ", "", n)
    if _WEATHER_TALK.match(n) or not _WEATHER_ASK.search(n):
        return None
    city = ""
    m = re.search(r"\b(?:weather|forecast|temperature|raining|snowing|sunny|cloudy|cold|hot|windy)\b.*?\b(?:in|for|at) "
                  r"(?P<c>[a-z' ]+?)(?: (?:today|tonight|tomorrow|now|right now|this week|please))*$", n)
    if m and m.group("c") not in ("the moment", "general", "my area", "my city", "here", "outside"):
        city = m.group("c").strip()
    return {"city": city}


def describe_timer(timer: dict) -> str:
    label = f" for {timer['label']}" if timer["label"] and timer["kind"] == "timer" else ""
    return f"{timers.format_duration(timer['total'])} timer{label}"


def timer_done_message(timer: dict) -> dict:
    """What to show and say when one ends (app.py: on_timer_fired)."""
    if timer["kind"] == "reminder":
        message = f"Reminder: {timer['label']}." if timer["label"] else "Time's up."
        return {"message": message, "spoken": message}
    message = f"Your {describe_timer(timer)} is done."
    return {"message": message, "spoken": f"Time's up. {message}"}


class Brain:
    """One conversation's worth of Jarvis: what was graphed or asked last, so follow-ups make sense."""

    def __init__(self):
        self.last_function = {"tree": None, "at": 0.0, "equation": None}
        self.pending_places_at = 0.0     # asked "which two places?": the next answer ("Israel and USA") is them
        self.last_route = {"a": None, "b": None, "at": 0.0}   # for "which countries does it fly over?"
        self.pending_choice = None       # {"request", "name", "options", "known", "at"}: "Which Valencia do you mean?"
        self.drawn = {"graph": 0, "globe": 0, "planet": 0}
        self._visual = None

    # ------------------------------------------------------------ the one way in
    def handle(self, text: str, settings: dict = None) -> dict:
        """What to do with one message. Always has "text" (the message with its typos fixed); has "reply" when this
        brain answered it, with any of "visual" (a graph, globe or planet for the app to draw), "weather" (the
        forecast to show), "timer" (one to start or cancel) and "music" (something to find and play)."""
        settings = settings or {}
        fixed = fix_typos(text or "")
        out = {"text": fixed}
        self._visual = None
        steps = (
            lambda: self._music(fixed),
            lambda: self._math_followup(fixed),
            lambda: self._earth_choice(fixed) or self._earth(fixed, settings) or self._earth_places_answer(fixed, settings),
            lambda: self._planet(fixed),
            lambda: self._weather(fixed, settings),
            lambda: self._graph(fixed),
            lambda: self._equation(fixed),
            lambda: self._timer(fixed, settings),
        )
        for step in steps:
            try:
                answer = step()
            except Exception as e:   # one skill failing must never take the others (or the chat) with it
                print(f"phone brain: {type(e).__name__}: {e}", flush=True)
                answer = None
            if answer:
                out.update({"reply": answer} if isinstance(answer, str) else answer)
                if self._visual:
                    out["visual"] = self._visual
                break
        return out

    def _show(self, payload: dict) -> None:
        self._visual = payload

    # ------------------------------------------------------------ music: only read here, the app finds and plays it
    def _music(self, text: str):
        request = music.parse_music_request(text)
        if request is None:
            return None
        found = {"query": request.query, "kind": request.kind, "service": request.service, "shuffle": request.shuffle,
                 "mine": request.mine, "by": request.by, "alt": request.alt, "public": request.public}
        if request.kind == "playlist" and request.service in ("", "spotify"):
            found["mix"] = music.spotify_mix(request.query) or music.spotify_mix(request.alt or "")
        return {"music": found}

    # ------------------------------------------------------------ math
    def _remember(self, tree, equation=None) -> None:
        self.last_function.update(tree=tree, at=time.time(), equation=equation)

    def _math_followup(self, text: str):
        last = self.last_function
        if last["tree"] is None or time.time() - last["at"] > 45 * 60:
            return None
        n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower().replace("’", "'")).split())
        if not n or len(n.split()) > 14 or "x" in functions._tokenize(functions.normalize(text)) or re.search(r"\d", n):
            return None
        if not set(n.split()) <= _FOLLOWUP_WORDS:
            return None
        tree, equation = last["tree"], last["equation"]
        asks_steps, asks_roots = bool(_ASK_STEPS.search(n)), bool(_ASK_ROOTS.search(n))
        asks_vertex, asks_yint = bool(_ASK_VERTEX.search(n)), bool(_ASK_YINT.search(n))
        if not (asks_steps or asks_roots or asks_vertex or asks_yint):
            return None
        if not (_REFERS.search(n) or asks_steps or re.search(r"\bwhat\s+(?:is|are)\s+the\b", n)):
            return None
        if asks_steps or asks_roots:
            worksheet = equations.solve(*(equation if equation else (tree, None)))
            if worksheet:
                return worksheet
        quadratic = functions.as_quadratic(tree)
        if quadratic is not None and quadratic[0] != 0:
            info = graphs.facts(*quadratic)
            if asks_vertex:
                vx, vy = info["vertex"]
                return (f"The vertex of {info['plain']} is at x equals {graphs._say(vx)} and y equals {graphs._say(vy)}. "
                        f"It is the {'lowest' if info['opens'] == 'up' else 'highest'} point.")
            if asks_yint:
                return f"The y-intercept of {info['plain']} is {graphs._say(info['yint'])}."
        analysis = functions.analyze(tree)
        described = functions.describe_function(tree, analysis, functions.build_view(tree, analysis))
        if asks_yint:
            return ("The function doesn't cross the y-axis." if described["yint"] is None
                    else f"The y-intercept is {graphs._say(described['yint'])}.")
        if asks_vertex:
            if not described["extrema"]:
                return "This function has no highest or lowest point in the view."
            return "It has " + ", ".join(f"a {e['type']} at x equals {graphs._say(e['x'])} and y equals {graphs._say(e['y'])}"
                                         for e in described["extrema"][:4]) + "."
        roots = described["roots"]
        return (("It crosses the x-axis at " + ", ".join(f"x equals {graphs._say(r)}" for r in roots[:6]) + ".")
                if roots else "It never crosses the x-axis in this view.")

    def _equation(self, text: str):
        equation = equations.parse_request(text)
        if not equation:
            return None
        solved = equations.solve(*equation)
        if not solved:
            return None
        left, right = equation
        self._remember(left if right is None else ["sub", left, right], equation)
        return solved

    def _graph(self, text: str):
        request = graphs.parse_request(text)
        if request is None:
            return None
        hint = "Tell me the equation, for example: graph y equals x squared minus 4x plus 3. Or give me a, b and c."
        if request["action"] == "last":
            if self.last_function["tree"] is not None and time.time() - self.last_function["at"] < 60 * 60:
                request = graphs.request_from_tree(self.last_function["tree"])
            elif request.get("explicit"):
                return hint
            else:
                return None
        if request.get("ast") is not None:
            self._remember(request["ast"])
        action = request["action"]
        if action == "close":
            self._show({"type": "close_graph"})
            return "Okay, I closed the graph."
        if action == "reshow":
            if not self.drawn["graph"]:
                return "I haven't drawn a graph yet. Give me a function and I'll draw it."
            self._show({"type": "show_graph", "which": request["which"]})
            return {"prev": "Here is the previous graph.", "next": "Here is the next graph.",
                    "first": "Here is the first graph."}.get(request["which"], "Here is the graph again.")
        if action == "ask":
            return hint
        if action == "unsupported":
            return "I can graph any function of x, like y equals something with x. Give me one of those."
        if action == "unclear":
            return "I couldn't read that as a function of x. Try something like: graph sine of x, or graph x cubed minus 3x."
        if action == "function":
            info = graphs.build_function(request["ast"])
            described = graphs.describe_function(info)
        else:
            info = graphs.facts(request["a"], request["b"], request["c"])
            described = graphs.describe(info)
        self._show({"type": "graph", "data": info})
        self.drawn["graph"] += 1
        if not request.get("solve"):
            return described
        try:   # "what is 2x + 6 = 0, draw the graph": the worked answer first, then what the graph shows
            equation = equations.parse_request(f"solve {request['solve']}")
            worksheet = equations.solve(*equation) if equation else None
        except Exception:
            worksheet = None
        return f"{worksheet}\n\n---\n\nI drew its graph too. {described}" if worksheet else described

    # ------------------------------------------------------------ planets
    def _planet(self, text: str):
        request = planets.parse_request(text)
        if request is None:
            return None
        if request["action"] == "close":
            self._show({"type": "close_planet"})
            return "Okay, I closed it."
        if request["action"] == "reshow":
            if not self.drawn["planet"]:
                return "I haven't shown a planet yet. Ask me to tell you about one."
            self._show({"type": "show_planet", "which": request["which"]})
            return {"prev": "Here is the previous one.", "next": "Here is the next one.",
                    "first": "Here is the first one."}.get(request["which"], "Here it is again.")
        if request["action"] == "ask":
            return "Which one? Try Mars, Jupiter, Saturn, or any other planet, the Sun, or the Moon."
        info = planets.build(request["body"])
        self.drawn["planet"] += 1
        self._show({"type": "planet", "data": info})
        return info["text"]

    # ------------------------------------------------------------ the Earth
    def _places_talked_about(self, settings: dict):
        """"Show me on the globe" right after the distance was asked: the two places from then."""
        for said in reversed((settings.get("history") or [])[-4:]):
            earlier = earth.parse_request(fix_typos(str(said)))
            if earlier and earlier["action"] in ("distance", "compare", "radius"):
                return earlier
        return None

    def _earth_places_answer(self, text: str, settings: dict):
        if time.time() - self.pending_places_at > 3 * 60:
            return None
        self.pending_places_at = 0.0
        places = re.fullmatch(r"(?:(?:from|between)\s+)?(.+?)\s+(?:and|to|&)\s+(.+?)[.!?]*", " ".join((text or "").split()), re.I)
        if not places or len(places.group(0).split()) > 10:
            return None
        return self._earth(f"what is the distance between {places.group(1)} and {places.group(2)}", settings)

    def _earth(self, text: str, settings: dict):
        request = earth.parse_request(text)
        if request is None:
            return None
        if request["action"] == "close":
            self._show({"type": "close_globe"})
            return "Okay, I closed the globe."
        if request["action"] == "reshow":
            if not self.drawn["globe"]:
                return "I haven't shown a globe yet. Ask me the distance between two places."
            self._show({"type": "show_globe", "which": request["which"]})
            return {"prev": "Here is the previous one.", "next": "Here is the next one.",
                    "first": "Here is the first one."}.get(request["which"], "Here it is again.")
        if request["action"] == "ask":
            earlier = self._places_talked_about(settings)
            if not earlier:
                self.pending_places_at = time.time()
                return "Which two places? For example: what's the distance between Tokyo and Paris."
            request = earlier
        return self._answer_earth(request)

    @staticmethod
    def _place_names(request: dict) -> list:
        if request["action"] == "distance":
            return [request["a"], request["b"]]
        if request["action"] == "compare":
            return [name for pair in request["pairs"] for name in pair]
        if request["action"] == "radius":
            return [request["a"]]
        if request["action"] == "sun" and request.get("place"):
            return [request["place"]]
        return []

    def _answer_earth(self, request: dict, known: dict = None):
        known = dict(known or {})
        if request["action"] == "route_followup":
            if not self.last_route["a"] or time.time() - self.last_route["at"] > 30 * 60:
                return ("Which route? Tell me both places, for example: which countries does a flight from Tel Aviv to "
                        "London pass over.")
            request = {"action": "distance", "a": self.last_route["a"]["name"], "b": self.last_route["b"]["name"],
                       "wants": request["wants"]}
            known.update({request["a"]: self.last_route["a"], request["b"]: self.last_route["b"]})
        for name in dict.fromkeys(self._place_names(request)):
            if name in known:
                continue
            try:
                place, options = earth.resolve(name)
            except Exception as e:   # a lookup bug must never cost the answer: fall back to the single best match
                print(f"Place lookup for {name!r} failed: {e!r}", flush=True)
                place, options = earth.geocode(name), None
            if options:
                self.pending_choice = {"request": request, "name": name, "options": options, "known": known, "at": time.time()}
                return f"Which {name.title()} do you mean: {options[0]['name']}, or {options[1]['name']}?"
            if not place:
                return f"I couldn't find {name}. Could you say it another way, maybe with the country?"
            known[name] = place
        action = request["action"]
        if action == "distance":
            info = earth.build(known[request["a"]], known[request["b"]])
            text = earth.describe(info, request.get("wants", ""))
            self.last_route.update(a=info["a"], b=info["b"], at=time.time())
        elif action == "compare":
            info = earth.build_compare([(known[a], known[b]) for a, b in request["pairs"]])
            text = earth.describe_compare(info, request.get("question"))
        elif action == "radius":
            center = known[request["a"]]
            places = geo.places_near(center["lat"], center["lon"], request["km"], limit=12, exclude_name=center["name"])
            info = earth.build_radius(center, request["km"], places)
            text = earth.describe_radius(info)
        elif action == "sun":
            info, text = self._sun(request["what"], known.get(request.get("place")) if request.get("place") else None)
        else:
            return None
        self.drawn["globe"] += 1
        self._show({"type": "globe", "data": info})
        return text

    def _earth_choice(self, text: str):
        pending = self.pending_choice
        if not pending or time.time() - pending["at"] > 3 * 60:
            return None
        n = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
        options = pending["options"]
        chosen = None
        if re.search(r"\b(?:first|1st|former|the first one)\b", n):
            chosen = options[0]
        elif re.search(r"\b(?:second|2nd|latter|other one|the second one)\b", n):
            chosen = options[1]
        else:
            scores = []
            for option in options:
                words = set(re.findall(r"[a-z]+", option["name"].lower())) - set(re.findall(r"[a-z]+", pending["name"].lower()))
                scores.append(len(words & set(n.split())))
            if max(scores) > 0 and scores.count(max(scores)) == 1:
                chosen = options[scores.index(max(scores))]
        if not chosen:
            if len(n.split()) <= 6:   # a short reply that names neither: ask once more, plainly
                return f"Sorry, which one: {options[0]['name']}, or {options[1]['name']}?"
            self.pending_choice = None
            return None
        self.pending_choice = None
        return self._answer_earth(pending["request"], {**pending["known"], pending["name"]: chosen})

    @staticmethod
    def _sun(what: str, place):
        """Where the Sun really is now (or at that place's sunrise/sunset), and what that means."""
        now = datetime.now(timezone.utc)
        sun = {**geo.subsolar_point(now), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if what in ("night_view", "where_day"):
            big = [p for p in geo._places() if p[5] >= 7_000_000]
            day = sorted({p[0] for p in big if geo.sun_elevation(p[3], p[4], now) > 0})
            night = sorted({p[0] for p in big if geo.sun_elevation(p[3], p[4], now) <= -6})
            if what == "night_view":
                info = earth.build_sun(what, None, sun, "Earth at night, right now")
                text = ("Here's the night side of Earth right now, with its city lights. "
                        + (f"It's night in {earth._join(night[:6])}." if night else ""))
            else:
                info = earth.build_sun(what, {"name": "", "lat": sun["lat"], "lon": sun["lon"]}, sun, "Day and night, right now")
                text = (f"Right now the Sun is straight overhead at {abs(sun['lat']):.1f}° {'N' if sun['lat'] >= 0 else 'S'}, "
                        f"{abs(sun['lon']):.1f}° {'E' if sun['lon'] >= 0 else 'W'}. "
                        + (f"It's daytime in {earth._join(day[:6])}" if day else "")
                        + (f", and night in {earth._join(night[:6])}." if night else "."))
            return info, text
        name = place["name"].split(",")[0]
        if what == "is_day":
            elevation = geo.sun_elevation(place["lat"], place["lon"], now)
            local, zone = _local(now, place)
            state = "daytime" if elevation > 0 else "twilight" if elevation > -6 else "night"
            info = earth.build_sun(what, place, sun, f"{name}, right now")
            return info, (f"It's {state} in {name} right now: {_clock(local)} {zone}, with the Sun "
                          f"{abs(elevation):.0f}° {'above' if elevation > 0 else 'below'} the horizon.")
        local_now, zone = _local(now, place)
        for offset in (0, 1):
            day = (local_now + timedelta(days=offset)).date()
            events = geo.sun_events(place["lat"], place["lon"], day)
            if "polar" in events:
                info = earth.build_sun(what, place, sun, f"{name}, right now")
                return info, (f"There's no {what} in {name} today: it's polar {events['polar']}, so the Sun "
                              + ("doesn't set." if events["polar"] == "day" else "doesn't rise."))
            moment = events[what]
            if moment > now - timedelta(minutes=30) or offset == 1:
                break
        local, zone = _local(moment, place)
        when_word = "today" if local.date() == local_now.date() else "tomorrow"
        at = {**geo.subsolar_point(moment), "at": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}
        info = earth.build_sun(what, place, at, f"{what.title()} over {name}")
        return info, (f"The Sun {'rises' if what == 'sunrise' else 'sets'} in {name} at {_clock(local)} "
                      f"{zone} {when_word}, {MONTHS[local.month - 1]} {local.day}. Here's the globe at that moment, with the "
                      f"{'dawn' if what == 'sunrise' else 'dusk'} line passing over it.")

    # ------------------------------------------------------------ weather
    def _weather(self, text: str, settings: dict):
        request = parse_weather_request(text)
        if request is None:
            return None
        try:
            data = forecast.get(city=request["city"], fallback_city=str(settings.get("weatherCity") or ""), radar=False)
        except forecast.WeatherError as e:
            return str(e)
        return {"reply": forecast.summary(data), "weather": data}

    # ------------------------------------------------------------ timers: read and answered here, kept by the app
    def _timer(self, text: str, settings: dict):
        active = sorted(settings.get("timers") or [], key=lambda t: t["end"])
        command = timers.parse_timer_command(text, have_timers=bool(active))
        if not command:
            return None
        action = command["action"]
        if action == "ask":
            return "How long should I set it for?"
        if action == "set":
            new = {"label": command["label"], "kind": command["kind"], "total": int(command["seconds"])}
            if new["kind"] == "reminder":
                what = f" to {new['label']}" if new["label"] else ""
                reply = f"Okay, I'll remind you{what} in {timers.format_duration(new['total'])}."
            else:
                reply = f"Timer set for {timers.format_duration(new['total'])}" + (f", for {new['label']}." if new["label"] else ".")
            return {"reply": reply, "timer": {"action": "set", **new, "done": timer_done_message(new)}}
        if action == "cancel":
            if command["all"]:
                victims = active
            else:
                matches = [t for t in active if command["label"] and command["label"] in t["label"]]
                victims = (matches or active)[:1]
            if not victims:
                return "You don't have any timers running."
            reply = (f"Cancelled all {len(victims)} timers." if len(victims) > 1
                     else f"Cancelled the {describe_timer(victims[0])}.")
            return {"reply": reply, "timer": {"action": "cancel", "ids": [t["id"] for t in victims]}}
        if not active:
            return "You don't have any timers running."
        now = time.time()
        lines = [f"the {describe_timer(t)} has {timers.format_duration(t['end'] - now, short=True)} left" for t in active]
        if len(lines) == 1:
            return lines[0][0].upper() + lines[0][1:] + "."
        return f"You have {len(lines)} timers: " + "; ".join(lines) + "."


_brain = Brain()


def handle(text: str, settings: dict = None) -> dict:
    return _brain.handle(text, settings)
