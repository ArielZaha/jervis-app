"""Jervis's agent: understand a request, plan it, act, check the real result, and fix what went wrong.

    request -> PLAN (one call to the local AI: steps, each with code + checks, and checks for the whole request)
            -> for each step: ACT (the app adapter runs the code) -> OBSERVE (read the app's real state)
                              -> VERIFY (the step's checks, in plain code — no AI opinion involved)
                              -> on an error or a failed check: ROLL BACK the step, ask the AI to REPAIR it
                                 (it sees its code, the exact error / failed checks, and the real state), retry
            -> VERIFY the whole request -> one fix-up round if something's still missing
            -> report only what was verified ("8 of 8 checks passed"), never a bare claim

Apps plug in as adapters (AppAdapter): Blender (agent_blender.py) and Minecraft (agent_minecraft.py) today; a new
app needs only an adapter — how to act, how to read its state, what checks mean — not changes here.

Speed: a typical request is ONE model call (the plan carries the code); repairs are only paid for when something
actually fails. The model is the local "agent" model (local_llm.model_for), kept warm in the GPU.
"""
import re
import threading
import time
import traceback

import local_llm

MAX_REPAIRS = 2


class AppGone(Exception):
    """The app stopped answering (closed, crashed, frozen): nothing an AI rewrite of the step can fix — the task
    stops at once and says so, instead of "repairing" the step against an app that isn't there."""


class AppAdapter:
    """How the agent works with one app. Subclass and override; see agent_blender.BlenderAdapter."""
    name = "app"
    label = "the app"
    check_types = ("exists",)
    uses_input = False      # True when acting means sending keys/clicks (needs the user's OK to control the computer)

    def available(self) -> tuple:
        return True, ""

    def prepare(self) -> None:
        """Make the app ready (load helpers, focus its window...). Raises with a plain-words message if it can't."""

    def observe(self) -> dict:
        return {}

    def describe(self, state: dict) -> str:
        """The state, as compact text for the AI."""
        return ""

    def instructions(self) -> str:
        """What the AI needs to know to act on this app: the API, conventions, check types, an example."""
        return ""

    def execute(self, code: str) -> dict:
        """Run one step's code: {"ok": bool, "output": str, "error": str}."""
        raise NotImplementedError

    def snapshot(self):
        return None

    def rollback(self, snapshot) -> None:
        """Undo what happened since `snapshot` (so a repaired step starts clean)."""

    def evaluate(self, check: dict, state: dict) -> tuple:
        """(True / False / None for "can't tell", detail) for one check against the real state."""
        return None, f"unknown check type {check.get('type')!r}"

    def auto_checks(self, code: str) -> list:
        """Checks implied by the code itself, for a step the AI gave none."""
        return []

    def usable_checks(self, checks, goal: str) -> list:
        """The AI's checks worth trusting: well-formed, known types, no duplicates. Adapters drop kinds the AI tends
        to get wrong (a check that contradicts its own code would make every repair chase the wrong thing)."""
        seen, out = set(), []
        for c in checks or []:
            if not isinstance(c, dict) or c.get("type") not in self.check_types:
                continue
            key = tuple(sorted((k, str(v)) for k, v in c.items() if v not in (None, "")))
            if key not in seen:
                seen.add(key)
                out.append({k: v for k, v in c.items() if v not in (None, "")})
        return out

    def extra_failures(self, before, state: dict, goal: str) -> list:
        """Mistakes the adapter can spot by itself after a step (beyond the step's checks), as plain sentences."""
        return []

    def auto_fix(self, before, state: dict, goal: str) -> list:
        """Mistakes the adapter can correct by itself, deterministically, right after a step (no AI involved).
        Returns what it fixed, as plain sentences (then the state is read again)."""
        return []

    relational_checks = ()   # check types that relate two things: the AI's own ones can be wrong, see _run_step

    def check_is_guess(self, check: dict, code: str) -> bool:
        """Whether a failing check of the AI's is only its guess about something the code never states (a name it
        expects a helper to have given): then it's left unconfirmed instead of failing a step that works."""
        return False

    scene_layout = False   # True when the app can build a scene thing by thing (see AgentTask._run_scene)

    def known_names(self, state: dict):
        """The names of what's in the app now (None if it has no named objects): checks naming none of these and
        nothing the plan's code makes are dropped as the AI's slips."""
        return None

    def place_scene(self, things: list, state: dict) -> list:
        """Final positions for a scene's things (the AI's layout made to fit the actual scene)."""
        return things

    def place_thing(self, thing: dict, state: dict) -> dict:
        """Where one thing of a scene goes, decided just before it's built, on the app's real state (the thing it
        stands by may have just been built). Returns the thing with "x", "y" (and "placed": how, in words)."""
        return thing

    def stages(self, goal: str) -> list:
        """The request as construction stages run one after another (e.g. build the scene, then direct a cinematic
        of it). [goal] when it is one stage."""
        return [goal]

    def finishing_touches(self, before, goal: str) -> list:
        """What the adapter adds by itself once a request is built, verified (e.g. water that moves, trees swaying
        in the wind), as plain sentences."""
        return []

    def scene_fix(self, before, state: dict, goal: str, things: list) -> tuple:
        """Once every thing of a scene is built: correct how they stand relative to each other, deterministically.
        (what was fixed, what is still wrong) as plain sentences."""
        return [], []

    def quick_plan(self, goal: str, state: dict, ask_json):
        """A complete plan the adapter can make itself, without the general planner (e.g. a finished asset the app
        has: one structured choice instead of the AI inventing geometry). None: plan normally."""
        return None

    def save_step(self, part: str):
        """A step that saves the user's work when `part` is only "save it" / "save it as X", else None."""
        return None

    def subject_of(self, before, state: dict):
        """What the last request made, for the next part of a sequence to refer to: (name, kind) or None."""
        return None

    def contextualize(self, part: str, subject) -> str:
        """`part` of a sequence with its unsaid context filled in ("add trees" right after building an island ->
        "add trees on the Island")."""
        return part

    def closing_steps(self, goal: str, plan: dict) -> list:
        """Steps the request asked for at the end that the plan must not leave out (e.g. "... and save it")."""
        return []

    def quality_guidance(self, tier: str) -> str:
        """What "simple" / "normal" / "high" quality means for this app, told to the AI when planning."""
        return ""

    def quality_issues(self, before, state: dict, goal: str, tier: str = "normal") -> list:
        """What looks poor about what this request made, as concrete fixes ([] = fine). Drives inspect-and-refine."""
        return []

    def risk(self, code: str) -> str:
        """Why this code needs the user's OK first, or ""."""
        return ""

    def sanitize(self, code: str, goal: str) -> str:
        """The code with lines removed that must never run for this request and do nothing else (a lone
        "clear the scene" the user didn't ask for). "" means the step has nothing left to do."""
        return code

    def guard(self, code: str, goal: str) -> str:
        """Why this code must not run at all for this request (it would destroy what the user didn't ask to touch),
        or "". The reason goes back to the AI as the step's error, so it writes the step another way."""
        return ""

    def finished(self, before, success: bool, goal: str) -> None:
        """After the whole request (e.g. set up "undo", remember what was made)."""

    def made(self, before, state: dict) -> list:
        """Names of what this request created, for the summary."""
        return []

    def describe_made(self, before, state: dict) -> str:
        """What this request built, in words, when the adapter knows (finished assets); '' otherwise."""
        return ""

    def self_contained(self, steps: list, made: list) -> bool:
        """Whether these steps only touch what they made themselves (so they're a fair example for another time)."""
        return True


