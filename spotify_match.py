"""Which Spotify result the user meant — decided here, by rules, never by a language model.

A request ("סוזי תזוזי", "suzi tazozi", "static and ben al", "Echoes by Pink Floyd", "the Discover Weekly playlist")
becomes an intent (title, artist, kind); the intent becomes a few searches (as said; the same in the other script,
for Hebrew songs written in English letters or English names written in Hebrew; artist with title); and every result
Spotify returns is scored against the intent: title and artist similarity in their own script, in a cross-script
sound key (so "Ben El" is "בן אל" and "Tazuzi" is "תזוזי"), word overlap, what kind of item it is, and where Spotify
ranked it. The best one is played — by its exact URI — or, when nothing comes close, nothing is.

Pure Python: spotify_local.py reads the results out of the Spotify app; app.py uses the Web API when the user has
keys. Both hand their results here."""
import re
import unicodedata
from difflib import SequenceMatcher

HEBREW = re.compile(r"[א-ת]")
_NIQQUD = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
# what a title carries that the user never says: "(feat. X)", "- Remastered 2011", "(Live)", "[Radio Edit]"
_EXTRA = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+-\s+(?:.*\b(?:remaster\w*|live|version|edit|mix|remix|mono|stereo|"
                    r"acoustic|radio|single|from)\b.*)$", re.I)
_KIND_WORDS = {"playlist": "playlist", "פלייליסט": "playlist", "רשימת השמעה": "playlist", "album": "album",
               "אלבום": "album", "artist": "artist", "אמן": "artist", "זמר": "artist", "זמרת": "artist",
               "podcast": "show", "פודקאסט": "show", "song": "track", "track": "track", "שיר": "track",
               "השיר": "track", "songs": "artist", "שירים": "artist", "music": None, "מוזיקה": None}

# Hebrew letters -> Latin, the way Israeli song titles are written in English letters
_HE_LATIN = {"א": "", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "o", "ז": "z", "ח": "ch", "ט": "t", "י": "i",
             "כ": "ch", "ל": "l", "מ": "m", "נ": "n", "ס": "s", "ע": "", "פ": "f", "צ": "tz", "ק": "k", "ר": "r",
             "ש": "sh", "ת": "t"}
# and back: a Hebrew title spelled in English letters ("suzi tazozi", "kapit achat shel tov") -> Hebrew letters
_LATIN_HE = [("sh", "ש"), ("ch", "ח"), ("kh", "ח"), ("tz", "צ"), ("ts", "צ"), ("th", "ת"), ("ph", "פ"),
             ("oo", "ו"), ("ee", "י"), ("ei", "יי"), ("ai", "יי"), ("ay", "יי"), ("oy", "וי"),
             ("b", "ב"), ("v", "ב"), ("w", "ו"), ("g", "ג"), ("j", "ג'"), ("d", "ד"), ("h", "ה"), ("z", "ז"),
             ("t", "ת"), ("y", "י"), ("k", "ק"), ("c", "ק"), ("q", "ק"), ("x", "קס"), ("l", "ל"), ("m", "מ"),
             ("n", "נ"), ("s", "ס"), ("f", "פ"), ("p", "פ"), ("r", "ר"), ("o", "ו"), ("u", "ו"), ("i", "י"),
             ("e", ""), ("a", "")]
_HE_FINAL = {"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"}

# the cross-script sound key: consonants by how they sound, vowels and silent letters dropped
_KEY_HE = {"ב": "B", "ג": "G", "ד": "D", "ז": "Z", "ח": "K", "ט": "T", "כ": "K", "ל": "L", "מ": "M", "נ": "N",
           "ס": "S", "פ": "P", "צ": "C", "ק": "K", "ר": "R", "ש": "S", "ת": "T"}
_KEY_LATIN = [("sch", "S"), ("sh", "S"), ("ch", "K"), ("kh", "K"), ("ck", "K"), ("tz", "C"), ("ts", "C"),
              ("ph", "P"), ("th", "T"), ("b", "B"), ("v", "B"), ("g", "G"), ("j", "G"), ("d", "D"), ("z", "Z"),
              ("k", "K"), ("q", "K"), ("x", "KS"), ("c", "K"), ("l", "L"), ("m", "M"), ("n", "N"), ("s", "S"),
              ("p", "P"), ("f", "P"), ("r", "R"), ("t", "T")]


# ---------- text, made comparable ----------

def normalize(text: str) -> str:
    """Lower case, no niqqud, Hebrew final letters as the usual ones, '&' as 'and', no "(feat. ...)" or
    "- Remastered", punctuation gone, spaces single."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = _EXTRA.sub("", t)
    t = _NIQQUD.sub("", t).translate(_FINALS).lower()
    t = t.replace("&", " and ").replace("+", " and ")
    t = re.sub(r"[^\wא-ת]+", " ", t)
    return " ".join(t.split())


def sound_key(text: str) -> str:
    """'Ben El' and 'בן אל' -> 'BN L'; 'Suzi Tazuzi' and 'סוזי תזוזי' -> 'SZ TZZ'. Word by word."""
    words = []
    for w in normalize(text).split():
        out = []
        if HEBREW.search(w):
            for ch in w:
                out.append(_KEY_HE.get(ch, ""))
        else:
            i = 0
            while i < len(w):
                for src, dst in _KEY_LATIN:
                    if w.startswith(src, i):
                        out.append(dst)
                        i += len(src)
                        break
                else:
                    if w[i].isdigit():
                        out.append(w[i])
                    i += 1
        key = re.sub(r"(.)\1+", r"\1", "".join(out))   # doubled sounds are one
        if key:
            words.append(key)
    return " ".join(words)


def to_latin(text: str) -> str:
    """Hebrew letters in English letters, the usual way ("סוזי תזוזי" -> "suzi tazuzi"-ish): a second way to search
    for a Hebrew song whose English title is in Latin letters."""
    out = []
    for w in normalize(text).split():
        if not HEBREW.search(w):
            out.append(w)
            continue
        s = ""
        for i, ch in enumerate(w):
            lat = _HE_LATIN.get(ch, ch)
            if ch == "ו":
                lat = "v" if i == 0 else ("o" if i < len(w) - 1 else "o")
            elif ch == "י":
                lat = "y" if i == 0 else "i"
            elif ch == "ה" and i == len(w) - 1:
                lat = "a"
            elif ch == "ב" and i > 0:
                lat = "v"
            elif ch == "כ" and i == 0:
                lat = "k"
            elif ch == "פ" and i == 0:
                lat = "p"
            # two consonants together at the start of a word are usually said with an 'a' between them
            if s and i == 1 and ch not in "וי" and w[0] not in "אהועי" and lat:
                s += "a"
            s += lat
        out.append(s)
    return " ".join(out)


def to_hebrew(text: str) -> str:
    """English letters in Hebrew ones ("suzi tazozi" -> "סוזי תזוזי"): a Hebrew song typed or heard in English
    letters, searched for the way it's really written. Rough by nature; the ranking decides what's right."""
    out = []
    for w in normalize(text).split():
        if HEBREW.search(w) or w.isdigit():
            out.append(w)
            continue
        s, i = "", 0
        while i < len(w):
            for src, dst in _LATIN_HE:
                if w.startswith(src, i):
                    if src in ("a", "e") and i == 0:
                        dst = "א"
                    elif src == "a" and i == len(w) - 1:
                        dst = "ה"
                    s += dst
                    i += len(src)
                    break
            else:
                i += 1
        if s and s[-1] in _HE_FINAL:
            s = s[:-1] + _HE_FINAL[s[-1]]
        if s:
            out.append(s)
    return " ".join(out)


def similarity(a: str, b: str) -> float:
    """0..1: the same words (in any order), the same text, or the same sound across scripts."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    text = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    words = len(ta & tb) / max(len(ta), len(tb))
    ka, kb = sound_key(a), sound_key(b)
    sound = SequenceMatcher(None, ka, kb).ratio() if ka and kb else 0.0
    if ka and kb and ka == kb:
        sound = 1.0
    kwa, kwb = set(ka.split()), set(kb.split())
    sound_words = len(kwa & kwb) / max(len(kwa), len(kwb)) if kwa and kwb else 0.0
    # one contained in the other ("echoes" in "echoes - 2011 remaster"): nearly the same title
    short, long_ = sorted((na, nb), key=len)
    # (scaled by how much of the longer one it is: "זוזי" is in "סוזי תזוזי" but isn't that song)
    contained = 0.9 * (len(short) / len(long_)) ** 0.5 if short in long_ and len(short) >= 4 else 0.0
    return max(text, words, 0.92 * sound, 0.88 * sound_words, contained)


# ---------- what was asked for ----------

def parse(query: str) -> dict:
    """{"text", "title", "artist", "kind"}: "Echoes by Pink Floyd" -> title Echoes, artist Pink Floyd;
    "סוזי תזוזי של כפיר עטיה" -> title and artist; "the Chill Vibes playlist" -> kind playlist."""
    text = " ".join(str(query or "").replace("“", '"').replace("”", '"').replace("״", '"').split())
    text = text.strip(" \"'.,!?")
    kind = None
    for word, k in sorted(_KIND_WORDS.items(), key=lambda kv: -len(kv[0])):
        pattern = rf"(?<![\wא-ת])(?:the\s+|ה)?{re.escape(word)}(?![\wא-ת])"
        if kind is None and re.search(pattern, text, re.I):   # (only the word that says what kind: "all songs"
            kind = k                                           # in a playlist's name stays its name)
            text = re.sub(pattern, " ", text, count=1, flags=re.I)
    text = " ".join(text.split()).strip(" ,-\"'")
    text = re.sub(r"^(?:the|my|our|some)\s+", "", text, flags=re.I)
    title, artist = text.replace('"', ""), None
    m = re.match(r"^(?P<t>.+?)\s+(?:by|from)\s+(?P<a>.+)$", text, re.I) or \
        re.match(r"^(?P<t>.+?)\s+(?:של|מאת)\s+(?P<a>.+)$", text)
    if m:
        title, artist = m.group("t").strip(" \"'"), m.group("a").strip(" \"'")
    q = re.match(r'^"(?P<t>[^"]+)"\s+(?P<a>.+)$', str(query or "").strip()) or \
        re.match(r'^(?P<a>[^"]+?)\s+"(?P<t>[^"]+)"$', str(query or "").strip())
    if q and not m:   # 'Static and Ben El "Suzi Tazuzi"': what's quoted is the title
        title, artist = q.group("t").strip(), q.group("a").strip()
    text = " ".join(text.replace('"', " ").split())
    if kind == "artist" and artist is None:
        title, artist = None, text
    return {"text": text, "title": title or None, "artist": artist, "kind": kind}


def _looks_english(text: str) -> bool:
    """Real English words ("static and ben el", "echoes"), not a Hebrew title in English letters ("suzi tazozi")."""
    words = [w for w in re.findall(r"[a-z]{2,}", normalize(text))]
    if not words:
        return True
    try:
        import language
        if not language._is_english_word("zzqxv"):   # (without its dictionary every word passes: no telling)
            return known_words(words, language) >= max(1, len(words) * 0.75)
    except Exception:
        pass
    return False


def known_words(words, language) -> int:
    return sum(1 for w in words if language._is_english_word(w))


def queries(intent: dict, limit: int = 4) -> list:
    """The searches to run, best first — the caller stops at the first that finds a confident match: as said; artist
    with title; the same in the other script (a Hebrew song typed in English letters is searched in Hebrew, a
    Hebrew one also in English letters) — after the rest when the words look like plain English. No duplicates."""
    text, title, artist = intent["text"], intent.get("title"), intent.get("artist")
    out, late = [text], []
    if artist and title:
        out.append(f"{artist} {title}")
    for t in [title or text] + ([text] if title and title != text else []):
        if HEBREW.search(t):
            out.append(to_latin(t))
            if artist and not HEBREW.search(artist):
                out.append(f"{artist} {to_latin(t)}")
        elif re.search(r"[a-z]", t, re.I):
            (late if _looks_english(t) else out).append(to_hebrew(t))
    seen, result = set(), []
    for q in out + late:
        k = normalize(q)
        if k and k not in seen:
            seen.add(k)
            result.append(q)
    return result[:limit]


# ---------- which result ----------

def score(intent: dict, cand: dict) -> float:
    """How well one result (kind, title, artists, position) fits the request, 0..1+."""
    title = cand.get("title") or ""
    artists = [a for a in cand.get("artists") or [] if a]
    kind = cand.get("kind") or "track"
    wanted = intent.get("kind")
    text = intent["text"]
    artist_sim = max([similarity(intent["artist"], a) for a in artists] +
                     ([similarity(intent["artist"], " and ".join(artists))] if artists else []) +
                     ([similarity(intent["artist"], title)] if kind == "artist" else []) + [0.0]) \
        if intent.get("artist") else 0.0
    if kind == "artist":
        name_sim = similarity(intent.get("artist") or text, title)
        s = name_sim * (1.0 if wanted == "artist" else 0.94)
        if intent.get("title") and intent.get("artist") and wanted != "artist":
            s *= 0.75   # a song was asked for: its artist's page is second best
    elif intent.get("artist") and intent.get("title"):
        t = similarity(intent["title"], title)
        s = 0.62 * t + 0.38 * artist_sim
        if artist_sim < 0.5:
            s -= 0.18   # the artist was named: someone else's song isn't it, however close its title
    else:
        # just words: a title, an artist, or both run together ("static and ben el suzi tazuzi")
        whole = " ".join([title] + artists)
        s = max(similarity(text, title), 0.97 * similarity(text, whole),
                0.97 * similarity(text, " ".join(artists + [title])),
                0.8 * max([similarity(text, a) for a in artists] or [0.0]))
    if wanted and wanted == kind:
        s += 0.08
    elif wanted in ("playlist", "album", "show") and kind != wanted:
        s -= 0.2
    elif not wanted:
        s += {"track": 0.05, "artist": 0.0, "album": -0.06, "playlist": -0.14, "show": -0.2, "episode": -0.2,
              "user": -0.4, "genre": -0.3}.get(kind, -0.1)
    pos = cand.get("position")
    if isinstance(pos, int):
        s += 0.04 * max(0.0, 1.0 - pos / 8.0)   # Spotify's own relevance and popularity, a little
    return round(s, 4)


CONFIDENT = 0.72   # play it
PLAUSIBLE = 0.5    # play it, saying it's the closest match


def choose(intent: dict, candidates: list) -> dict:
    """{"best", "score", "verdict": "confident" | "plausible" | "none", "ranked": [(score, cand)...]} — the same
    item (same URI) found by several searches counts once, at its best."""
    best_by_uri = {}
    for c in candidates:
        if not c.get("uri"):
            continue
        sc = score(intent, c)
        if c["uri"] not in best_by_uri or sc > best_by_uri[c["uri"]][0]:
            best_by_uri[c["uri"]] = (sc, c)
    ranked = sorted(best_by_uri.values(), key=lambda p: -p[0])
    if not ranked:
        return {"best": None, "score": 0.0, "verdict": "none", "ranked": []}
    top, cand = ranked[0]
    verdict = "confident" if top >= CONFIDENT else "plausible" if top >= PLAUSIBLE else "none"
    return {"best": cand, "score": top, "verdict": verdict, "ranked": ranked}


def settled(intent: dict, pick: dict) -> bool:
    """Stop searching: the best so far is confidently what was asked — a song or an artist, unless an album, a
    playlist or a show was asked for (Spotify plays an album shuffled for a free account: "suzi tazozi" started
    another song of its album, while its track was one more search away)."""
    best = pick.get("best") or {}
    return pick.get("verdict") == "confident" and (bool(intent.get("kind")) or best.get("kind") in ("track", "artist"))


def describe(cand: dict) -> str:
    """'"Echoes" by Pink Floyd' / 'the playlist "Chill Vibes"' / 'Static & Ben El' — as Spotify names it."""
    title, artists, kind = cand.get("title") or "", cand.get("artists") or [], cand.get("kind") or "track"
    if kind == "artist":
        return title
    if kind in ("playlist", "album", "show"):
        return f'the {"podcast" if kind == "show" else kind} "{title}"' + (f" by {', '.join(artists)}" if artists
                                                                            and kind == "album" else "")
    return f'"{title}"' + (f" by {' and '.join(artists[:2])}" if artists else "")


def uri_of(url: str):
    """'https://xpui.app.spotify.com/track/7tJS...' or 'https://open.spotify.com/track/7tJS...?si=..' ->
    ('track', 'spotify:track:7tJS...'); None for anything else."""
    m = re.search(r"/(track|album|playlist|artist|show|episode|user|genre)/([A-Za-z0-9]+)", url or "")
    if not m:
        return None
    return m.group(1), f"spotify:{m.group(1)}:{m.group(2)}"
