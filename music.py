"""Music the user asks for by name, wherever they want it: "play my Workout playlist", "play the album OK Computer
on Apple Music", "shuffle my liked songs", "put on a lofi playlist on YouTube".

This module understands the request (what kind of thing, which service, shuffle, "my") and does the parts that
don't need Jarvis's Spotify connection: Apple Music (the Music app on a Mac), YouTube and YouTube Music playlists,
and opening the search of the other services. Spotify playback itself stays in app.py, next to the Spotify
connection it uses (see play_music there); it calls best_match() from here to pick the right item.

Every reply says exactly what happened. When a service only lets Jarvis open its search (no way to press play
from outside), it says so instead of claiming the music is playing.
"""
import difflib
import json
import re
import subprocess
import urllib.parse
from dataclasses import dataclass

import osal

# ---------------------------------------------------------------- understanding the request
SERVICES = {   # service id -> how people say it (longest first wins: "youtube music" before "youtube")
    "youtube_music": ["youtube music", "yt music", "you tube music"],
    "apple_music": ["apple music", "itunes", "the music app", "music app"],
    "spotify": ["spotify"],
    "youtube": ["youtube", "you tube"],
    "soundcloud": ["soundcloud", "sound cloud"],
    "deezer": ["deezer"],
    "tidal": ["tidal"],
    "amazon_music": ["amazon music"],
}
SERVICE_NAMES = {"youtube_music": "YouTube Music", "apple_music": "Apple Music", "spotify": "Spotify",
                 "youtube": "YouTube", "soundcloud": "SoundCloud", "deezer": "Deezer", "tidal": "Tidal",
                 "amazon_music": "Amazon Music"}
# Spotify's own personal playlists, known by name: "play my Discover Weekly" is a playlist without the word.
NAMED_PLAYLISTS = re.compile(r"^(?:discover weekly|release radar|daily mix(?: \d)?|on repeat|repeat rewind|"
                             r"time capsule|daylist|your top songs(?: \d{4})?)$")
# What people call them: "the repeat playlist" is On Repeat, "my discover" is Discover Weekly.
_MIX_NAMES = {"on repeat": "On Repeat", "repeat": "On Repeat", "my repeat": "On Repeat", "repeat rewind": "Repeat Rewind",
              "rewind": "Repeat Rewind", "discover weekly": "Discover Weekly", "discover": "Discover Weekly",
              "discovery weekly": "Discover Weekly", "weekly discover": "Discover Weekly",
              "release radar": "Release Radar", "radar": "Release Radar", "time capsule": "Time Capsule",
              "daylist": "daylist", "day list": "daylist", "top songs": "Your Top Songs", "your top songs": "Your Top Songs",
              "my top songs": "Your Top Songs", "daily mix": "Daily Mix 1"}
_LIKED = re.compile(r"^(?:(?:my )?(?:liked|saved|favou?rited?) (?:songs|tracks|music)|my likes|liked|my library|"
                    r"(?:my )?(?:liked|saved) videos)$")
_VERB = re.compile(r"^(?:(?:hey |ok |okay )?(?:jarvis|jervis)[, ]+)?(?:(?:please|can you|could you|would you|i want to|"
                   r"i wanna|i'd like to|let's|lets|go ahead and)\s+)*(?P<verb>play|put on|start|listen to|shuffle|"
                   r"start playing|blast)\s+(?P<rest>.+)$", re.I)


@dataclass
class MusicRequest:
    query: str              # the name, as said ("My Favorite Songs", "OK Computer Radiohead")
    kind: str               # playlist | album | artist | song | liked | any
    service: str = ""       # one of SERVICES, or "" (the default service)
    shuffle: bool = False
    mine: bool = False      # "my ..." — only the user's own library, never someone else's with the same name
    by: str = ""            # the artist, when said ("OK Computer by Radiohead"), to pick the right album/song
    alt: str = ""           # the name with its "my" kept ("My Favorite Songs"): "my" may be part of the name
    public: bool = False    # "a / some lofi playlist": anyone's will do, not one particular playlist

    @property
    def names(self) -> list:
        """The ways the name might be meant, for matching against what the user actually has."""
        return [n for n in dict.fromkeys([self.query, self.alt]) if n]


