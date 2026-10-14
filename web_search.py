"""Spoken web searches: "search Google for cats", "google cats", "search YouTube for Minecraft",
"look up the Eiffel Tower on Google".

Only sentences that name where to search count (Google, YouTube, "the web"), so ordinary talk like "I searched for my
keys" or "find me a good book" never opens a browser. app.py does the opening.
"""
import re
from urllib.parse import quote

_LEAD = (r"^(?:(?:hey |ok |okay )?(?:jarvis|jervis) )?(?:(?:please|can you|could you|would you|go ahead and|just|"
         r"i want you to|i want to|i need to) )*")
_ENGINE = r"(?P<engine>google|youtube|you tube|the web|the internet|online)"
_VERB = r"(?:search|look up|look for|find|search up)"
_PATTERNS = [
    # "search Google for cats", "search on YouTube for minecraft", "look up on google how to tie a tie"
    re.compile(_LEAD + _VERB + r" (?:on |in |using )?" + _ENGINE + r" (?:for |about )?(?P<q>.+)$"),
    # "search for cats on Google", "look up minecraft on youtube", "find lofi music on YouTube"
    re.compile(_LEAD + _VERB + r" (?:for |about )?(?P<q>.+?) (?:on|in|using|with) " + _ENGINE + r"$"),
    # "youtube search minecraft", "google search for the weather in Paris"
    re.compile(_LEAD + r"(?P<engine>google|youtube|you tube) search(?: for)? (?P<q>.+)$"),
    # "google cats" (Google as a verb), but not a sentence about Google ("Google is down", "Google said…")
    re.compile(_LEAD + r"(?P<engine>google) (?!(?:is|was|are|were|has|had|have|does|did|do|says|said|can|could|will|"
                       r"would|should|just|also|keeps|kept|made|makes|bought|owns|knows|took|gave|wants|needs|isn't|"
                       r"doesn't|didn't|won't|can't)\b)(?:for )?(?P<q>.+)$"),
]
# "Google Docs", "YouTube Music": products, not searches ("google classroom" is opened by the app/site commands).
_NOT_A_QUERY = {"docs", "doc", "drive", "classroom", "calendar", "maps", "meet", "photos", "sheets", "slides", "scholar",
                "chrome", "music", "studio", "kids", "translate", "earth", "keep", "forms", "news", "play", "home",
                "assistant", "account", "search", "it", "that", "this"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w'+#. -]", " ", (text or "").lower().replace("\u2019", "'")).split()).strip(" .")


def parse_request(text: str):
    """("google" | "youtube", query) for a spoken search request, else None."""
    n = _norm(text)
    for pattern in _PATTERNS:
        m = pattern.match(n)
        if not m:
            continue
        query = m.group("q").strip(" .?!")
        query = re.sub(r"^(?:for|about) ", "", query)
        query = re.sub(r" (?:please|for me|now)$", "", query).strip()
        if not query or query in _NOT_A_QUERY:
            return None
        engine = m.group("engine").replace(" ", "")
        return ("youtube" if engine == "youtube" else "google"), query
    return None


def youtube_results_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote(query)}"
