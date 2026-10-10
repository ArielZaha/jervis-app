"""Typos people make when giving Jarvis orders, fixed before a command is read ("the distence between…", "drew the
greph", "30 seconeds"). Pure text in, text out: Jarvis on the computer (app.py) and the phone's own copy of his
brain (phone_brain.py) both start with it."""
import difflib
import re

# Words people mistype when giving orders ("take contorl"), matched loosely so a typo doesn't send a command to the AI.
_TYPO_TARGETS = ("control", "computer", "spotify", "search")


# Misspellings seen in real requests ("the distence between…", "drew the greph", "30 seconeds"): fixed exactly, word
# by word, so only these words change — a loose match would turn "plant" into "planet" or "instance" into "distance".
_MISSPELLINGS = {
    "distence": "distance", "distanse": "distance", "disstance": "distance", "distnace": "distance",
    "greph": "graph", "grapgh": "graph", "grahp": "graph", "garph": "graph", "graf": "graph", "graoh": "graph",
    "seconeds": "seconds", "secondes": "seconds", "secnds": "seconds", "seonds": "seconds", "secs": "seconds",
    "minuts": "minutes", "minuets": "minutes", "mintues": "minutes", "minuites": "minutes",
    "wrtie": "write", "wirte": "write", "writte": "write", "wrtite": "write",
    "calender": "calendar", "calandar": "calendar", "calander": "calendar", "calnder": "calendar",
    "trailor": "trailer", "trialer": "trailer", "traler": "trailer", "triler": "trailer",
    "netflex": "netflix", "netfilx": "netflix", "netflx": "netflix",
    "documnet": "document", "docuemnt": "document", "doucment": "document",
    "storie": "story", "stroy": "story", "sotry": "story",
    "planit": "planet", "plannet": "planet", "planent": "planet",
    "seturn": "saturn", "saturen": "saturn", "jupitor": "jupiter", "jupiler": "jupiter", "nepture": "neptune",
    "isreal": "israel", "isarel": "israel", "googel": "google", "gogle": "google",
    "genearte": "generate", "generete": "generate", "genrate": "generate", "gnerate": "generate", "genarate": "generate",
    "imgae": "image", "iamge": "image", "imag": "image", "pictuer": "picture", "picure": "picture", "pitcure": "picture",
    "evnet": "event", "evnt": "event", "meating": "meeting", "apointment": "appointment",
}
_MISSPELLED_PHRASES = [
    (re.compile(r"\btell my about\b", re.I), "tell me about"),
    (re.compile(r"\bshow my\b(?= (?:the|a|an|it|on|how)\b)", re.I), "show me"),
    (re.compile(r"\bdrew\b(?= (?:the|a|an|me|it|this|that|its|her|his|my)?\s*(?:graph|model|function|line|plot|chart|parabola|globe)\b)", re.I), "draw"),
]


def fix_typos(text: str) -> str:
    def fix(match):
        word = match.group(0)
        exact = _MISSPELLINGS.get(word.lower())
        if exact:
            return exact.capitalize() if word[:1].isupper() else exact
        if len(word) < 5 or word.lower() in _TYPO_TARGETS:
            return word
        close = difflib.get_close_matches(word.lower(), _TYPO_TARGETS, n=1, cutoff=0.8)
        return close[0] if close else word
    text = re.sub(r"[A-Za-z]+", fix, text or "")
    for pattern, replacement in _MISSPELLED_PHRASES:
        text = pattern.sub(replacement, text)
    return text
