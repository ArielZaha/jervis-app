"""Jervis using the computer like a person: look at the screen, decide, act, check what happened, and go on.

    goal -> OBSERVE (what's on screen) -> DECIDE (the AI picks one action) -> ACT -> OBSERVE AGAIN -> VERIFY
         -> recover if nothing happened or something unexpected appeared -> ... -> DONE (or stopped, or asks)

How the screen is read: mainly through the operating system's accessibility information (every button, field, link
and menu item of the window in front, with its name and position), which is exact, instant and needs no vision
model. Where the computer can afford it, a vision model can also look at a screenshot ("look", "click_on").
How it acts: an element's own "press" action where possible, otherwise the mouse at the element's centre, and real
keyboard input. The platform parts live in screen_windows.py and screen_mac.py.

The user stays in control:
  - it only runs when allowed (Settings: ask before each task / allowed / never),
  - a visible "AI control active" bar shows every step, with Pause and Stop,
  - moving the mouse yourself pauses it at once (you're taking over),
  - risky steps (send, delete, buy, pay, sign out...) wait for your OK,
  - it never types into password fields, and never presses Jervis's own emergency-stop keys,
  - it stops after a fixed number of steps rather than wandering on.
"""
import hashlib
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field

MAX_STEPS = 25
MAX_INVALID = 4          # the AI's answer couldn't be used this many times in a row: give up and say so
SETTLE_TIMEOUT = 2.5     # seconds to wait for the screen to settle after an action
TAKEOVER_PIXELS = 40     # the pointer moved this far without Jervis moving it: the user took over
MAX_ELEMENTS_SHOWN = 120
# What the window registers as the emergency stop (never pressed by Jervis himself), as said aloud.
STOP_SHORTCUT = "Control Option Q" if sys.platform == "darwin" else "Ctrl+Alt+Q"

STATES = ("starting", "observing", "thinking", "acting", "waiting", "paused", "completed", "stopped", "error")

# What makes a step consequential enough to ask first.
RISKY_WORDS = re.compile(
    r"\b(send|sent|post|publish|reply|tweet|delete|remove|erase|trash|discard|empty|wipe|format|uninstall|reset|"
    r"buy|purchase|order|checkout|check out|pay|payment|transfer|donate|subscribe|unsubscribe|confirm|submit|"
    r"sign out|log out|logout|sign off|close account|deactivate|change password|forget)\b", re.I)
RISKY_KEYS = {"shift+delete", "ctrl+shift+delete", "cmd+backspace", "cmd+delete", "ctrl+enter", "cmd+enter",
              "alt+f4", "cmd+q"}
FORBIDDEN_KEYS = {"ctrl+alt+q", "ctrl+alt+delete", "cmd+alt+q"}
# Compared as sets, so "alt+ctrl+q" or "control option q" is the same shortcut.
_RISKY_COMBOS = {frozenset(k.split("+")) for k in RISKY_KEYS}
_FORBIDDEN_COMBOS = {frozenset(k.split("+")) for k in FORBIDDEN_KEYS}


@dataclass
class Element:
    id: int
    role: str
    name: str = ""
    value: str = ""
    rect: tuple = (0, 0, 0, 0)        # x, y, width, height in screen pixels
    enabled: bool = True
    focused: bool = False
    password: bool = False
    handle: object = None             # the platform's own object for the element (used to press it)

    @property
    def center(self):
        x, y, w, h = self.rect
        return (int(x + w / 2), int(y + h / 2))

    def label(self) -> str:
        text = self.name or self.value or ""
        return f"{self.role} “{text[:60]}”" if text else self.role

    def describe(self) -> str:
        parts = [f"[{self.id}] {self.role}"]
        if self.name:
            parts.append(f"“{self.name[:80]}”")
        if self.value and not self.password:
            parts.append(f"value=“{self.value[:60]}”")
        if self.password:
            parts.append("(password field)")
        if self.focused:
            parts.append("(focused)")
        if not self.enabled:
            parts.append("(disabled)")
        return " ".join(parts)