def _check_schema(types) -> dict:
    return {"type": "object", "properties": {
        "type": {"type": "string", "enum": list(types)}, "object": {"type": "string"}, "other": {"type": "string"},
        "color": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"},
        "value": {"type": "string"}}, "required": ["type"]}


def plan_schema(types) -> dict:
    check = _check_schema(types)
    return {"type": "object", "properties": {
        "understanding": {"type": "string"},
        "question": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "code": {"type": "string"}, "checks": {"type": "array", "items": check}},
            "required": ["title", "code"]}},
        "final_checks": {"type": "array", "items": check}},
        "required": ["understanding", "steps", "final_checks"]}


def repair_schema(types) -> dict:
    return {"type": "object", "properties": {
        "diagnosis": {"type": "string"}, "code": {"type": "string"},
        "checks_were_wrong": {"type": "boolean"},
        "checks": {"type": "array", "items": _check_schema(types)}},
        "required": ["diagnosis", "code", "checks_were_wrong"]}

AGENT_RULES = """You are the planning and coding brain of Jervis, a voice assistant that operates apps on the \
user's computer. You receive a request, the app's REAL current state, and context. You answer with JSON only.

Plan:
- "understanding": one short sentence of what the user wants, in plain words.
- "steps": the request broken into small, concrete steps in order. Each step has a short "title" and the "code" that \
does it. Simple requests are ONE step. That everything your code names really exists is verified automatically; add \
step "checks" only for something specific that matters (a color, what rests on what).
- "final_checks": checks that prove the WHOLE request is done (the user's key words: colors, counts, what is on \
what). Be specific and only check what the user asked for or what your code clearly makes.
- "question": only if the request is genuinely impossible to interpret, or it names something that isn't in the \
state (e.g. "color the roof" with no roof): then ask, and give no steps. Never quietly change something else instead. \
Otherwise "".
- Complex requests are built in stages, each relying only on what earlier steps really made: the main structure \
first, then things placed relative to it (where they go is measured, not guessed), then what connects them (paths), \
then details and small props. A step never continues as if an earlier one had worked when it didn't.
Never claim anything in text: the checks are how success is decided."""

FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


# How much modelling effort a request deserves, from its own words: quick commands stay quick, "detailed"/"realistic"
# requests get the full treatment (more tokens, more parts, more inspect-and-refine rounds).
_HIGH = re.compile(r"\b(?:high[- ]?quality|hq|detailed|detail|realistic|beautiful|professional|polished|intricate|"
                   r"photo[- ]?real\w*|stunning|gorgeous|elaborate|amazing|impressive|lots of detail|very nice|"
                   r"best|fancy|ornate|cinematic)\b", re.I)
_SIMPLE = re.compile(r"\b(?:simple|basic|quick(?:ly)?|rough|low[- ]?poly|placeholder|blocky|minimal|fast|primitive)\b",
                     re.I)
TIERS = {   # (plan tokens, repair tokens, inspect-and-refine rounds)
    "simple": (2500, 2000, 0),
    "normal": (4500, 3000, 1),
    "high": (7000, 4500, 2),
}


# A request that may name several separate things ("a park with a bench, two trees and some rocks"): one quick call
# decides whether it really is several things, and lays them out; each is then built on its own, with the whole
# plan -> build -> verify -> inspect -> refine treatment. One model writing a whole scene in one go does it badly.
_SCENE_WORDS = re.compile(r"\b(?:scene|park|garden|village|town|street|yard|backyard|camp(?:site|ground|ing|s)?|farm|forest|playground|"
                          r"landscape|island|beach|plaza|square|courtyard|neighbou?rhood)\b", re.I)
_SEVERAL = re.compile(r"\b(?:two|three|four|five|six|several|a few|some|many|\d+)\s+\w+s\b|,.*\band\b", re.I)
MAX_SCENE_THINGS = 8
RELATIONS = ["", "beside", "near", "in front of", "behind", "left of", "right of", "inside", "on", "connects"]
LAYOUT_SCHEMA = {"type": "object", "properties": {
    "separate_things": {"type": "boolean"},
    "things": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "request": {"type": "string"},
        "relation": {"type": "string", "enum": RELATIONS}, "anchor": {"type": "string"}, "to": {"type": "string"},
        "x": {"type": "number"}, "y": {"type": "number"}, "radius": {"type": "number"},
        "width": {"type": "number"}, "depth": {"type": "number"}},
        "required": ["name", "request", "x", "y"]}}},
    "required": ["separate_things", "things"]}
LAYOUT_PROMPT = """You lay out scenes for a 3D modelling assistant. Decide whether the request is ONE thing (however \
detailed: "a house with a red roof, a door and two windows" is one house) or SEVERAL separate things ("a park with a \
bench, two trees and some rocks" is a bench, a tree, a tree and a group of rocks; "a villa with a pool beside it and \
a path to the pool" is a villa, a pool and a path).
If several, list each separate thing to build (at most 8; "two trees" = two entries) IN BUILD ORDER: the main \
structures first, then the things placed relative to them, then the paths between things, then small props and \
plants. For each:
- "name": a short unique name prefix in Title Case ("Villa", "Pool", "Path", "Tree 1", "Tree 2"),
- "request": what to build, keeping the user's details (colours, style, quality words): "a modern villa",
- "relation" + "anchor": where it stands relative to ANOTHER thing of the list (by its name) or to something already
  in the scene: "beside", "near", "in front of", "behind", "left of", "right of", "inside" (furniture in a house),
  "on" (a lamp on a table), or "" when nothing is said. "a pool beside the villa" -> "beside", anchor "Villa".
  A path, walkway or driveway between two things: relation "connects", anchor = where it starts (a building means
  its entrance), "to" = where it ends ("a path from the entrance to the pool" -> anchor "Villa", to "Pool").
- "x", "y": a rough spot in metres around the scene's centre (0, 0), for things with no relation (spread out, 2-4 m
  of room between things),
- "width", "depth": its footprint in metres (a villa 12 x 9, a pool with its deck 11 x 7, a tree 4 x 4, a bench
  1.8 x 0.7, a car 4.6 x 1.9).
Outdoor things (pools, trees, cars, paths, fountains) always stand outside buildings. Reply as JSON."""


