"""Find a show on Netflix by name and open it in the browser.

Netflix has no public search API, so the title id is looked up through a web
search restricted to netflix.com/title. Opening /watch/<id> starts playback
(you must already be signed in to Netflix in Chrome).
"""
import html
import json
import os
import re
from urllib.parse import quote, unquote

import requests
import paths

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
_TITLE_URL = re.compile(r"netflix\.com/(?:[a-z-]+/)?title/(\d+)")
_ANCHOR = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S)
_ENDPOINTS = ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/")
_CACHE_FILE = os.path.join(paths.DATA_DIR, "netflix_cache.json")


def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _parse(page: str):
    for href, label in _ANCHOR.findall(page):
        m = _TITLE_URL.search(unquote(href))
        if not m:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        if re.match(r"watch this\b", name, re.I):  # a clip, not the show itself
            continue
        name = re.sub(r"^Watch\s+", "", name, flags=re.I)
        name = re.split(r"\s+[|\-–]\s+Netflix", name)[0].strip()
        return m.group(1), name
    return None


_WIKIDATA = "https://www.wikidata.org/w/api.php"
_WIKIDATA_HEADERS = {"User-Agent": "JervisAssistant/1.0 (personal voice assistant)"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


def resembles(asked: str, found: str) -> bool:
    """True if a search result plausibly IS what was asked for: same words, or very close spelling."""
    import difflib
    a, b = _norm(asked), _norm(found)
    if not a or not b:
        return False
    return (a == b or b.startswith(a) or a.startswith(b) or set(a.split()) <= set(b.split())
            or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


def _from_wikidata(query: str):
    """Wikidata records Netflix title ids (property P1874) for most shows and films."""
    try:
        hits = requests.get(_WIKIDATA, params={
            "action": "wbsearchentities", "search": query, "language": "en",
            "type": "item", "limit": 15, "format": "json"}, headers=_WIKIDATA_HEADERS, timeout=10).json().get("search", [])
        ids = [h["id"] for h in hits]
        if not ids:
            return None
        entities = requests.get(_WIKIDATA, params={
            "action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels",
            "languages": "en", "format": "json"}, headers=_WIKIDATA_HEADERS, timeout=10).json().get("entities", {})
    except (requests.RequestException, ValueError):
        return None
    wanted, best, best_score = _norm(query), None, -1
    for rank, wid in enumerate(ids):
        entity = entities.get(wid, {})
        netflix_ids = [c["mainsnak"]["datavalue"]["value"] for c in entity.get("claims", {}).get("P1874", [])
                       if "datavalue" in c.get("mainsnak", {})]
        if not netflix_ids:
            continue
        label = entity.get("labels", {}).get("en", {}).get("value") or query
        name = _norm(label)
        if not resembles(query, label):  # never accept a match that has nothing to do with what was asked
            continue
        # Exact name beats prefix beats alias match; search rank breaks ties.
        score = (3 if name == wanted else 2 if name.startswith(wanted) else 1) * 20 - rank
        if score > best_score:
            best, best_score = (netflix_ids[0], label), score
    return best


def _from_web_search(query: str):
    for endpoint in _ENDPOINTS:
        try:
            resp = requests.post(endpoint, data={"q": f"site:netflix.com/title {query}"}, headers=_HEADERS, timeout=10)
        except requests.RequestException:
            continue
        found = _parse(resp.text) if resp.status_code == 200 else None
        if found:
            return found[0], found[1] or query
    return None


def find_title(query: str):
    """Return (title_id, title) for the best Netflix match, or None. Results are cached on disk."""
    key = " ".join(query.lower().split())
    cache = _load_cache()
    if key in cache and resembles(query, cache[key][1]):  # a wrong match saved earlier is discarded, not trusted forever
        return tuple(cache[key])
    found = _from_wikidata(query) or _from_web_search(query)
    if found and not resembles(query, found[1]):
        found = None
    if found:
        cache[key] = list(found)
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1)
        except OSError:
            pass
    return found


def search_url(query: str) -> str:
    return f"https://www.netflix.com/search?q={quote(query)}"


def title_url(title_id: str) -> str:
    """The title's own page: it shows the trailer at the top (and the play button)."""
    return f"https://www.netflix.com/title/{title_id}"


def watch_url(title_id: str) -> str:
    return f"https://www.netflix.com/watch/{title_id}"


# ---------- Episodes ----------
# Netflix's public title page lists each season's episodes with their watch ids (about the first ten per
# season). Ids run consecutively inside a season, so later episodes are worked out from the first one.
_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
}
_SEASON_NODE = re.compile(r'"Season:\{\\+"videoId\\+":(\d+)\}":\{"__typename":"Season"')
_EPISODE_REF = re.compile(r'Episode:\{\\+"videoId\\+":(\d+)\}')