@dataclass
class Observation:
    app: str = ""
    window: str = ""
    elements: list = field(default_factory=list)
    other_windows: list = field(default_factory=list)
    screenshot: object = None          # a PIL image, when the platform can capture the screen
    screen_size: tuple = (0, 0)
    cursor: tuple = None
    note: str = ""                     # e.g. "accessibility permission is missing"

    def element(self, element_id):
        return next((e for e in self.elements if e.id == element_id), None)

    def fingerprint(self) -> str:
        items = [(e.role, e.name, e.value, tuple(int(v) // 4 for v in e.rect), e.focused) for e in self.elements]
        digest = hashlib.sha1(json.dumps([self.app, self.window, items], default=str).encode()).hexdigest()
        if self.screenshot is not None:
            try:
                small = self.screenshot.convert("L").resize((16, 10))
                digest += hashlib.sha1(small.tobytes()).hexdigest()[:12]
            except Exception:
                pass
        return digest


SINGLE_LINE_ROLES = {"text field", "search field", "combo box"}


class Environment:
    """What a platform provides. screen_windows.WindowsScreen and screen_mac.MacScreen implement it."""
    name = "unknown"
    select_all = ["ctrl", "a"]

    def available(self) -> tuple:
        """(True, "") if computer control can work here, else (False, what's missing, in plain words)."""
        return False, "Computer control isn't available on this computer."

    def observe(self) -> Observation:
        raise NotImplementedError

    def press_element(self, element: Element) -> str:
        return self.click(element.center)

    def click(self, point, button="left", double=False) -> str:
        raise NotImplementedError

    def type_text(self, text: str) -> str:
        raise NotImplementedError

    def press_keys(self, keys: list) -> str:
        raise NotImplementedError

    def scroll(self, amount: int, point=None) -> str:
        raise NotImplementedError

    def switch_window(self, title: str) -> str:
        raise NotImplementedError

    def open_app(self, name: str) -> str:
        from app_launcher import open_application
        return open_application(name)

    def cursor(self):
        return None

    def focus_moved(self) -> bool:
        """True when the user has since switched to another app (not Jervis's own window): keys must not follow."""
        return False

    def focus_element(self, element: Element) -> str:
        """Put the typing cursor in this element. "" when it's there; otherwise why not (then nothing is typed)."""
        return self.press_element(element) or ""


# ---------- the actions the AI may choose (the only things it can do) ----------
def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required)}}}


_ID = {"element": {"type": "integer", "description": "The number in [brackets] from the element list."}}
BASE_TOOLS = [
    _tool("click", "Click an element (buttons, links, fields, menu items, tabs, list items).", _ID, ["element"]),
    _tool("double_click", "Double-click an element (e.g. open a file in a list).", _ID, ["element"]),
    _tool("right_click", "Right-click an element to open its menu.", _ID, ["element"]),
    _tool("type_text", "Type text into `element` (or into whatever has focus). In a one-line field (text field, "
                       "search field, combo box) it replaces what's there; in a document or text area it is inserted "
                       "at the cursor.",
          {"text": {"type": "string"}, "element": {"type": "integer", "description": "Optional field to type into."},
           "press_enter": {"type": "boolean", "description": "Press Enter after typing (e.g. to search)."},
           "append": {"type": "boolean", "description": "Keep what's in a one-line field and add to the end."}},
          ["text"]),
    _tool("press_keys", "Press a key or shortcut, e.g. 'enter', 'escape', 'tab', 'ctrl+l', 'cmd+t', 'down'.",
          {"keys": {"type": "string"}}, ["keys"]),
    _tool("scroll", "Scroll the page or list up or down.",
          {"direction": {"type": "string", "enum": ["up", "down"]},
           "element": {"type": "integer", "description": "Optional: scroll inside this element."}}, ["direction"]),
    _tool("open_app", "Open (or bring forward) an app by name, e.g. 'Google Chrome', 'Settings', 'Notepad'.",
          {"name": {"type": "string"}}, ["name"]),
    _tool("switch_window", "Bring another open window to the front (use a title from 'Other windows').",
          {"title": {"type": "string"}}, ["title"]),
    _tool("wait", "Wait for something to load (1 to 5 seconds).", {"seconds": {"type": "number"}}, ["seconds"]),
    _tool("done", "The goal is achieved. Summarize what you did in one short sentence.",
          {"summary": {"type": "string"}}, ["summary"]),
    _tool("fail", "The goal can't be done (explain why in one sentence, and what the user could do).",
          {"reason": {"type": "string"}}, ["reason"]),
    _tool("ask_user", "Ask the user one short question when the goal is ambiguous (e.g. which file).",
          {"question": {"type": "string"}}, ["question"]),
]
VISION_TOOLS = [
    _tool("look", "Look at the screenshot to answer a question about what's visible (use when the element list "
                  "doesn't show what you need).", {"question": {"type": "string"}}, ["question"]),
    _tool("click_on", "Click something you can see but that isn't in the element list, by describing it.",
          {"description": {"type": "string"}}, ["description"]),
]