def looks_like_scene(goal: str, known=()) -> bool:
    if _SCENE_WORDS.search(goal or "") or _SEVERAL.search(goal or ""):
        return True
    # "a villa with a pool beside it": one thing placed by ANOTHER new thing is a scene of two
    import spatial
    known_words = {w for name in (known or ()) for w in spatial.words_of(name)}
    for intent in spatial.parse_relations(goal or ""):
        subject, anchor = str(intent.get("subject") or ""), str(intent.get("anchor") or "")
        if anchor.startswith("'") or not subject or subject == anchor:
            continue
        if anchor in spatial.DOOR_WORDS or anchor in spatial.ROOMS:
            anchor = next((w for w in spatial.words_of(goal) if w in spatial.BUILDING), anchor)
        if anchor not in known_words and not (anchor in spatial.BUILDING and known_words & spatial.BUILDING):
            return True
    return False


def order_things(things: list) -> list:
    """Build order for a scene: what others stand by comes before them, paths (which connect two things) after both
    their ends, everything else in the layout's order."""
    names = {str(t.get("name") or "").lower() for t in things}
    connectors = [t for t in things if str(t.get("relation") or "").lower() == "connects"]
    pending = [t for t in things if t not in connectors]
    out, done = [], set()
    while pending:
        moved = False
        for t in list(pending):
            anchor = str(t.get("anchor") or "").lower()
            if anchor in names and anchor != str(t.get("name") or "").lower() and anchor not in done:
                continue
            out.append(t)
            done.add(str(t.get("name") or "").lower())
            pending.remove(t)
            moved = True
        if not moved:   # a cycle ("A beside B", "B beside A"): keep the layout's order
            out += pending
            break
    return out + connectors


_LAYOUT_RELATION = {"front": "in front of", "left": "left of", "right": "right of"}
_COUNTED = re.compile(r"^\s*(?:two|three|four|five|six|seven|eight|several|some|a few|a couple of|a pair of|\d+)\s+",
                      re.I)


def _one_each(things: list) -> list:
    """"two pine trees" laid out as Tree 1 and Tree 2 must each build ONE tree: a small model often copies the
    whole phrase into both ("two pine trees behind it" twice), and each then built two."""
    import spatial
    out = []
    for t in things:
        request = str(t.get("request") or "")
        same = sum(1 for u in things if str(u.get("request") or "").strip().lower() == request.strip().lower())
        m = _COUNTED.match(request)
        if m and same > 1:
            rest = request[m.end():]
            words = rest.split()
            # the counted noun is the last plural word before any "behind it", "with ...", etc.
            cut = next((i for i, w in enumerate(words) if w.lower() in ("behind", "in", "on", "near", "beside", "next",
                                                                         "with", "by", "around", "and", "to")), len(words))
            head = [spatial.singular(w) if i == cut - 1 else w for i, w in enumerate(words[:cut])]
            t = dict(t, request=" ".join(["a"] + head + words[cut:]))
        out.append(t)
    return out


def _relations_from_goal(goal: str, things: list) -> list:
    """Each thing's relation as the request's own words state it, wherever the layout left it out (a small model
    often lists "a pool" with no relation for "a villa with a pool beside it"): its words decide, not the model."""
    import spatial
    intents = spatial.parse_relations(goal or "")
    out = []
    for t in things:
        t = dict(t)
        own_words = set(spatial.words_of(t.get("name"))) | {spatial._first_noun(t.get("request"))}
        if own_words & spatial.PATH and str(t.get("relation") or "").strip().lower() != "connects":
            # a path, walkway or driveway connects two places, whatever the layout said ("beside the villa")
            link = next((i for i in intents if i.get("relation") == "connects"), None)
            if link is not None:
                t["relation"], t["anchor"], t["to"] = "connects", link.get("anchor"), link.get("to")
                out.append(t)
                continue
        if not str(t.get("relation") or "").strip():
            words = set(spatial.words_of(t.get("name"))) | set(spatial.words_of(t.get("request")))
            for intent in intents:
                subject = str(intent.get("subject") or "")
                if not (subject in words or (subject in spatial.PATH and words & spatial.PATH)):
                    continue
                anchor = str(intent.get("anchor") or "")
                own = set(spatial.words_of(t.get("name"))) | {spatial._first_noun(t.get("request"))}
                if anchor in own and anchor not in spatial.DOOR_WORDS:
                    continue   # its own kind is no anchor ("a bench near the fountain" names the fountain: fine)
                relation = spatial.normalize_relation(intent.get("relation"))
                t["relation"] = _LAYOUT_RELATION.get(relation, relation)
                t["anchor"], t["to"] = anchor, intent.get("to") or t.get("to")
                break
        out.append(t)
    return out


def _resolve_names(things: list) -> list:
    """The layout's anchors as the names of its things ("the villa" -> 'Villa'), where they refer to one."""
    import spatial
    by_words = [(t, set(spatial.words_of(t.get("name"))) | {spatial._first_noun(t.get("request"))}) for t in things]
    out = []
    for t in things:
        t = dict(t)
        for key in ("anchor", "to"):
            ref = str(t.get(key) or "").strip().strip("'\"")
            if not ref:
                continue
            exact = next((u["name"] for u, _ in by_words if u.get("name", "").lower() == ref.lower()), None)
            if exact is None:
                head = spatial.head_noun(ref)
                if head in spatial.DOOR_WORDS:   # "the entrance": the building's
                    exact = next((u["name"] for u, w in by_words if w & spatial.BUILDING), None)
                else:
                    exact = next((u["name"] for u, w in by_words if head in w and u is not t), None)
            t[key] = exact or ref
        out.append(t)
    return out


def quality_tier(goal: str) -> str:
    if _HIGH.search(goal or ""):
        return "high"
    if _SIMPLE.search(goal or ""):
        return "simple"
    return "normal"


def clean_code(code) -> str:
    return FENCE.sub("", str(code or "").strip()).strip()


def plain_error(text) -> str:
    """An error as the user should hear it: "Error: ValueError: There is no room (at line 3 of your code)" ->
    "There is no room"."""
    text = re.sub(r"^\s*Error:\s*", "", str(text or ""))
    text = re.sub(r"^(?:[A-Z]\w*(?:Error|Exception)):\s*", "", text)
    return re.sub(r"\s*\(at line \d+ of your code\)", "", text).strip()


def _touches_sentence(touches) -> str:
    return "I also gave it its natural motion: " + "; ".join(touches[:4]) + "."


def sentences(text, max_len: int = 300) -> str:
    """As many whole sentences of `text` as fit in `max_len` — never cut off mid-sentence (a summary that ends
    "But there is " says nothing; one that ends "natural motion: " says something false)."""
    text = tidy(text, "", 100000)
    if len(text) <= max_len:
        return text
    out = ""
    for m in re.finditer(r"(?:[^.!?]|[.!?](?=[^\s\"”)]))+(?:[.!?]+[\"”)]*|$)\s*", text):
        if len(out) + len(m.group(0)) > max_len:
            break
        out += m.group(0)
    return out.strip() or tidy(text, "", max_len).rsplit(" ", 1)[0] + "…"


