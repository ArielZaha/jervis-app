"""Which Google account (Chrome profile) a page opens in: learning things use the school account, everything else the personal one.

Two accounts are set in the .env file:
    GOOGLE_ACCOUNT_LEARNING=school account   (school work: documents, Drive, Classroom, learning sites and videos)
    GOOGLE_ACCOUNT_PERSONAL=personal account (everything else: Gmail, Photos, trailers, Netflix, fun documents, ...)

Every page Jervis opens in the browser goes to the Chrome profile that has the right account, in a new tab for Google
documents and in the tab Jervis itself opened earlier (in that same profile) for sites like YouTube and Netflix, so an
open tab of the other account is never reused. Nothing is announced out loud: it just happens. Each decision is written
to logs/routing.log so a wrong choice can be explained and fixed.
"""
import os
import re
import time
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import chrome_profiles
import paths

# Google services where the account matters, and which account they use when nothing else says otherwise.
SERVICE_DEFAULT = {
    "docs.google.com": "learning", "drive.google.com": "learning", "classroom.google.com": "learning",
    "meet.google.com": "learning", "sites.google.com": "learning", "scholar.google.com": "learning",
    "mail.google.com": "personal", "calendar.google.com": "personal", "photos.google.com": "personal",
}
# Learning websites that are not Google's: always the school account.
LEARNING_HOSTS = ("khanacademy.org", "quizlet.com", "kahoot.it", "duolingo.com", "coursera.org", "edx.org", "wikipedia.org",
                  "desmos.com", "geogebra.org", "brainly.com", "britannica.com", "mathway.com", "wolframalpha.com")

_LEARNING = re.compile(
    r"\b(learn\w*|study\w*|homework|assignments?|essays?|reports?|projects?|lessons?|class|classes|classroom|school|"
    r"teachers?|professors?|tutors?|students?|lectures?|courses?|exams?|tests?|quiz\w*|midterm|university|college|"
    r"math\w*|algebra|geometry|calculus|trigonometry|statistics|physics|chemistry|biology|history|geography|science|"
    r"literature|english|hebrew|bible|civics|economics|philosophy|psychology|sociology|programming|coding|"
    r"grammar|vocabulary|flashcards?|research|thesis|education\w*|tutorials?|worksheets?|syllabus|curriculum|chapters?|"
    r"presentations?|grades?|semester|papers?|theory|analysis|experiments?|labs?|equations?|formulas?|revision|revise|"
    r"shakespeare|macbeth|hamlet|monologue|soliloquy|photosynthesis|revolution|ancient|explained|documentary|"
    r"ort|khan|quizlet|kahoot|coursera|duolingo)\b")
_PERSONAL = re.compile(
    r"\b(personal|gmail|fun|funny|stor(?:y|ies)|poems?|songs?|lyrics|jokes?|recipes?|shopping|groceries|grocery|birthday|"
    r"party|wedding|invitation|games?|gaming|movies?|films?|netflix|music|diary|journal|travel|trip|vacation|holiday|"
    r"gifts?|wishlist|budget|resume|cv|hobby|hobbies|workout|fitness|meme|memes|fantasy|dragons?|friends?|family|"
    r"trailers?|episodes?|seasons?|series|shows?|official|clips?|concert|live)\b")
_SAY_LEARNING = re.compile(r"\b(for school|school account|my school|for class|for homework|for study|for studying|learning account)\b")
_SAY_PERSONAL = re.compile(r"\b(personal account|my personal|my gmail|not for school|for fun|for myself|not learning)\b")

last_route = {"url": None, "context": "", "kind": None, "at": 0.0}  # what was opened last, for "wrong account"


def accounts() -> dict:
    """{"learning": email or "", "personal": email or ""} from the .env file (GOOGLE_ACCOUNT still works for learning)."""
    def clean(name):
        return (os.getenv(name) or "").strip().strip("\"'")
    return {"learning": clean("GOOGLE_ACCOUNT_LEARNING") or clean("GOOGLE_ACCOUNT"), "personal": clean("GOOGLE_ACCOUNT_PERSONAL")}


def configured() -> bool:
    return any(accounts().values())


def applies(host: str) -> bool:
    """True if this is a Google service where the account matters and some account is set."""
    return configured() and host.split("/")[0] in SERVICE_DEFAULT