def parse_music_request(text: str):
    """A MusicRequest for a request to play a named collection or on a named service, else None (plain "play X"
    keeps going through Jarvis's usual song handling)."""
    raw = (text or "").strip()
    m = _VERB.match(re.sub(r"\s+", " ", raw).rstrip(" .!?"))
    if not m:
        return None
    shuffle = m.group("verb").lower() == "shuffle" or bool(re.search(r"\b(?:on |in )?shuffle(?:d)?\b", m.group("rest"), re.I))
    rest = re.sub(r"\b(?:on |in |with )?shuffle(?:d)?\b", " ", m.group("rest"), flags=re.I)
    rest = re.sub(r"\s+(?:please|for me|now|right now)$", "", rest.strip(), flags=re.I)

    service = ""
    for sid, names in sorted(SERVICES.items(), key=lambda kv: -max(len(n) for n in kv[1])):
        for name in names:
            pattern = rf"\s*\b(?:(?:on|in|from|with|using|through|via|at)\s+)?(?:the\s+)?{re.escape(name)}(?:\s+app)?\b"
            if re.search(pattern, rest, re.I):
                service = sid
                rest = re.sub(pattern, " ", rest, count=1, flags=re.I)
                break
        if service:
            break

    words = " ".join(rest.split())
    public = False
    quoted = re.search(r"[\"“”']([^\"“”]{2,})[\"“”']", words)
    kind = "any"
    if re.search(r"\bplay ?lists?\b|\bmix ?tape\b", words, re.I):
        kind = "playlist"
    elif re.search(r"\b(?:album|record|ep)\b", words, re.I):
        kind = "album"
    elif re.search(r"\b(?:songs|music|tracks)\s+(?:by|from|of)\b|\bartist\b", words, re.I) and not quoted:
        kind = "artist"
    elif re.search(r"\b(?:song|track|single)\b", words, re.I):
        kind = "song"

    mine = bool(re.match(r"^(?:my|our)\b", words, re.I)) and kind != "artist"
    if quoted:
        name = alt = quoted.group(1).strip()   # exactly as written
    else:
        # only the word that told the kind goes ("the Workout playlist" -> "Workout"); "Favorite Songs" stays whole
        kind_words = {"playlist": r"play ?lists?|mix ?tape", "album": r"album|record|ep", "song": r"song|track|single",
                      "artist": r"artist|(?:songs|music|tracks)(?=\s+(?:by|from|of)\b)"}.get(kind, "")
        name = re.sub(rf"\b(?:{kind_words})\b", " ", words, flags=re.I) if kind_words else words
        public = bool(re.match(r"^\s*(?:a|an|some|any)\s+", name, re.I))
        name = re.sub(r"^\s*(?:the|a|an|some|any)\s+", "", name, flags=re.I)
        name = re.sub(r"^\s*(?:called|named|titled|by|from|of)\s+|\s+(?:called|named|titled)\s+", " ", name, flags=re.I)
        name = re.sub(r"\b(?:the|by|from|of)\s*$", "", name.strip(), flags=re.I)
        name = " ".join(name.split()).strip(" ,.-:")
        alt = name
        name = re.sub(r"^(?:my|our)\s+(?:own\s+)?", "", name, flags=re.I)
        if alt == name:
            alt = ""

    by = ""
    if not quoted and kind in ("album", "song", "any"):
        name, _, by = (name.partition(" by ") if " by " in f" {name} " else (name, "", ""))
        name, by = name.strip(), by.strip()
    lowered = name.lower()
    # "my liked songs" — but never a playlist that happens to be called that ("My Favorite Songs" playlist, quoted)
    if kind in ("any", "song") and not quoted and (
            _LIKED.match(f"my {lowered}" if mine else lowered) or (mine and lowered in ("likes", "liked", "favorites", "favourites"))):
        kind, name = "liked", ""
    elif kind == "any" and NAMED_PLAYLISTS.match(lowered):
        kind = "playlist"
    if kind == "liked" or (kind != "any" and kind != "song") or service:
        if not name and kind != "liked":
            return None
        if kind == "song" and service in ("", "spotify", "youtube"):
            return None   # a single song on Spotify or YouTube: Jarvis's existing song/video handling does that
        if kind == "any" and service in ("spotify", "youtube"):
            return None   # "play Radiohead on Spotify" / "… on YouTube": existing handling (top song / video)
        return MusicRequest(query=name, kind=kind, service=service, shuffle=shuffle, mine=mine and not quoted, by=by,
                            alt=alt if alt != name else "", public=public and not mine)
    return None