def tidy(text, fallback: str = "", max_len: int = 220) -> str:
    text = " ".join(str(text or "").split())
    text = re.sub(r"[*_`#]", "", text).strip(" -•")
    return text[:max_len] if any(c.isalpha() for c in text) else fallback


class SequenceTask:
    """Several things asked for in one go — "create a detailed island, add trees, improve the water, and save it" —
    each done properly, IN ORDER: every part is its own AgentTask (understand, plan, act, verify, repair), the next
    one starts only when the last really finished, and each knows what the earlier ones made ("add trees" after the
    island means on it). A part that fails stops the sequence and says exactly what was done and what wasn't; a save
    asked for at the end still runs, so the finished work is kept. Same controls as AgentTask."""

    def __init__(self, goal: str, parts: list, adapter: AppAdapter, report=None, log=print, confirm=None,
                 history=(), memory=None, ask_json=None):
        self.goal = " ".join((goal or "").split())
        self.parts = [p for p in parts if p.strip()]
        self.adapter = adapter
        self.report = report or (lambda state: None)
        self.log = log
        self.confirm = confirm
        self.history = list(history or [])
        self.memory = memory
        self.ask_json = ask_json or local_llm.chat_json
        self.state = "starting"
        self.result = ""
        self.step = 0
        self.max_steps = len(self.parts)
        self.child = None
        self._stopped = False

    def stop(self):
        self._stopped = True
        if self.child is not None:
            self.child.stop()

    def pause(self, why: str = ""):
        if self.child is not None:
            self.child.pause(why) if why else self.child.pause()

    def resume(self):
        if self.child is not None:
            self.child.resume()

    @property
    def stopped(self) -> bool:
        return self._stopped

    def _report(self, state, detail=""):
        self.state = state
        try:
            self.report({"state": state, "detail": detail, "goal": self.goal, "step": self.step,
                         "maxSteps": self.max_steps})
        except Exception as e:
            self.log(f"Could not report the sequence's state: {e}")

    def _finish(self, state, message):
        self.result = message
        self._report(state, message)
        return message

    def run(self) -> str:
        done, subject, failed, saved = [], None, None, ""
        try:
            ok, why = self.adapter.available()
            if not ok:
                return self._finish("error", why)
            for self.step, part in enumerate(self.parts, 1):
                if self._stopped:
                    break
                save = self.adapter.save_step(part)
                if save is not None:
                    if failed is not None and not done:
                        continue   # nothing was made: nothing to save
                    self._report("acting", f"Saving ({self.step} of {self.max_steps})")
                    result = self.adapter.execute(save["code"])
                    saved = (result.get("output") if result.get("ok")
                             else f"I couldn't save it: {plain_error(result.get('error'))}")
                    continue
                if failed is not None:
                    continue   # later parts build on the one that failed
                goal = self.adapter.contextualize(part, subject)
                self._report("acting", f"{part[0].upper() + part[1:]} ({self.step} of {self.max_steps})")
                self.log(f"Sequence part {self.step}/{self.max_steps}: {goal}")
                self.adapter.goal = goal
                self.adapter.prepare()
                before = self.adapter.snapshot()
                self.child = AgentTask(goal, self.adapter, report=lambda s: None, log=self.log, confirm=self.confirm,
                                       history=self.history, memory=self.memory, ask_json=self.ask_json)
                result = self.child.run()
                self.history.append((goal, result))
                if self.child.state == "completed" and not result.startswith("I couldn't"):
                    done.append((part, result))
                    subject = self.adapter.subject_of(before, self.adapter.observe()) or subject
                elif self.child.state == "stopped":
                    self._stopped = True
                else:
                    failed = (part, result)
            return self._finish(*self._summary(done, failed, saved))
        except AppGone as e:
            return self._finish("error", str(e))
        except Exception as e:
            traceback.print_exc()
            return self._finish("error", f"Something went wrong ({type(e).__name__}: {str(e)[:160]}).")

    def _summary(self, done, failed, saved):
        def short(text):
            text = re.sub(r"\s*I checked it in [^.]*\.(?:\s*\([^)]*\))?", "", text)
            text = text.replace("Done: ", "").replace("Done — ", "")
            built = re.search(r"\bI built (.+)", text)   # "Build an island. I built a 30 m island ..." -> the second
            return tidy(built.group(0) if built else text, "", 260)
        lines = [f"{i}. {short(r)}" for i, (_, r) in enumerate(done, 1)]
        if saved:
            lines.append(saved if saved.startswith("I couldn't") else saved + ".")
        body = " ".join(lines)
        if self._stopped:
            return "stopped", f"Stopped after {len(done)} of {self.max_steps} parts. {body}".strip()
        if failed is not None:
            part, why = failed
            return "error", (f"I did {len(done)} of {self.max_steps} parts" + (f": {body}" if body else ".")
                             + f" But “{part}” didn't work: {tidy(why, '', 200)} I stopped there.")
        return "completed", f"Done, all {len(done)} parts, each checked: {body}"


class StepOutcome:
    def __init__(self, title, ok, detail="", attempts=1, passed=0, total=0):
        self.title, self.ok, self.detail, self.attempts, self.passed, self.total = title, ok, detail, attempts, passed, total