def _text(context: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", (context or "").lower()).split())


def classify(host: str, context: str = "") -> str:
    """"learning" or "personal" for a page on `host`, given what the user said (words that hint at either)."""
    host = host.split("/")[0].lower()
    text = _text(context)
    if _SAY_PERSONAL.search(text):
        return "personal"
    if _SAY_LEARNING.search(text):
        return "learning"
    if any(host == h or host.endswith("." + h) for h in LEARNING_HOSTS):
        return "learning"
    score = len(_LEARNING.findall(text)) - len(_PERSONAL.findall(text))
    if score:
        return "learning" if score > 0 else "personal"
    if host in SERVICE_DEFAULT:
        return SERVICE_DEFAULT[host]
    return "personal"  # entertainment and everything else (YouTube, Netflix, ...) unless it sounds like school


def account_for(host: str, context: str = "", force_kind: str = "") -> str:
    """The account to use: the classified one, or the other one if that one isn't set. Empty if none is set."""
    chosen = accounts()
    kind = force_kind or classify(host, context)
    return chosen[kind] or chosen["personal" if kind == "learning" else "learning"]


def kind_of_account(account: str) -> str:
    return "learning" if account and account == accounts()["learning"] else "personal"


def with_account(url: str, account: str) -> str:
    """Add ?authuser=<account> to an address, replacing any authuser already there."""
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "authuser"]
    return urlunparse(parsed._replace(query=urlencode([("authuser", account)] + query, quote_via=quote)))


def log_route(kind: str, account: str, profile, url: str, context: str, how: str) -> None:
    """Record every decision (logs/routing.log), so "it opened in the wrong account" can be explained afterwards."""
    global last_route
    last_route = {"url": url, "context": context, "kind": kind, "at": time.time()}
    try:
        folder = paths.logs_dir()
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "routing.log"), "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {kind:8} profile={profile} via={how:7} {urlparse(url).netloc} | said: {(context or '')[:120]!r}\n")
    except OSError:
        pass
    print(f"[browser] {urlparse(url).netloc} -> {kind} account ({profile or 'no profile'}, {how})", flush=True)


def open_page(url: str, context: str = "", force_kind: str = "") -> str:
    """Open a Google Docs / Sheets / Slides / Drive / Mail page in a NEW tab under the right account.

    1. In the Chrome profile that has the account (a page opened in another profile would use that profile's account).
    2. If no Chrome profile has it: Google's account chooser, which asks for THAT account and never silently uses another.
    3. No account configured for this page: opened as before.
    Returns "profile", "chooser" or "default".
    """
    from youtube_browser import open_youtube
    host = urlparse(url).netloc
    account = account_for(host, context, force_kind) if configured() and host in SERVICE_DEFAULT else ""
    if not account:
        open_youtube(url, new_tab=True, routed=False)
        return "default"
    kind = kind_of_account(account)
    target = with_account(url, account)
    profile = chrome_profiles.find_profile(account)
    if profile and chrome_profiles.open_and_show(target, profile, host):
        log_route(kind, account, profile, url, context, "profile")
        return "profile"
    open_youtube(f"https://accounts.google.com/AccountChooser?Email={quote(account)}&continue={quote(target, safe='')}",
                 new_tab=True, routed=False)
    log_route(kind, account, None, url, context, "chooser")
    return "chooser"


def route(url: str, new_tab: bool = False, context: str = "", force_kind: str = "") -> bool:
    """Open any web page in the Chrome profile of the right account. Returns False if this page isn't routed (then the
    caller opens it the normal way).

    Sites like YouTube and Netflix keep using ONE tab: the one Jervis opened earlier in that same profile.
    """
    if not configured():
        return False
    host = urlparse(url).netloc
    if not host or host.startswith("accounts.google.com"):
        return False
    if host in SERVICE_DEFAULT:
        open_page(url, context, force_kind)
        return True
    account = account_for(host, context, force_kind)
    profile = chrome_profiles.find_profile(account) if account else None
    if not profile:
        return False
    kind = kind_of_account(account)
    if not new_tab and chrome_profiles.reuse_tab(profile, host, url):
        log_route(kind, account, profile, url, context, "same tab")
        return True
    if not chrome_profiles.open_and_show(url, profile, host, remember=True):
        return False
    log_route(kind, account, profile, url, context, "new tab")
    return True


def reopen_elsewhere(kind: str = "") -> str:
    """"Wrong account": open the last page again under the other account (or the one asked for)."""
    if not last_route["url"] or time.time() - last_route["at"] > 20 * 60:
        return "I don't have anything to move."
    target_kind = kind or ("personal" if last_route["kind"] == "learning" else "learning")
    if not accounts()[target_kind]:
        return "I don't have that account set up."
    route(last_route["url"], new_tab=True, context=last_route["context"], force_kind=target_kind)
    return "Done."