SYSTEM_PROMPT = """You operate the user's computer to achieve their goal, one action at a time, like a careful person.

Each turn you get: the goal, the app and window in front, a numbered list of the window's elements, other open
windows, what your last action did, and your earlier steps. Reply with exactly ONE tool call.

Rules:
- Use element numbers from the CURRENT list only. Never guess coordinates.
- To type into a field, pass its number to type_text (it gets clicked first). Use press_enter to submit searches.
- Browsers: ctrl+l (cmd+l on a Mac) focuses the address bar; type a search or address and press enter.
- If a popup, cookie banner or dialog appears, deal with it or dismiss it before continuing.
- If your last action changed nothing, don't repeat it: try something different (another element, a shortcut, wait).
- Never type passwords, payment details or personal data the user didn't give you.
- When the goal is achieved, call done with a one-sentence summary. If it truly can't be done, call fail.
- Stay on the user's goal; don't open things they didn't ask for."""


# Where Enter sends something to other people (a chat box, an email), unless it's that app's search box.
MESSAGING = re.compile(r"\b(messages?|reply|comment|chat|post|tweet|e-?mail|mail|compose|whatsapp|telegram|signal|"
                       r"slack|discord|teams|messenger|imessage|outlook|gmail|inbox|dm)\b", re.I)


def _enter_sends(target, observation) -> bool:
    if target is not None and (target.role == "search field" or re.search(r"\bsearch\b", target.name or "", re.I)):
        return False
    context = " ".join(filter(None, [target.name if target else "", target.role if target else "",
                                     observation.app if observation else "", observation.window if observation else ""]))
    return bool(MESSAGING.search(context))


def risk_of(action: dict, element, observation=None) -> str:
    """Why this step needs the user's OK first, or "" if it doesn't."""
    kind = action.get("action")
    focused = next((e for e in observation.elements if e.focused), None) if observation else None
    if kind in ("click", "double_click", "click_on"):
        text = " ".join(filter(None, [element.name if element else "", element.value if element else "",
                                      action.get("description", "")]))
        match = RISKY_WORDS.search(text)
        if match:
            return f"click “{(element.name if element else action.get('description', '')) or match.group(0)}”"
    if kind == "press_keys":
        combo = normalize_keys(action.get("keys", ""))
        if frozenset(combo) in _RISKY_COMBOS:
            return f"press {'+'.join(combo)}"
        if combo == ["enter"]:
            target = element or focused
            if target is not None and RISKY_WORDS.search(target.name or ""):
                return f"press Enter on “{target.name}”"
            if _enter_sends(target, observation):
                return "press Enter, which may send what's typed"
    if kind == "type_text" and action.get("press_enter") and _enter_sends(element or focused, observation):
        return f"send “{action.get('text', '')[:60]}”"
    return ""