class AgentTask:
    """One request, carried out on its own thread with the same controls as computer_use.ComputerTask (state,
    stop, pause, resume, run() -> the sentence to say), so app.py runs and shows it the same way."""

    def __init__(self, goal: str, adapter: AppAdapter, report=None, log=print, confirm=None, history=(),
                 memory=None, ask_json=None, max_repairs: int = MAX_REPAIRS, allow_scene: bool = True,
                 allow_stages: bool = True):
        self.goal = " ".join((goal or "").split())
        self.adapter = adapter
        self.report = report or (lambda state: None)
        self.log = log
        self.confirm = confirm
        self.history = list(history or [])
        self.memory = memory
        self.ask_json = ask_json or local_llm.chat_json
        self.max_repairs = max_repairs
        self.state = "starting"
        self.result = ""
        self.step = 0
        self.max_steps = 0
        self.plan = None
        self.outcomes = []
        self.fixup_step = None
        self.unconfirmed = []
        self.auto_fixed = False
        self.tier = quality_tier(self.goal)
        self.allow_scene = allow_scene
        self.allow_stages = allow_stages
        self.touches = []          # what the adapter added by itself, verified (water that moves...)
        self.refined = []          # [(step, StepOutcome)] inspect-and-refine rounds that were kept
        self.fixes = []            # what the adapter corrected by itself (a thing moved out of a building...)
        self.quality_left = []     # what the quality check still objects to at the end
        self._stop = threading.Event()
        self._running = threading.Event()
        self._running.set()

    # ---------- controls (same as ComputerTask) ----------
    def stop(self):
        self._stop.set()
        self._running.set()

    def pause(self, why: str = "Paused. Say “continue” when you want me to go on.") -> None:
        if not self._stop.is_set():
            self._running.clear()
            self._report("paused", why)

    def resume(self) -> None:
        self._running.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _checkpoint(self) -> bool:
        if not self._running.is_set():
            self._running.wait()
        return not self._stop.is_set()

    def _report(self, state: str, detail: str = "") -> None:
        self.state = state
        try:
            self.report({"state": state, "detail": detail, "goal": self.goal, "step": self.step,
                         "maxSteps": self.max_steps})
        except Exception as e:
            self.log(f"Could not report the agent's state: {e}")

    def _finish(self, state: str, message: str) -> str:
        self.result = message
        self._report(state, message)
        return message

    # ---------- the loop ----------
    def run(self) -> str:
        before = None
        try:
            ok, why = self.adapter.available()
            if not ok:
                return self._finish("error", why)
            self._report("thinking", f"Getting {self.adapter.label} ready…")
            self.adapter.goal = self.goal   # what this request is allowed to touch can depend on its words
            self.adapter.prepare()
            before = self.adapter.snapshot()
            state = self.adapter.observe()
            if not self._checkpoint():
                return self._finish("stopped", "Stopped.")
            if self.allow_stages:
                stages = [g for g in self.adapter.stages(self.goal) if g.strip()]
                if len(stages) > 1:
                    return self._run_stages(stages, before)
            self._report("thinking", "Planning…")
            started = time.time()
            if hasattr(self.adapter, "set_progress"):   # a long plan (looking at a picture) says how it's going
                self.adapter.set_progress(lambda text: self._report("thinking", text))
            quick = self.adapter.quick_plan(self.goal, state, self.ask_json)
            if quick is None and self.allow_scene and self.adapter.scene_layout and looks_like_scene(
                    self.goal, self.adapter.known_names(state) or ()):
                things = self._layout(state)
                if len(things) > 1:
                    return self._run_scene(things, before)
            self.plan = quick or self._plan(state)
            self.plan["steps"] += self.adapter.closing_steps(self.goal, self.plan)
            self.log(f"Agent plan ({time.time() - started:.1f}s): {self.plan.get('understanding')} — "
                     f"{[s['title'] for s in self.plan['steps']]}")
            if not self.plan["steps"]:
                question = tidy(self.plan.get("question"), "Can you say that a different way?")
                return self._finish("completed", question)
            self.max_steps = len(self.plan["steps"])
            for self.step, step in enumerate(self.plan["steps"], 1):
                if not self._checkpoint():
                    return self._finish("stopped", "Stopped. What I'd done so far is still there.")
                self._report("acting", f"{step['title']} ({self.step} of {self.max_steps})")
                self.outcomes.append(self._run_step(step))
                if not self.outcomes[-1].ok:
                    break   # later steps build on this one: carrying on would only fail the same way, slower
            final, fixup = self._verify_final(before)
            all_ran = len(self.outcomes) == len(self.plan["steps"]) and all(o.ok for o in self.outcomes)
            success = (all_ran or (fixup is not None and fixup.ok)) and all(p is not False for p, _ in final)
            if success:
                final = self._inspect_and_refine(before, final)
                self.touches = self.adapter.finishing_touches(before, self.goal)
                if self.touches:
                    self.log(f"Agent finishing touches: {self.touches}")
            summary = self._summary(final, before, fixup)
            self.adapter.finished(before, success, self.goal)
            # Only clean results become examples for later requests: right first time, nothing auto-fixed, repaired
            # or left unconfirmed. "Verified" means the parts exist with the right colors — not that it looks right —
            # so a build that needed rescuing would teach its flaws to every similar request after it.
            clean = (success and fixup is None and not self.auto_fixed and not self.unconfirmed
                     and not self.quality_left and all(o.attempts == 1 for o in self.outcomes))
            if clean and self.memory is not None:
                steps = [{"title": s["title"], "code": s["code"]} for s in self.plan["steps"]]
                steps += [{"title": s["title"], "code": s["code"]} for s, _ in self.refined]
                # And only builds that stand on their own: one that leans on this scene's objects ("on top of
                # 'House Roof'") would teach the next, unrelated request to do the same.
                if self.adapter.self_contained(steps, self.adapter.made(before, self.adapter.observe())):
                    self.memory.remember(self.goal, self.adapter.name, steps)
            return self._finish("completed" if success else "error", summary)
        except local_llm.LocalAIUnavailable as e:
            return self._finish("error", f"I couldn't plan that: {e}.")
        except AppGone as e:
            return self._finish("error", str(e))
        except Exception as e:
            traceback.print_exc()
            return self._finish("error", f"Something went wrong ({type(e).__name__}: {str(e)[:160]}).")

    # ---------- stages: build the scene, then direct it ----------
    def _run_stages(self, stages: list, before) -> str:
        """Construction stages in order, each a full request of its own (plan, act, verify, repair): a later stage
        (a cinematic of the villa) only runs once the earlier one (the villa) really exists."""
        self.log(f"Agent stages: {stages}")
        self.max_steps = len(stages)
        done = []
        for self.step, stage in enumerate(stages, 1):
            if not self._checkpoint():
                return self._finish("stopped", "Stopped. What I'd done so far is still there.")
            self._report("acting", f"{stage[0].upper() + stage[1:]} ({self.step} of {len(stages)})")
            child = AgentTask(stage, self.adapter, report=lambda state: None, log=self.log, confirm=self.confirm,
                              history=self.history + [(g, r) for g, r in done], memory=self.memory,
                              ask_json=self.ask_json, max_repairs=self.max_repairs, allow_scene=self.allow_scene,
                              allow_stages=False)
            child.tier = self.tier
            result = child.run()
            if child.state != "completed":
                self.adapter.goal = self.goal
                first = " ".join(sentences(r, 260) for _, r in done)
                return self._finish("stopped" if child.state == "stopped" else "error",
                                    (f"{first} " if first else "") + f"But “{stage}” didn't work: {sentences(result, 320)}")
            done.append((stage, result))
        self.adapter.goal = self.goal
        return self._finish("completed", " ".join(sentences(r, 360) for _, r in done))

    # ---------- scenes: several separate things, each built properly on its own ----------
    def _layout(self, state: dict) -> list:
        try:
            raw = self.ask_json([{"role": "system", "content": LAYOUT_PROMPT},
                                 {"role": "user", "content": f"Request: {self.goal}"}], LAYOUT_SCHEMA,
                                max_tokens=900, temperature=0.2)
        except local_llm.LocalAIUnavailable:
            return []
        if not raw.get("separate_things"):
            return []
        things = [t for t in (raw.get("things") or []) if isinstance(t, dict) and t.get("request")]
        things = _relations_from_goal(self.goal, _one_each(things[:MAX_SCENE_THINGS]))
        for t in things:
            t.setdefault("x", 0.0)
            t.setdefault("y", 0.0)
            rel = str(t.get("relation") or "").strip().lower()
            t["relation"] = rel if rel in RELATIONS else ""
        return self.adapter.place_scene(order_things(_resolve_names(things)), state)

    def _run_scene(self, things: list, before) -> str:
        """Build each thing of a scene as its own request (full quality treatment each), in dependency order and
        each placed on the real scene as it is by then (by what it stands next to), then check and correct how they
        all stand together, and report on the whole."""
        self.log(f"Agent scene: {[(t['name'], t.get('relation'), t.get('anchor'), t['x'], t['y']) for t in things]}")
        self.max_steps = len(things)
        built, failed = [], []
        failed_names = set()
        for self.step, thing in enumerate(things, 1):
            if not self._checkpoint():
                return self._finish("stopped", "Stopped. What I'd built so far is still there.")
            if {str(thing.get("anchor") or "").lower(), str(thing.get("to") or "").lower()} & failed_names:
                # it stands by (or leads to) something that didn't get built: building it would put it nowhere
                failed.append((thing, f"it depends on {thing.get('anchor')}, which didn't get built"))
                failed_names.add(thing["name"].lower())
                continue
            self._report("acting", f"Building {thing['request']} ({self.step} of {len(things)})")
            thing = self.adapter.place_thing(thing, self.adapter.observe())
            where = f", {thing['placed']}" if thing.get("placed") else ""
            goal = (f"{thing['request']} — name its parts '{thing['name']} ...', build it at x={thing['x']:.1f}, "
                    f"y={thing['y']:.1f} (X, Y){where} and finish with assemble('{thing['name']}')")
            child = AgentTask(goal, self.adapter, report=lambda state: None, log=self.log, confirm=self.confirm,
                              history=self.history, memory=self.memory, ask_json=self.ask_json,
                              max_repairs=self.max_repairs, allow_scene=False)
            child.tier = self.tier
            result = child.run()
            if child.state == "completed":
                built.append((thing, result))
            else:
                failed.append((thing, result))
                failed_names.add(thing["name"].lower())
        self.adapter.goal = self.goal
        state = self.adapter.observe()
        fixed, wrong = self.adapter.scene_fix(before, state, self.goal, [t for t, _ in built])
        if fixed:
            self.auto_fixed = True
            self.log(f"Agent scene fixes: {fixed}")
            state = self.adapter.observe()
        self.touches = self.adapter.finishing_touches(before, self.goal) if built else []
        made = self.adapter.made(before, state)
        self.adapter.finished(before, not failed and not wrong, self.goal)
        names = ", ".join(t["request"] for t, _ in built)
        checked = (f" I checked how everything stands together and corrected {len(fixed)} placement"
                   f"{'s' if len(fixed) != 1 else ''}." if fixed else " I checked how everything stands together.")
        summary = f"Done: I built {names} ({len(made)} parts), each one checked and inspected in {self.adapter.label}." \
                  + checked
        if failed:
            summary = (f"I built {names or 'nothing'}" + f" ({len(made)} parts), but " +
                       "; ".join(f"{t['request']} didn't work ({tidy(r, '', 100)})" for t, r in failed) + ".")
        if self.touches:
            summary += " " + _touches_sentence(self.touches)
        if wrong:
            summary += " But this still isn't right: " + "; ".join(tidy(w, "", 140) for w in wrong[:2]) + "."
        return self._finish("completed" if not failed and not wrong else "error", summary)

    def _messages(self, user: str) -> list:
        return [{"role": "system", "content": AGENT_RULES + "\n\n" + self.adapter.instructions()},
                {"role": "user", "content": user}]

    def _context(self, state: dict) -> str:
        parts = [f"Request: {self.goal}", "", f"Current state of {self.adapter.label} (read just now):",
                 self.adapter.describe(state) or "(nothing)"]
        if self.history:
            parts += ["", "Earlier in this conversation (most recent last):"]
            parts += [f"- {g} -> {tidy(r, '', 160)}" for g, r in self.history[-4:]]
        if self.memory is not None:
            for example in self.memory.similar(self.goal, self.adapter.name):
                parts += ["", f"A similar request that worked before (adapt it; names/positions may differ): "
                              f"\"{example['goal']}\""]
                parts += [f"  step '{s['title']}':\n{s['code']}" for s in example["steps"][:6]]
        return "\n".join(parts)

    def _plan(self, state: dict) -> dict:
        guidance = self.adapter.quality_guidance(self.tier)
        raw = self.ask_json(self._messages(self._context(state) + (f"\n\n{guidance}" if guidance else "") +
                                           "\n\nReply with the plan as JSON."),
                            plan_schema(self.adapter.check_types), max_tokens=TIERS[self.tier][0], timeout=300)
        raw = raw if isinstance(raw, dict) else {}   # a garbled answer is no plan, never a crash
        steps = []
        for s in (raw.get("steps") or [])[:12]:
            code = self.adapter.sanitize(clean_code(s.get("code")), self.goal)
            if not code:
                continue   # e.g. a "Clear the scene" step nobody asked for: dropped, not repaired three times
            checks = self.adapter.usable_checks(s.get("checks"), self.goal)
            checks += [c for c in self.adapter.auto_checks(code) if c not in checks]
            steps.append({"title": tidy(s.get("title"), f"Step {len(steps) + 1}", 80), "code": code,
                          "checks": checks})
        final = self.adapter.usable_checks(raw.get("final_checks"), self.goal)
        # A check about something no code here makes and that isn't there already (a "Ground" nobody builds) can
        # never pass: it's the AI's slip, not a requirement — leave it out rather than fail a good build on it.
        known = self.adapter.known_names(state)
        if known is not None:
            code = " ".join(s["code"] for s in steps).lower()
            def real(c):
                # An object the code really names (in quotes: box('Cabin Walls', ...)); a variable of the code
                # ("free_space") is never an object, so a check for it could only fail.
                name = str(c.get("object") or "")
                return (not name or name in known or
                        re.search(r"""['"]""" + re.escape(name.split()[0].lower()), code) is not None)
            final = [c for c in final if real(c)]
            for s in steps:
                s["checks"] = [c for c in s["checks"] if real(c)]
        return {"understanding": tidy(raw.get("understanding"), self.goal), "question": raw.get("question") or "",
                "steps": steps, "final_checks": final}

    def _evaluate(self, checks, state) -> list:
        results = []
        for check in checks:
            try:
                results.append(self.adapter.evaluate(check, state))
            except Exception as e:
                results.append((None, f"couldn't evaluate {check}: {e}"))
        return results

    def _run_step(self, step: dict) -> StepOutcome:
        code, tried = step["code"], []
        # A step the adapter wrote itself (a finished asset, a save) is known-good code: when it fails, the reason
        # is the scene ("no free ground on the island"), which an AI rewrite can't change — it would only burn a
        # minute inventing something else. It fails once, with that reason.
        attempts = 1 if step.get("quick") else self.max_repairs + 1
        for attempt in range(1, attempts + 1):
            if not self._checkpoint():
                return StepOutcome(step["title"], False, "stopped", attempt)
            risk = self.adapter.risk(code)
            if risk and not (self.confirm and self.confirm(f"Can I {risk}?")):
                return StepOutcome(step["title"], False, "skipped: not allowed", attempt)
            snapshot = self.adapter.snapshot()
            refused = self.adapter.guard(code, self.goal)
            if refused:
                self.log(f"Agent: refused to run step {self.step}: {refused}")
                result = {"ok": False, "output": "", "error": f"Not run: {refused}"}
            else:
                result = self.adapter.execute(code)
            state = self.adapter.observe()
            checked = self._evaluate(step["checks"], state) if result.get("ok") else []
            # A check the adapter knows is only the AI's guess about names (see check_is_guess): unconfirmed, not a
            # reason to fail a step that works.
            checked = [(None, d) if p is False and self.adapter.check_is_guess(c, code) else (p, d)
                       for c, (p, d) in zip(step["checks"], checked)] + checked[len(step["checks"]):]
            failed = list(dict.fromkeys(detail for passed, detail in checked if passed is False))
            if result.get("ok") and failed and attempt > 1:
                # The code runs cleanly and only the AI's own relational expectations still fail after a repair:
                # with a small model those checks are as likely wrong as the code. Keep the result, but don't count
                # them as confirmed (the request's final checks still decide success).
                relational = [c for c, (p, _) in zip(step["checks"], checked)
                              if p is False and c.get("type") in self.adapter.relational_checks]
                if len(relational) == sum(1 for p, _ in checked if p is False):
                    self.log(f"Agent: accepting step {self.step} with unconfirmed checks: {failed}")
                    checked = [(None if p is False else p, d) for p, d in checked]
                    failed = []
            if result.get("ok") and not failed:
                step["code"] = code   # what actually worked (remembered for similar requests)
                passed = sum(1 for p, _ in checked if p)
                total = sum(1 for p, _ in checked if p is not None)
                self.log(f"Agent step {self.step} ok: {step['title']} ({passed}/{total} checks)")
                return StepOutcome(step["title"], True, result.get("output") or "", attempt, passed, total)
            problem = (f"Error: {result.get('error')}" if not result.get("ok")
                       else "These checks failed: " + "; ".join(failed))
            self.log(f"Agent step {self.step} attempt {attempt} failed: {problem[:300]}")
            tried.append((code, problem))
            self.adapter.rollback(snapshot)
            if attempt >= attempts:
                break
            self._report("acting", f"Fixing: {step['title']} (try {attempt + 1})")
            code = self._repair(step, tried) or code
        return StepOutcome(step["title"], False, tried[-1][1] if tried else "failed", len(tried))

    def _repair(self, step: dict, tried: list) -> str:
        """Corrected code for a failed step. The AI may also say its own step checks were wrong (a radius taken
        for a width, "above" for an eye on a face) and replace them; the request's final checks never change, and
        the adapter's own checks (each object the code names must exist) are always kept."""
        state = self.adapter.observe()
        attempts = "\n\n".join(f"Attempt {i}:\n{code}\nResult: {problem}" for i, (code, problem) in
                               enumerate(tried, 1))
        checks = "; ".join(str(c) for c in step["checks"]) or "(none)"
        user = (self._context(state) + f"\n\nYou are fixing the step \"{step['title']}\" of this request. Its "
                f"checks: {checks}\n\n{attempts}\n\nEverything the failed attempt made was undone: the state above "
                "is from BEFORE this step, so objects that step created don't exist now. Find the real cause (read "
                "the error and the state: exact names, argument names, positions, and remember every builder "
                "stands on `at`). Then write the COMPLETE code for this step again, from scratch. If a failed check "
                "itself was a mistake (it contradicts what the step should make), set \"checks_were_wrong\": true "
                "and give the corrected \"checks\". Reply as JSON.")
        try:
            fix = self.ask_json(self._messages(user), repair_schema(self.adapter.check_types),
                                max_tokens=TIERS[self.tier][1], temperature=0.2 + 0.25 * (len(tried) - 1),
                                timeout=300)
        except local_llm.LocalAIUnavailable:
            return ""
        fix = fix if isinstance(fix, dict) else {}
        code = self.adapter.sanitize(clean_code(fix.get("code")), self.goal)
        self.log(f"Agent repair: {tidy(fix.get('diagnosis'), '', 200)}")
        if fix.get("checks_were_wrong") and code:
            replaced = self.adapter.usable_checks(fix.get("checks"), self.goal)
            auto = [c for c in self.adapter.auto_checks(code) if c not in replaced]
            step["checks"] = replaced + auto
            self.log(f"Agent: step checks corrected to {step['checks']}")
        elif code:   # the new code may name objects the old one didn't (door() became box('Door', ...))
            step["checks"] = step.get("checks", []) + [c for c in self.adapter.auto_checks(code)
                                                       if c not in step.get("checks", [])]
        return code

    def _inspect_and_refine(self, before, final: list) -> list:
        """INSPECT what was actually built (not whether the code ran) and, for as many rounds as the quality tier
        allows, have the AI improve what the inspection objects to: too primitive, too few parts, hard edges, flat
        colours, identical copies... A round that fails, or that breaks something the request needed, is undone, so
        refining can only make the result better. Returns the final check results after it."""
        rounds = TIERS[self.tier][2]
        for round_no in range(1, rounds + 1):
            issues = self.adapter.quality_issues(before, self.adapter.observe(), self.goal, self.tier)
            if not issues or not self._checkpoint():
                break
            self.log(f"Agent inspection (round {round_no}): {issues}")
            self._report("acting", f"Improving the model ({round_no} of {rounds})")
            snapshot = self.adapter.snapshot()
            step = {"title": f"Improve the model (round {round_no})", "checks": []}
            step["code"] = self._improvement(step, issues)
            if not step["code"]:
                break
            outcome = self._run_step(step)
            if not outcome.ok:
                continue    # _run_step already undid it
            after = self._whole_request_state(before)
            broke = [d for (was, _), (now, d) in zip(final, after) if was is not False and now is False]
            if broke:
                self.log(f"Agent: the improvement broke {broke}; undoing it")
                self.adapter.rollback(snapshot)
                break
            final = after
            self.refined.append((step, outcome))
        self.quality_left = self.adapter.quality_issues(before, self.adapter.observe(), self.goal, self.tier)
        if self.quality_left:
            self.log(f"Agent: quality notes left: {self.quality_left}")
        return final

    def _improvement(self, step: dict, issues: list) -> str:
        state = self.adapter.observe()
        problems = "\n".join(f"- {i}" for i in issues)
        guidance = self.adapter.quality_guidance(self.tier)
        user = (self._context(state) + f"\n\n{guidance}\n\nThe request has been built (the state above is the "
                f"result). An inspection of the result found these quality problems:\n{problems}\n\nWrite ONE step of "
                "code that fixes them: rebuild or reshape the parts this request made (building again with the same "
                "name replaces them) and add the missing parts and details, using the kit. Keep its position and "
                "everything that already works. Reply as JSON with \"diagnosis\", \"code\" and "
                "\"checks_were_wrong\": false.")
        try:
            fix = self.ask_json(self._messages(user), repair_schema(self.adapter.check_types),
                                max_tokens=TIERS[self.tier][1], temperature=0.3, timeout=300)
        except local_llm.LocalAIUnavailable:
            return ""
        self.log(f"Agent improvement plan: {tidy(fix.get('diagnosis'), '', 200)}")
        code = self.adapter.sanitize(clean_code(fix.get("code")), self.goal)
        step["checks"] = self.adapter.auto_checks(code)
        return code

    def prime(self) -> None:
        """Load the model and its (long) instructions into the GPU's cache ahead of time, so the real plan starts
        generating at once instead of first re-reading thousands of tokens."""
        try:
            self.ask_json(self._messages("Request: (warm-up, reply with an empty plan)"),
                          plan_schema(self.adapter.check_types), max_tokens=1)
        except Exception:
            pass

    def _whole_request_state(self, before) -> tuple:
        """Correct what the adapter can fix by itself, then check the whole request: (final check results incl.
        the adapter's own findings). Done once all steps ran, since a part may legitimately wait for a later step
        (a car body raised for wheels that come next)."""
        state = self.adapter.observe()
        fixed = self.adapter.auto_fix(before, state, self.goal)
        if fixed:
            self.auto_fixed = True
            self.fixes += [f for f in fixed if f not in self.fixes]
            self.log(f"Agent auto-fix: {'; '.join(fixed)}")
            state = self.adapter.observe()
        results = self._evaluate(self.plan["final_checks"], state)
        results += [(False, d) for d in self.adapter.extra_failures(before, state, self.goal)]
        return results

    def _verify_final(self, before=None) -> tuple:
        """Check the whole request. If anything is missing — a step that failed even after repairs, steps that never
        ran because of it, or final checks that fail — one fix-up step aimed at exactly that. Returns (final check
        results, the fix-up's StepOutcome or None)."""
        checks = self.plan["final_checks"]
        results = self._whole_request_state(before)
        failed = [detail for passed, detail in results if passed is False]
        broken = [(s, o) for s, o in zip(self.plan["steps"], self.outcomes) if not o.ok]
        not_run = self.plan["steps"][len(self.outcomes):]
        if not (failed or broken or not_run) or not self._checkpoint() or self.plan.get("quick"):
            return results, None
        problems, wanted = [], []
        for s, o in broken:
            problems.append(f"The step '{s['title']}' failed even after repairs: {o.detail}")
            wanted += s["checks"]
        if not_run:
            problems.append("These steps never ran: " + "; ".join(f"'{s['title']}'" for s in not_run))
            wanted += [c for s in not_run for c in s["checks"]]
        if failed:
            problems.append("These checks of the whole request fail: " + "; ".join(failed))
        self._report("acting", "Finishing what's still missing")
        self.fixup_step = {"title": "Finish what's still missing", "checks": self.adapter.usable_checks(
            wanted + checks, self.goal)}
        self.fixup_step["code"] = self._repair(self.fixup_step, [("(the steps above)", " ".join(problems))])
        outcome = self._run_step(self.fixup_step) if self.fixup_step["code"] else None
        return self._lenient_on_layout(self._whole_request_state(before)), outcome

    def _lenient_on_layout(self, results: list) -> list:
        """After the fix-up has had its chance: if all that still fails are the AI's own guesses about layout
        ("the car is above the roof"), report them as unconfirmed instead of calling a working build a failure.
        Facts — something missing, a wrong color, a wrong count, something floating — still fail."""
        checks = self.plan["final_checks"]
        layout = {i for i, (passed, _) in enumerate(results[:len(checks)])
                  if passed is False and checks[i].get("type") in self.adapter.relational_checks}
        others = [i for i, (passed, _) in enumerate(results) if passed is False and i not in layout]
        if not layout or others:
            return results
        self.unconfirmed = [results[i][1] for i in sorted(layout)]
        self.log(f"Agent: layout checks left unconfirmed: {self.unconfirmed}")
        return [(None if i in layout else p, d) for i, (p, d) in enumerate(results)]

    def _summary(self, final: list, before, fixup=None) -> str:
        state = self.adapter.observe()
        made = self.adapter.made(before, state)
        described = self.adapter.describe_made(before, state)
        outcomes = [o for o in self.outcomes if o.ok] + ([fixup] if fixup is not None and fixup.ok else [])
        passed = sum(o.passed for o in outcomes) + sum(1 for p, _ in final if p)
        total = sum(o.total for o in outcomes) + sum(1 for p, _ in final if p is not None)
        rescued = fixup is not None and fixup.ok
        failed_steps = [] if rescued else [o for o in self.outcomes if not o.ok] + (
            [fixup] if fixup is not None else [])
        failed_final = [d for p, d in final if p is False]
        what = self.plan["understanding"].rstrip(".")
        made_text = ""
        if len(made) > 3:
            made_text = f" I made {len(made)} parts, including {made[0]} and {made[1]}."
        elif made:
            made_text = f" I made {' and '.join(made)}."
        checked = f" I checked it in {self.adapter.label}: {passed} of {total} checks passed." if total else ""
        if self.unconfirmed:
            checked += f" ({len(self.unconfirmed)} layout detail(s) I couldn't confirm.)"
        if self.fixes:
            checked += (f" I corrected {len(self.fixes)} placement or shape problem"
                        f"{'s' if len(self.fixes) != 1 else ''} myself while checking it.")
        if self.refined:
            checked += (" I inspected it and improved the modelling" +
                        (f" {len(self.refined)} times." if len(self.refined) > 1 else "."))
        if described:
            made_text = f" I {described}." if described.startswith(("directed ", "set it going", "rebuilt ", "changed ")) \
                else f" I built {described}."
        elif self.plan.get("quick") and all(s["code"].startswith("rebuild_asset(") for s in self.plan["steps"]
                                            if s.get("title") != "Save the file"):
            made_text = ""   # the same thing, rebuilt with an option changed: its part count says nothing
        saved = [o.detail for o in self.outcomes if o.ok and str(o.detail).startswith("Saved to ")]
        if saved:
            made_text += f" {saved[-1]}."
        if self.touches:
            checked += " " + _touches_sentence(self.touches)
        if not failed_steps and not failed_final:
            return f"Done: {what}.{made_text}{checked}"
        problems = [f"the step “{o.title}” didn't work: {tidy(plain_error(o.detail), 'it failed', 110)}"
                    for o in failed_steps]
        problems += [tidy(d, "", 100) for d in failed_final if not failed_steps][:2]
        problems = problems[:2]
        if not made and not any(o.ok for o in self.outcomes):
            return f"I couldn't do that: {'; '.join(problems)}. I undid the attempt, so nothing is left half-done."
        return f"I did part of it: {what}.{made_text} But {'; '.join(problems)}.{checked}"
