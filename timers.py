"""Voice timers and reminders: parsing spoken durations, keeping countdowns, and firing when they end."""
import json
import os
import re
import threading
import time
import paths

_FILE = os.path.join(paths.DATA_DIR, "timers.json")

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SECONDS_PER = {"h": 3600, "m": 60, "s": 1}


def _small_number(tokens: list, i: int):
    """Read 0-99 at position i ("twenty five", "thirteen", "seven"). Returns (value, next_index) or None."""
    if i >= len(tokens):
        return None
    word = tokens[i]
    if word in _TENS:
        value, j = _TENS[word], i + 1
        if j < len(tokens) and tokens[j] in _UNITS and 1 <= _UNITS[tokens[j]] <= 9:
            value += _UNITS[tokens[j]]
            j += 1
        return value, j
    if word in _UNITS:
        return _UNITS[word], i + 1
    return None


def _read_number(tokens: list, i: int):
    """Read a spoken number ("a hundred and five", "twenty five") at i, or None."""
    word = tokens[i]
    nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
    if nxt == "hundred" and (word == "a" or 1 <= _UNITS.get(word, 0) <= 9):
        value, j = (1 if word == "a" else _UNITS[word]) * 100, i + 2
        k = j + 1 if j < len(tokens) and tokens[j] == "and" else j
        rest = _small_number(tokens, k)
        if rest:
            return value + rest[0], rest[1]
        return value, j
    return _small_number(tokens, i)


def words_to_numbers(text: str) -> str:
    """"twenty five minutes" -> "25 minutes"; "one hundred and twenty seconds" -> "120 seconds"."""
    tokens, out, i = text.split(), [], 0
    while i < len(tokens):
        read = _read_number(tokens, i)
        if read:
            out.append(str(read[0]))
            i = read[1]
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out)


_UNIT_RE = r"(hours?|hrs?|minutes?|mins?|seconds?|secs?)"
_DURATION_PARTS = re.compile(
    rf"(?:(?P<mixed>\d+)\s+and\s+a\s+half\s+{_UNIT_RE}|"
    rf"(?P<n>\d+(?:\.\d+)?|an?|half\s+an?|half|quarter\s+of\s+an?)\s+{_UNIT_RE}(?P<plus>\s+and\s+a\s+half)?)")


def _unit_seconds(unit: str) -> int:
    return _SECONDS_PER[unit[0]] if unit[0] in _SECONDS_PER else 60


def parse_duration(text: str):
    """Return (seconds, text_without_the_duration) or (None, text)."""
    n = " ".join(re.sub(r"[^a-z0-9.' ]", " ", (text or "").lower()).split())
    n = words_to_numbers(re.sub(r"(?<!\d)\.|\.(?!\d)", " ", n))  # keep the dot only inside numbers like 1.5
    n = " ".join(n.split())
    total, spans = 0.0, []
    for m in _DURATION_PARTS.finditer(n):
        if m.group("mixed"):
            unit = _unit_seconds(m.group(2))
            total += (int(m.group("mixed")) + 0.5) * unit
        else:
            word = m.group("n")
            value = (0.5 if word.startswith("half") else 0.25 if word.startswith("quarter")
                     else 1 if word in ("a", "an") else float(word))
            unit = _unit_seconds(m.group(4))
            total += value * unit
            if m.group("plus"):
                total += 0.5 * unit
        spans.append(m.span())
    if not spans or total <= 0:
        return None, n
    rest, last = [], 0
    for a, b in spans:
        rest.append(n[last:a])
        last = b
    rest.append(n[last:])
    return int(round(total)), " ".join(" ".join(rest).replace(" and ", " ").split())