def spotify_mix(name: str) -> str:
    """The Spotify-made personal playlist a name means ("repeat" -> "On Repeat", "daily mix 3" -> "Daily Mix 3"),
    or "" when it isn't one."""
    n = _norm(re.sub(r"^(?:my|our)\s+(?=(?:on repeat|discover|release|daily|daylist|time|top)\b)", "", (name or "").strip(), flags=re.I))
    n = re.sub(r"\s+(?:mix|playlist)$", "", n) if n not in ("daily mix",) else n
    if not n:
        return ""
    daily = re.fullmatch(r"(?:daily mix|daily|mix) ?(\d)", n)
    if daily:
        return f"Daily Mix {daily.group(1)}"
    top = re.fullmatch(r"(?:your |my )?top songs (\d{4})", n)
    if top:
        return f"Your Top Songs {top.group(1)}"
    return _MIX_NAMES.get(n, "")


# ---------------------------------------------------------------- finding the right one by name
def _norm(text: str) -> str:
    text = re.sub(r"[\"“”'’`]", "", (text or "").lower())
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def name_score(wanted: str, name: str) -> float:
    """How well a name fits what was asked: 1.0 the same name; ~0.9 it contains it (or the other way round);
    otherwise how much of it matches (words and letters)."""
    w, n = _norm(wanted), _norm(name)
    if not w or not n:
        return 0.0
    if w == n:
        return 1.0
    if f" {w} " in f" {n} " or f" {n} " in f" {w} ":
        return 0.9 - 0.2 * abs(len(n) - len(w)) / max(len(n), len(w))
    words_w, words_n = set(w.split()), set(n.split())
    overlap = len(words_w & words_n) / len(words_w | words_n)
    return 0.5 * overlap + 0.5 * difflib.SequenceMatcher(None, w, n).ratio()


def best_match(wanted: str, items: list, name_of=lambda x: x, threshold: float = 0.72):
    """The item whose name best fits `wanted`, if it fits well enough (None rather than a wrong guess)."""
    scored = sorted(((name_score(wanted, name_of(i)), idx, i) for idx, i in enumerate(items)), key=lambda t: (-t[0], t[1]))
    return scored[0][2] if scored and scored[0][0] >= threshold else None


# ---------------------------------------------------------------- YouTube / YouTube Music playlists
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0 Safari/537.36")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def youtube_playlists(query: str, limit: int = 8) -> list:
    """[(title, playlist_id, first_video_id)] from YouTube's playlist search, best results first."""
    import requests
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query, "sp": "EgIQAw=="})
    html = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en"}, timeout=10).text
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    if not m:
        return []
    found = []
    for node in _walk(json.loads(m.group(1))):
        lockup = node.get("lockupViewModel")
        if isinstance(lockup, dict) and str(lockup.get("contentId", "")).startswith(("PL", "OL", "RD")):
            title = next((n["content"] for n in _walk(lockup.get("metadata", {})) if isinstance(n.get("content"), str)), "")
            video = next((n.get("videoId") for n in _walk(lockup) if n.get("videoId")), "")
            found.append((title, lockup["contentId"], video))
        legacy = node.get("playlistRenderer")
        if isinstance(legacy, dict) and legacy.get("playlistId"):
            title = (legacy.get("title") or {}).get("simpleText", "")
            video = next((n.get("videoId") for n in _walk(legacy) if n.get("videoId")), "")
            found.append((title, legacy["playlistId"], video))
    unique = list({pid: (t, pid, v) for t, pid, v in found}.values())
    return unique[:limit]


def youtube_playlist_url(playlist_id: str, first_video: str, music: bool = False) -> str:
    host = "https://music.youtube.com" if music else "https://www.youtube.com"
    return f"{host}/watch?v={first_video}&list={playlist_id}" if first_video else f"{host}/playlist?list={playlist_id}"


# ---------------------------------------------------------------- Apple Music (the Music app, Mac)
def _music_script(script: str, *args: str, timeout: int = 20) -> str:
    result = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "the Music app didn't answer")
    return result.stdout.strip()


