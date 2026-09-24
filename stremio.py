"""Find a movie or series and open it in the Stremio desktop app.

Titles are looked up in Stremio's own catalog (Cinemeta), which returns the
IMDb ids Stremio's deep links use. macOS routes stremio:// links to the app,
which navigates its existing window, so nothing new opens if it is running.
"""
import json
import os
import platform
import re
import subprocess
from urllib.parse import quote

import requests

from netflix import resembles  # a search result must actually resemble what was asked for

CINEMETA = "https://v3-cinemeta.strem.io/catalog/{kind}/top/search={query}.json"
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stremio_cache.json")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _search(kind: str, query: str) -> list:
    try:
        resp = requests.get(CINEMETA.format(kind=kind, query=quote(query)), timeout=12)
        resp.raise_for_status()
        return [m for m in resp.json().get("metas", []) if m.get("imdb_id") and m.get("name")]
    except (requests.RequestException, ValueError):
        return []


def find_title(query: str, kind: str = ""):
    """Return (imdb_id, name, kind) for the best match, or None. `kind` may force "movie" or "series"."""
    key = f"{kind}:{_norm(query)}"
    cache = _load_cache()
    if key in cache and resembles(query, cache[key][1]):
        return tuple(cache[key])

    wanted = _norm(query)
    best, best_score = None, -1
    for k in ([kind] if kind else ["series", "movie"]):
        for rank, meta in enumerate(_search(k, query)[:5]):
            if not resembles(query, meta["name"]):
                continue
            name = _norm(meta["name"])
            # Exact name beats prefix beats anything else; earlier catalog rank breaks ties, series before movies.
            score = (3 if name == wanted else 2 if name.startswith(wanted) else 1) * 10 - rank
            if score > best_score:
                best, best_score = (meta["imdb_id"], meta["name"], k), score
    if best:
        cache[key] = list(best)
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=1)
        except OSError:
            pass
    return best


def deep_link(imdb_id: str, kind: str, season=None, episode=None) -> str:
    if kind == "series" and season and episode:
        return f"stremio:///detail/series/{imdb_id}/{imdb_id}:{season}:{episode}"
    if kind == "movie":
        return f"stremio:///detail/movie/{imdb_id}/{imdb_id}"
    return f"stremio:///detail/series/{imdb_id}"


def search_link(query: str) -> str:
    return f"stremio:///search?search={quote(query)}"


def is_installed() -> bool:
    if platform.system() == "Windows":
        try:  # Stremio registers the stremio:// link type when it is installed
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "stremio"))
            return True
        except OSError:
            return False
    if platform.system() != "Darwin":
        return True
    return any(
        os.path.isdir(os.path.join(d, "Stremio.app"))
        for d in ("/Applications", os.path.expanduser("~/Applications"))
    )


def open_link(url: str) -> bool:
    """Hand a stremio:// link to the Stremio app. Returns False if it could not be opened."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", url], check=True, capture_output=True, timeout=15)
        elif platform.system() == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", url], check=True, capture_output=True, timeout=15)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def toggle_playback() -> str:
    """Press the space bar in Stremio's player (macOS asks for Accessibility permission the first time)."""
    if platform.system() == "Windows":
        try:
            import winctl
            windows = [w for w in winctl.find_windows("stremio", browsers_only=False) if not winctl.is_browser_title(w[1])]
            if not windows:
                return "I don't see the Stremio window. Is it open?"
            winctl.focus(windows[0][0])
            winctl.press("space")
            return "Toggled play and pause in Stremio."
        except (RuntimeError, OSError) as e:
            return f"I couldn't control Stremio: {e}"
    if platform.system() != "Darwin":
        return "I can only control Stremio's player on macOS and Windows for now."
    script = 'tell application "Stremio" to activate\ndelay 0.3\ntell application "System Events" to keystroke " "'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as e:
        return f"I couldn't reach Stremio: {e}"
    if result.returncode != 0:
        if "not allowed" in result.stderr or "1002" in result.stderr:
            return ("I need Accessibility permission to press keys. Open System Settings, Privacy and Security, "
                    "Accessibility, and allow the app running Jervis.")
        return "I couldn't control Stremio."
    return "Toggled play and pause in Stremio."
