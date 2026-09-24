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
        if i + 1 < len(words) and not _match(words[i]):
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