def format_duration(seconds: int, short: bool = False) -> str:
    seconds = int(max(0, round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not (short and h):
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) or "0 seconds"


def parse_timer_command(text: str, have_timers: bool = False):
    """Return {"action": "set"|"cancel"|"query"|"list", ...} or None."""
    n = " ".join(re.sub(r"[^a-z0-9.' ]", " ", (text or "").lower()).split())
    has_timer_word = bool(re.search(r"\b(timers?|countdown)\b", n))
    has_set_word = has_timer_word or bool(re.search(r"\balarm\b", n))
    seconds, rest = parse_duration(n)

    if has_timer_word and re.search(r"\b(cancel|stop|delete|remove|clear|dismiss|kill|turn off|end|forget)\b", n):
        return {"action": "cancel", "all": bool(re.search(r"\b(all|every|both)\b", n)),
                "label": re.sub(r"\b(cancel|stop|delete|remove|clear|dismiss|kill|turn off|end|forget|the|my|a|all|every|both|timers?|countdown|please)\b", " ", n).strip()}
    if (has_timer_word or have_timers) and re.search(
            r"\bhow (?:much )?(?:time|long)\b.*\b(left|remaining|remains|to go|on)\b|\btime (?:is )?(?:left|remaining)\b|\bcheck\b.*\btimer|\bhow(?:'s| is) the timer\b", n):
        return {"action": "query"}
    if has_timer_word and re.search(r"\b(what|which|list|show|any|do i have|how many)\b", n) and seconds is None:
        return {"action": "list"}
    if seconds is None:
        if has_set_word and re.search(r"\b(set|start|put|make|create|begin)\b", n):
            return {"action": "ask"}
        return None

    remind = re.search(r"\b(remind me|wake me up|wake me|tell me|let me know|ping me)\b", n)
    if not (has_set_word or remind):
        return None
    label, kind = "", "timer"
    if remind:
        kind = "reminder"
        m = re.search(r"\b(?:to|that|about)\s+(.+)$", rest)
        label = m.group(1) if m else ("wake up" if "wake" in remind.group(1) else "")
    else:
        m = (re.search(r"\b(?:called|named|labeled|label)\s+(?:the\s+|my\s+)?(.+)$", rest)
             or re.search(r"\b(?:for|to)\s+(?:the\s+|my\s+|a\s+)?(.+)$", rest))
        label = m.group(1) if m else ""
    if not remind:
        label = re.sub(r"\b(set|start|put|make|create|begin|please|a|an|the|timer|countdown|alarm|remind me|me|in|for|of|from now|and|on|jervis)\b", " ", label)
    label = " ".join(label.split())
    label = re.sub(r"^(?:in|for|after|within|at)\s+|\s+(?:in|for|after|within|at)$", "", label).strip()
    return {"action": "set", "seconds": seconds, "label": label, "kind": kind}


class TimerManager:
    """Keeps active timers, schedules their end, and survives restarts (timers.json)."""

    def __init__(self, on_fire, on_change=None):
        self._on_fire = on_fire
        self._on_change = on_change or (lambda timers: None)
        self._lock = threading.RLock()
        self._timers = {}
        self._threads = {}
        self._next_id = 1

    # ----- state -----
    def snapshot(self) -> list:
        with self._lock:
            return sorted((dict(t) for t in self._timers.values()), key=lambda t: t["end"])

    def _save(self) -> None:
        try:
            with open(_FILE, "w", encoding="utf-8") as f:
                json.dump({"next_id": self._next_id, "timers": list(self._timers.values())}, f)
        except OSError:
            pass

    def _changed(self) -> None:
        self._save()
        self._on_change(self.snapshot())

    def _schedule(self, timer: dict) -> None:
        delay = max(0.0, timer["end"] - time.time())
        thread = threading.Timer(delay, self._fire, args=(timer["id"],))
        thread.daemon = True
        self._threads[timer["id"]] = thread
        thread.start()

    def _fire(self, timer_id: int) -> None:
        with self._lock:
            timer = self._timers.pop(timer_id, None)
            self._threads.pop(timer_id, None)
        if timer:
            self._changed()
            self._on_fire(timer)

    # ----- actions -----
    def add(self, seconds: int, label: str = "", kind: str = "timer") -> dict:
        with self._lock:
            timer = {"id": self._next_id, "label": label, "kind": kind, "total": int(seconds),
                     "end": time.time() + int(seconds)}
            self._next_id += 1
            self._timers[timer["id"]] = timer
            self._schedule(timer)
        self._changed()
        return dict(timer)

    def cancel(self, label: str = "", everything: bool = False) -> list:
        with self._lock:
            if everything:
                victims = list(self._timers.values())
            else:
                matches = [t for t in self._timers.values() if label and label in t["label"]]
                pool = matches or sorted(self._timers.values(), key=lambda t: t["end"])
                victims = pool[:1]
            for t in victims:
                self._timers.pop(t["id"], None)
                thread = self._threads.pop(t["id"], None)
                if thread:
                    thread.cancel()
        if victims:
            self._changed()
        return [dict(t) for t in victims]

    def load(self) -> None:
        """Restore timers saved before Jervis was closed. Ones that ended meanwhile fire right away."""
        try:
            with open(_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        with self._lock:
            self._next_id = int(data.get("next_id", 1))
            for t in data.get("timers", []):
                self._timers[t["id"]] = t
                self._schedule(t)
        self._on_change(self.snapshot())
