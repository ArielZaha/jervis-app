"""Pull a spoken position in a track or video out of a sentence: "minute two", "at 2:30", "1 minute 30 seconds"."""
import re

_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}
_NUM = r"(?:\d{1,3}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + ")"
_HALF = r"(?:and\s+)?(?:a\s+)?half"
_SECS = rf"(?:and\s+)?({_NUM})\s+seconds?"
_LEAD = re.compile(r"\b(?:(?:starting|start|begin|beginning)\s+)?(?:at|from|in|to|on|around)\s+(?:the\s+)?$")

_PATTERNS = [
    ("clock", re.compile(r"\b(\d{1,2}):(\d{2})\b")),
    ("minutes", re.compile(rf"\b({_NUM})\s+minutes?(?:\s+(?:{_HALF}|{_SECS}))?(?:\s+(?:in|into))?(?!\w)")),
    ("minute", re.compile(rf"\bminute\s+({_NUM})(?:\s+(?:{_HALF}|{_SECS}))?(?!\w)")),
    ("seconds", re.compile(rf"\b({_NUM})\s+seconds?\b")),
]


def _value(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token]


def format_time(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def parse_start_time(text: str):
    """Return (seconds, text_without_the_time_phrase), or (None, text) when no position was spoken."""
    n = " ".join(re.sub(r"[^a-z0-9': ]", " ", (text or "").lower()).split())
    for kind, pattern in _PATTERNS:
        m = pattern.search(n)
        if not m:
            continue
        if kind == "clock":
            seconds = int(m.group(1)) * 60 + int(m.group(2))
        elif kind == "seconds":
            seconds = _value(m.group(1))
        else:
            seconds = _value(m.group(1)) * 60
            tail = m.group(0)
            if re.search(r"\bhalf\b", tail):
                seconds += 30
            elif m.lastindex and m.lastindex >= 2 and m.group(2):
                seconds += _value(m.group(2))
        before = _LEAD.sub("", n[:m.start()]).strip()
        return seconds, " ".join((before + " " + n[m.end():]).split())
    return None, n
