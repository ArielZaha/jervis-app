"""Repair speech-recognition mishearings of the names Jervis has to understand.

Recognizers turn "Stremio" into "Streamio", "Stream here", "Freemio", "Thremial"
and so on. Fixing them before any command parsing keeps every downstream parser
simple: they only ever see the canonical spelling.
"""
import difflib
import re

# name -> (fuzzy cutoff, known mishearings that are too far from the name for a similarity match)
NAMES = {
    "stremio": (0.78, {"freemio", "thremial", "thremio", "instrimio", "stremial", "streamial", "streamyo",
                       "streamyou", "stremmio", "stremi", "streamyo", "stremeo", "streemeo"}),
    "netflix": (0.8, {"netflicks", "netflex", "nettlix", "netflis"}),
    "youtube": (0.85, {"utube", "youtub", "yootube"}),
    "blender": (0.78, {"blingdon", "blendor", "blenda", "blendr", "blendah", "blenders", "blinder", "blendever"}),
    "spotify": (0.8, {"spotifi", "spotafy", "spotfy", "spotifye", "spottify"}),
}
# "stream" is a real word, so it only becomes Stremio when followed by a typical mishearing of "-io".
_STREAM_PAIR = re.compile(r"\bstream (?:here|hear|io|you|yo|me o|mio|e o|ear|ee o)\b")
_OPEN_STREAM = re.compile(r"\b(open|launch|start)\s+stream(?=\s+(?:and|then)\b|$)")
_ON_STREAM = re.compile(r"\b(on|in|with|using)\s+stream$")
_GLUED_VERB = re.compile(r"\b(open|launch|play|watch)(?=(?:stream|strem|strim|netflix|youtube))")


def _match(candidate: str):
    if len(candidate) < 5:
        return None
    for name, (cutoff, aliases) in NAMES.items():
        if candidate == name:
            return name
        if candidate in aliases:
            return name
        if difflib.SequenceMatcher(None, candidate, name).ratio() >= cutoff:
            return name
    return None


def _closeness(candidate: str) -> float:
    """How close `candidate` is to the name it matches (1.0 = exact or a known mishearing; 0 = no match)."""
    name = _match(candidate)
    if not name:
        return 0.0
    if candidate == name or candidate in NAMES[name][1]:
        return 1.0
    return difflib.SequenceMatcher(None, candidate, name).ratio()


def fix_names(text: str) -> str:
    """Return the text lower-cased, without punctuation, with service names spelled correctly."""
    low = " ".join(w.strip(":") for w in re.findall(r"[\w':]+", (text or "").lower()))  # keep "2:30"
    low = _GLUED_VERB.sub(r"\1 ", low)
    low = _STREAM_PAIR.sub("stremio", low)
    low = _OPEN_STREAM.sub(r"\1 stremio", low)
    low = _ON_STREAM.sub(r"\1 stremio", low)

    words, out, i = low.split(), [], 0
    while i < len(words):
        # Two words that were really one ("you tube", "net flicks", "stream io").
        # Also when the first word alone is a weaker match: "blend ever" is "blender", not "blender ever".
        if i + 1 < len(words) and _closeness(words[i] + words[i + 1]) > _closeness(words[i]):
            joined = _match(words[i] + words[i + 1])
            if joined and len(words[i]) >= 3 and len(words[i + 1]) >= 2 and words[i] not in {"the", "and", "in", "on"}:
                out.append(joined)
                i += 2
                continue
        out.append(_match(words[i]) or words[i])
        i += 1
    fixed = " ".join(out)
    fixed = re.sub(r"\b(?:whats ?app|whatsap|watsapp|what's app|whats up app|what's up app|whatsup app)\b", "whatsapp", fixed)
    if re.search(r"\b(stremio|netflix)\b", fixed):
        fixed = re.sub(r"\bplayhouse\b", "play house", fixed)  # "play House" is heard as one word
    return fixed


# ---------- Jervis's own name ----------
# Speech recognition rarely gets "Jervis" right: Jarvis, Gravis, Gervis, Jervais, Travis... After a greeting ("hey
# Gravis", "okay Gervis") or as the first word with a pause after it ("Gravis, open Spotify") it's the name — but never
# on its own inside a sentence, where "service", "nervous" or a friend called Travis are just words.
_NAME_HEARD = (r"(?:jervis|jarvis|gravis|gervis|gervais|jervais|jervus|jarvus|jarves|jervas|jarvas|travis|chervis|"
               r"jervies|jarvie|jervy|jarvi|gerbis|jervice|javis|jervish|jarvish|jervist|service|nervous|purvis|"
               r"garvis|jarvys)")
_GREETED_NAME = re.compile(rf"\b(?P<greeting>hey|hi|hello|ok|okay|wake up|yo)\s*[,.!]?\s+{_NAME_HEARD}\b", re.I)
_LEADING_NAME = re.compile(rf"^{_NAME_HEARD}\s*[,!.]\s*", re.I)


def fix_wake_name(text: str) -> str:
    """"Hey Gravis, make it red" -> "hey jervis, make it red"; "Gravis, open Spotify" -> "jervis, open Spotify"."""
    fixed = _GREETED_NAME.sub(lambda m: f"{m.group('greeting')} jervis", text or "")
    return _LEADING_NAME.sub("jervis, ", fixed)


# ---------- a sentence cut off by a pause ----------
# "Make the roof..." (a breath) "...green": a phrase that ends on a word a sentence can't end with is waited on.
_DANGLING = re.compile(r"\b(?:and|or|but|the|a|an|to|of|with|for|in|on|at|from|into|onto|then|so|because|like|"
                       r"make|put|move|turn|set|change|add|create|open|play|is|are|its|it's|my|your|this|that|um+|uh+|"
                       r"er+|hmm+)\s*[,.]*$", re.I)


def sounds_unfinished(text: str) -> bool:
    words = (text or "").split()
    return len(words) >= 2 and bool(_DANGLING.search(text or ""))