def _episode_titles(page: str) -> dict:
    return {i: html.unescape(t.replace("\\'", "'")) for i, t in
            re.findall(r'"__typename":"Episode","videoId":(\d+),"title":"(.*?)"', page)}


def _parse_seasons(page: str) -> list:
    """Return [(season_number, [episode ids])] in page order."""
    seasons = []
    for index, m in enumerate(_SEASON_NODE.finditer(page)):
        seg = page[m.end(): m.end() + 400000]
        nxt = seg.find('"Season:{')
        seg = seg[:nxt] if nxt > 0 else seg
        label = re.search(r'"title":"([^"]*)"', seg)
        number = re.search(r"(\d+)\s*$", label.group(1)) if label else None
        start = seg.find('"edges":[')
        ids = []
        if start >= 0:
            depth = 0
            for j in range(start + 8, len(seg)):
                if seg[j] == "[":
                    depth += 1
                elif seg[j] == "]":
                    depth -= 1
                    if depth == 0:
                        ids = _EPISODE_REF.findall(seg[start:j + 1])
                        break
        seasons.append((int(number.group(1)) if number else index + 1, ids))
    return seasons


def find_episode(series_id: str, season: int, episode: int):
    """Return (episode_watch_id, episode_title) or None if Netflix has no such episode."""
    season = season or 1
    episode = episode or 1
    try:
        page = requests.get(f"https://www.netflix.com/title/{series_id}", headers=_PAGE_HEADERS, timeout=15).text
    except requests.RequestException:
        return None
    seasons = _parse_seasons(page)
    titles = _episode_titles(page)
    numbers = [n for n, _ in seasons]
    if season not in numbers:
        return None
    ids = dict(seasons)[season]
    if not ids:
        return None
    if episode <= len(ids):
        ep_id = ids[episode - 1]
    else:
        ep_id = str(int(ids[0]) + episode - 1)  # consecutive ids within a season
        later = [int(v[0]) for n, v in seasons if n > season and v]
        if later and int(ep_id) >= min(later):  # would run into the next season: there is no such episode
            return None
    return ep_id, titles.get(ep_id, "")


# ---------- Trailers ----------
# A show's public Netflix page lists its trailers, each a video with its own id that plays in Netflix's normal player.
_EXTRA = re.compile(r'"videoId":(\d+),"title":"((?:[^"\\]|\\.)*)","runtimeSec":(\d+),"type":"([A-Z_]+)"')
_trailer_cache = {}


def find_trailers(title_id: str) -> list:
    """The show's trailers, in Netflix's order: [{"id", "title", "seconds"}]. Empty if Netflix lists none."""
    if title_id in _trailer_cache:
        return _trailer_cache[title_id]
    try:
        page = requests.get(f"https://www.netflix.com/title/{title_id}", headers=_PAGE_HEADERS, timeout=20).text
    except requests.RequestException:
        return []
    trailers, seen = [], set()
    for video_id, raw_title, seconds, kind in _EXTRA.findall(page):
        if kind not in ("TRAILER", "TEASER", "TEASER_TRAILER") or video_id in seen:
            continue
        seen.add(video_id)
        title = html.unescape(raw_title.replace("\\x20", " ").replace("\\'", "'").replace('\\"', '"'))
        trailers.append({"id": video_id, "title": title, "seconds": int(seconds)})
    _trailer_cache[title_id] = trailers
    return trailers


def pick_trailer(trailers: list, hint: str = ""):
    """The trailer to play: the one for a season/part the user named, else the main ("Franchise") trailer, else the first."""
    if not trailers:
        return None
    wanted = re.search(r"\b(?:season|part|series)\s+(\d+)\b", (hint or "").lower())
    if wanted:
        number = wanted.group(1)
        for trailer in trailers:
            if re.search(rf"\b(?:season|part|series)\s*{number}\b", trailer["title"].lower()):
                return trailer
    for trailer in trailers:
        if "franchise" in trailer["title"].lower() or "official" in trailer["title"].lower():
            return trailer
    return trailers[0]