def normalize_keys(keys: str) -> list:
    aliases = {"control": "ctrl", "command": "cmd", "option": "alt", "opt": "alt", "return": "enter",
               "esc": "escape", "del": "delete", "arrowdown": "down", "arrowup": "up", "arrowleft": "left",
               "arrowright": "right", "pgdn": "pagedown", "pgup": "pageup", "windows": "win", "meta": "cmd"}
    parts = [p.strip().lower() for p in re.split(r"[+\s]+", keys or "") if p.strip()]
    return [aliases.get(p, p) for p in parts]


def describe_change(before: Observation, after: Observation) -> str:
    """What an action did, in words the AI can reason about."""
    if before is None:
        return ""
    notes = []
    if (before.app, before.window) != (after.app, after.window):
        notes.append(f"Now in {after.app or 'another app'} — window “{after.window}”.")
    old = {(e.role, e.name) for e in before.elements}
    new = [e for e in after.elements if (e.role, e.name) not in old]
    gone = len(old - {(e.role, e.name) for e in after.elements})
    if new:
        shown = ", ".join(e.label() for e in new[:6])
        notes.append(f"{len(new)} new element(s) appeared: {shown}{'…' if len(new) > 6 else ''}.")
    if gone:
        notes.append(f"{gone} element(s) disappeared.")
    # Changed contents, for elements that can be told apart (several unnamed "text" elements can't); focused first.
    counts = {}
    for e in before.elements:
        counts[(e.role, e.name)] = counts.get((e.role, e.name), 0) + 1
    before_values = {(e.role, e.name): e.value for e in before.elements}
    changed = [e for e in after.elements if not e.password and counts.get((e.role, e.name)) == 1
               and before_values[(e.role, e.name)] != e.value]
    changed.sort(key=lambda e: not e.focused)
    for e in changed[:2]:
        what = f"[{e.id}] {e.role}" + (f" “{e.name[:60]}”" if e.name else "")
        notes.append(f"{what} now contains “{e.value[:80]}”." if e.value else f"{what} is now empty.")
    focused = next((e for e in after.elements if e.focused), None)
    before_focused = next((e for e in before.elements if e.focused), None)
    if focused and (not before_focused or (focused.role, focused.name) != (before_focused.role, before_focused.name)):
        notes.append(f"Focus is now on [{focused.id}] {focused.label()}.")
    if not notes:
        notes.append("Nothing on screen changed.")
    return " ".join(notes)