_APPLE_PLAYLISTS = 'tell application "Music" to get name of every user playlist'
_APPLE_PLAY_PLAYLIST = '''on run argv
    tell application "Music"
        set shuffle enabled to ((item 2 of argv) is "true")
        play user playlist (item 1 of argv)
        delay 0.6
        return name of current track
    end tell
end run'''
_APPLE_PLAY_LIBRARY = '''on run argv
    tell application "Music"
        set shuffle enabled to true
        play library playlist 1
        delay 0.6
        return name of current track
    end tell
end run'''
# The library's own tracks for an album / artist / song, gathered into Jarvis's own playlist and played from there.
_APPLE_PLAY_TRACKS = '''on run argv
    set what to item 1 of argv
    set wanted to item 2 of argv
    tell application "Music"
        if what is "album" then
            set found to (every track of library playlist 1 whose album contains wanted)
        else if what is "artist" then
            set found to (every track of library playlist 1 whose artist contains wanted)
        else
            set found to (every track of library playlist 1 whose name contains wanted)
        end if
        if (count of found) is 0 then return ""
        if exists user playlist "Jarvis" then delete every track of user playlist "Jarvis"
        if not (exists user playlist "Jarvis") then make new user playlist with properties {name:"Jarvis"}
        repeat with t in found
            duplicate t to user playlist "Jarvis"
        end repeat
        set shuffle enabled to ((item 3 of argv) is "true")
        play user playlist "Jarvis"
        delay 0.6
        return (name of current track) & " by " & (artist of current track)
    end tell
end run'''


def play_apple_music(req: MusicRequest, open_url) -> str:
    """Apple Music: what's in the user's library plays right away; anything else opens Apple Music's search (the
    Music app can't be told to play something from the catalog that isn't in the library)."""
    search = "https://music.apple.com/search?term=" + urllib.parse.quote(req.query or "")
    if not osal.IS_MAC:
        open_url(search, "music.apple.com")
        return f"I opened Apple Music's search for {req.query}. Tap play there." if req.query else "I opened Apple Music."
    try:
        if req.kind == "liked":
            playing = _music_script(_APPLE_PLAY_LIBRARY)
            return f"Shuffling your Apple Music library, starting with {playing}." if playing else "Playing your Apple Music library."
        if req.kind in ("playlist", "any"):
            names = [n.strip() for n in _music_script(_APPLE_PLAYLISTS).split(",") if n.strip()]
            name = best_match(req.query, names)
            if name:
                _music_script(_APPLE_PLAY_PLAYLIST, name, "true" if req.shuffle else "false")
                return f"Playing your playlist {name} on Apple Music{', shuffled' if req.shuffle else ''}."
            if req.kind == "playlist":
                subprocess.run(["open", "music://music.apple.com/search?term=" + urllib.parse.quote(req.query)], timeout=10)
                return (f"There's no playlist called {req.query} in your Apple Music library, so I opened Apple Music's "
                        f"search for it. Tap play there.")
        what = req.kind if req.kind in ("album", "artist", "song") else "artist"
        playing = _music_script(_APPLE_PLAY_TRACKS, what, req.query, "true" if (req.shuffle or what == "artist") else "false")
        if playing:
            return f"Playing {playing} on Apple Music."
        subprocess.run(["open", "music://music.apple.com/search?term=" + urllib.parse.quote(req.query)], timeout=10)
        return f"{req.query} isn't in your Apple Music library, so I opened Apple Music's search for it. Tap play there."
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(f"Apple Music didn't answer: {e}", flush=True)
        return "I couldn't control the Music app. If macOS asked whether Jarvis may control Music, allow it, then ask me again."


# ---------------------------------------------------------------- services Jarvis can only open
SEARCH_URLS = {
    "soundcloud": ("https://soundcloud.com/search/{kind}?q={q}", "soundcloud.com", {"playlist": "sets", "album": "albums", "artist": "people"}),
    "deezer": ("https://www.deezer.com/search/{q}/{kind}", "deezer.com", {"playlist": "playlist", "album": "album", "artist": "artist"}),
    "tidal": ("https://listen.tidal.com/search/{kind}?q={q}", "listen.tidal.com", {"playlist": "playlists", "album": "albums", "artist": "artists"}),
    "amazon_music": ("https://music.amazon.com/search/{q}", "music.amazon.com", {}),
}


def open_service_search(req: MusicRequest, open_url) -> str:
    template, host, kinds = SEARCH_URLS[req.service]
    kind = kinds.get(req.kind, "")
    url = template.format(q=urllib.parse.quote(req.query), kind=kind).replace("//?", "/?").rstrip("/")
    open_url(url, host)
    what = f"the {req.kind} {req.query}" if req.kind in ("playlist", "album") else req.query
    return f"I opened {SERVICE_NAMES[req.service]}'s search for {what}. Tap play there: I can't start it from outside the app."