class ComputerTask:
    """One goal, carried out step by step on its own thread. Drive it with pause(), resume(), stop()."""

    def __init__(self, goal: str, env: Environment, ask_ai, report=None, confirm=None, vision=None,
                 max_steps: int = MAX_STEPS, log=print):
        self.goal = goal
        self.env = env
        self.ask_ai = ask_ai            # (messages, tools) -> OpenAI-style response (Jervis's own AI plumbing)
        self.report = report or (lambda state: None)
        self.confirm = confirm or (lambda question: False)   # blocking; True = the user said yes
        self.vision = vision            # optional: object with look(image, question) and locate(image, description)
        self.max_steps = max_steps
        self.log = log
        self.history = []               # [(action description, what happened)]
        self._stop = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self.state = "starting"
        self.result = ""
        self.step = 0
        self._expected_cursor = None

    # ---------- control from outside (voice, the window, the emergency shortcut) ----------
    def stop(self):
        self._stop.set()
        self._running.set()   # wake a paused task so it can stop

    def pause(self, why: str = "Paused. Say “continue” or press Resume.") -> None:
        if not self._stop.is_set():
            self._running.clear()
            self._report("paused", why)

    def resume(self) -> None:
        self._expected_cursor = None   # the user may have moved the pointer while paused
        self._running.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _report(self, state: str, detail: str = "") -> None:
        self.state = state
        try:
            self.report({"state": state, "detail": detail, "goal": self.goal, "step": self.step,
                         "maxSteps": self.max_steps})
        except Exception as e:
            self.log(f"Could not report computer-control state: {e}")

    def _checkpoint(self) -> bool:
        """Honour Pause and Stop between steps. False means stop now."""
        if not self._running.is_set():
            self._running.wait()
        return not self._stop.is_set()

    # ---------- the loop ----------
    def run(self) -> str:
        ok, why = self.env.available()
        if not ok:
            self._report("error", why)
            self.result = why
            return why
        before = None
        last_change = ""
        invalid = 0
        tools = BASE_TOOLS + (VISION_TOOLS if self.vision else [])
        try:
            for self.step in range(1, self.max_steps + 1):
                if not self._checkpoint():
                    return self._finish("stopped", "Stopped. You have control again.")
                self._report("observing", "Looking at the screen…")
                observation = self.env.observe()
                if self._user_took_over(observation):
                    self.pause("You moved the mouse, so I paused. Say “continue” when you want me to go on.")
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                    observation = self.env.observe()
                    last_change = "The user used the computer while you were paused; look at the screen again."
                self._report("thinking", "Deciding what to do next…")
                action, raw = self._decide(observation, last_change, tools)
                if not self._checkpoint():
                    return self._finish("stopped", "Stopped. You have control again.")
                problem = self._validate(action, observation)
                if problem:
                    invalid += 1
                    self.history.append((f"(invalid action: {raw[:120]})", problem))
                    last_change = f"Your last answer couldn't be used: {problem}"
                    if invalid >= MAX_INVALID:
                        return self._finish("error", "I couldn't work out how to do that on this screen, so I "
                                                     "stopped. You have control again.")
                    continue
                invalid = 0
                kind = action["action"]
                if kind == "done":
                    return self._finish("completed", action.get("summary") or "Done.")
                if kind == "fail":
                    return self._finish("error", action.get("reason") or "I couldn't do that.")
                if kind == "ask_user":
                    return self._finish("completed", action.get("question") or "What should I do?")
                element = observation.element(action.get("element")) if action.get("element") is not None else None
                risk = risk_of(action, element, observation)
                if risk:
                    self._report("waiting", f"Waiting for your OK to {risk}.")
                    if not self.confirm(f"Can I {risk}?"):
                        self.history.append((self._describe(action, element), "The user said no. Don't do it."))
                        last_change = "The user declined that step. Do something else, or call done/fail."
                        continue
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                if kind not in ("open_app", "switch_window", "wait", "look") and self.env.focus_moved():
                    self.pause("You switched to another window, so I paused. Say “continue” when you want me to go on.")
                    last_change = "The user switched windows while you were paused; look at the screen again."
                    if not self._checkpoint():
                        return self._finish("stopped", "Stopped. You have control again.")
                    continue
                description = self._describe(action, element)
                self._report("acting", description[0].upper() + description[1:])
                outcome = self._execute(action, element, observation)
                after = self._settle(observation)
                last_change = f"{outcome} {describe_change(observation, after)}".strip()
                self.history.append((description, last_change))
                self.log(f"Computer control step {self.step}: {description} -> {last_change[:160]}")
                before = after
            return self._finish("error", f"I took {self.max_steps} steps without finishing, so I stopped. "
                                         "You have control again.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._finish("error", f"Something went wrong while using the computer ({type(e).__name__}), "
                                         "so I stopped. You have control again.")
        finally:
            del before

    def _finish(self, state: str, message: str) -> str:
        self.result = message
        self._report(state, message)
        return message

    def _user_took_over(self, observation: Observation) -> bool:
        if self._expected_cursor is None or observation.cursor is None:
            return False
        dx = observation.cursor[0] - self._expected_cursor[0]
        dy = observation.cursor[1] - self._expected_cursor[1]
        return (dx * dx + dy * dy) ** 0.5 > TAKEOVER_PIXELS

    def _settle(self, before: Observation) -> Observation:
        """Wait (briefly) until the screen stops changing, so the next decision sees the result, not a half-drawn page."""
        deadline = time.time() + SETTLE_TIMEOUT
        time.sleep(0.35)
        latest = self.env.observe()
        while time.time() < deadline:
            time.sleep(0.4)
            again = self.env.observe()
            if again.fingerprint() == latest.fingerprint():
                latest = again
                break
            latest = again
        self._expected_cursor = latest.cursor
        return latest

    # ---------- asking the AI ----------
    def _prompt(self, observation: Observation, last_change: str) -> str:
        lines = [f"Goal: {self.goal}",
                 f"In front: {observation.app or 'unknown app'} — window “{observation.window}”"]
        if observation.note:
            lines.append(f"Note: {observation.note}")
        if observation.other_windows:
            lines.append("Other windows: " + "; ".join(f"“{w[:60]}”" for w in observation.other_windows[:12]))
        lines.append("Elements:")
        shown = observation.elements[:MAX_ELEMENTS_SHOWN]
        lines.extend(e.describe() for e in shown)
        if not shown:
            lines.append("(this window exposes no elements" + (": use look / click_on" if self.vision else
                                                             "; try keyboard shortcuts, or switch window") + ")")
        if len(observation.elements) > MAX_ELEMENTS_SHOWN:
            lines.append(f"(+{len(observation.elements) - MAX_ELEMENTS_SHOWN} more; scroll to see others)")
        if self.history:
            lines.append("Your steps so far:")
            for i, (did, happened) in enumerate(self.history[-8:], max(1, len(self.history) - 7)):
                lines.append(f"{i}. {did} → {happened[:200]}")
        if last_change:
            lines.append(f"Result of your last action: {last_change}")
        lines.append(f"Step {self.step} of {self.max_steps}. Reply with one tool call.")
        return "\n".join(lines)

    def _decide(self, observation: Observation, last_change: str, tools: list):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._prompt(observation, last_change)}]
        response = self.ask_ai(messages, tools)
        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            call = calls[0]
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except (ValueError, TypeError):
                return {"action": name, "_bad_json": True}, f"{name}({call.function.arguments})"
            if not isinstance(args, dict):
                args = {}
            return {"action": name, **args}, f"{name}({json.dumps(args)[:100]})"
        text = (getattr(message, "content", "") or "").strip()
        # Small local models sometimes write the call as JSON text instead of a tool call.
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                name = data.get("name") or data.get("action") or data.get("tool")
                args = data.get("arguments") or data.get("parameters") or {k: v for k, v in data.items()
                                                                            if k not in ("name", "action", "tool")}
                if isinstance(args, str):
                    args = json.loads(args)
                if name:
                    return {"action": name, **args}, text
            except (ValueError, TypeError, AttributeError):
                pass
        return {"action": None}, text or "(no answer)"

    def _validate(self, action: dict, observation: Observation) -> str:
        """Why this action can't be carried out, or "" if it can. Nothing unvalidated ever reaches the mouse."""
        kind = action.get("action")
        names = {t["function"]["name"] for t in BASE_TOOLS + (VISION_TOOLS if self.vision else [])}
        if action.get("_bad_json"):
            return "its arguments weren't valid JSON."
        if kind not in names:
            return f"“{kind}” isn't one of the available actions." if kind else "it wasn't a tool call."
        if kind in ("click", "double_click", "right_click") or (kind in ("type_text", "scroll") and
                                                               action.get("element") is not None):
            element_id = action.get("element")
            if not isinstance(element_id, int) and not (isinstance(element_id, str) and element_id.isdigit()):
                return "element must be a number from the list."
            action["element"] = int(element_id)
            element = observation.element(action["element"])
            if element is None:
                return f"there is no element [{element_id}] on the screen now."
            if not element.enabled and kind != "scroll":
                return f"[{element_id}] is disabled."
            if kind == "type_text" and element.password:
                return "that's a password field; Jervis never types passwords. Ask the user to type it."
        if kind == "type_text":
            if not isinstance(action.get("text"), str) or not action["text"]:
                return "type_text needs some text."
            if len(action["text"]) > 2000:
                return "that's too much text to type at once."
            focused = next((e for e in observation.elements if e.focused), None)
            if action.get("element") is None and focused is not None and focused.password:
                return "the focused field is a password field; Jervis never types passwords."
        if kind == "press_keys":
            combo = normalize_keys(action.get("keys", ""))
            if not combo:
                return "press_keys needs a key."
            if frozenset(combo) in _FORBIDDEN_COMBOS:
                return "that shortcut is reserved (it's the emergency stop, or a system shortcut)."
        if kind == "scroll" and action.get("direction") not in ("up", "down"):
            return "scroll direction must be up or down."
        if kind == "wait":
            try:
                action["seconds"] = max(0.5, min(5.0, float(action.get("seconds", 1))))
            except (TypeError, ValueError):
                return "wait needs a number of seconds."
        if kind in ("open_app", "switch_window") and not str(action.get("name") or action.get("title") or "").strip():
            return f"{kind} needs a name."
        if kind in ("look", "click_on") and not str(action.get("question") or action.get("description") or "").strip():
            return f"{kind} needs a description."
        return ""

    # ---------- doing it ----------
    @staticmethod
    def _describe(action: dict, element) -> str:
        kind = action["action"]
        target = element.label() if element else ""
        if kind in ("click", "double_click", "right_click"):
            return f"{kind.replace('_', '-')} {target}"
        if kind == "type_text":
            where = f" into {target}" if target else ""
            return f"type “{action['text'][:60]}”{where}" + (" and press Enter" if action.get("press_enter") else "")
        if kind == "press_keys":
            return f"press {'+'.join(normalize_keys(action['keys']))}"
        if kind == "scroll":
            return f"scroll {action['direction']}" + (f" in {target}" if target else "")
        if kind == "open_app":
            return f"open {action['name']}"
        if kind == "switch_window":
            return f"switch to “{action['title']}”"
        if kind == "wait":
            return f"wait {action['seconds']:.0f} s"
        if kind == "look":
            return f"look at the screen ({action['question'][:60]})"
        if kind == "click_on":
            return f"click {action['description'][:60]}"
        return kind

    def _execute(self, action: dict, element, observation: Observation) -> str:
        kind = action["action"]
        try:
            if kind == "click":
                return self.env.press_element(element) or ""
            if kind == "double_click":
                return self.env.click(element.center, double=True) or ""
            if kind == "right_click":
                return self.env.click(element.center, button="right") or ""
            if kind == "type_text":
                if element is not None and not element.focused:
                    problem = self.env.focus_element(element)
                    if problem:
                        return problem   # typing now would land somewhere else
                    time.sleep(0.1)
                if element is not None and element.role in SINGLE_LINE_ROLES and element.value \
                        and not action.get("append"):
                    self.env.press_keys(list(self.env.select_all))   # replace the old value, don't add to it
                    time.sleep(0.05)
                result = self.env.type_text(action["text"]) or ""
                if action.get("press_enter"):
                    time.sleep(0.1)
                    self.env.press_keys(["enter"])
                return result
            if kind == "press_keys":
                return self.env.press_keys(normalize_keys(action["keys"])) or ""
            if kind == "scroll":
                amount = -5 if action["direction"] == "down" else 5
                return self.env.scroll(amount, element.center if element else None) or ""
            if kind == "open_app":
                return str(self.env.open_app(action["name"]) or "")
            if kind == "switch_window":
                return self.env.switch_window(action["title"]) or ""
            if kind == "wait":
                time.sleep(action["seconds"])
                return ""
            if kind == "look":
                if observation.screenshot is None:
                    return "No screenshot is available on this computer."
                return f"You looked: {self.vision.look(observation.screenshot, action['question'])}"
            if kind == "click_on":
                if observation.screenshot is None:
                    return "No screenshot is available on this computer."
                point = self.vision.locate(observation.screenshot, action["description"], observation.screen_size)
                if point is None:
                    return f"Couldn't find “{action['description']}” on the screen."
                return self.env.click(point) or ""
        except Exception as e:   # one failed step is reported back to the AI, it never ends Jervis
            self.log(f"Computer control action failed: {type(e).__name__}: {e}")
            return f"That action failed ({type(e).__name__}: {str(e)[:120]})."
        return ""
