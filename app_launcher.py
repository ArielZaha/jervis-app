"""Open any installed desktop application by spoken name.

Speech recognition rarely returns an app's exact name ("spotifi", "whats app",
"vs code"), so names are resolved against the apps actually installed on the
machine: aliases first, then exact / prefix matches, then fuzzy matching.
"""
import difflib
import json
import os
import platform
import re
import subprocess
import time

import osal

APP_DIRS = (
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    os.path.expanduser("~/Applications"),
)

# Spoken shorthand -> installed app name.
ALIASES = {
    "chrome": "Google Chrome",
    "browser": "Google Chrome",
    "code": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "visual studio": "Visual Studio Code",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "power point": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "onenote": "Microsoft OneNote",
    "settings": "System Settings",
    "system preferences": "System Settings",
    "preferences": "System Settings",
    "calc": "Calculator",
    "whats app": "WhatsApp",
    "what's app": "WhatsApp",
    "app store": "App Store",
    "activity monitor": "Activity Monitor",
    "task manager": "Activity Monitor",
    "text edit": "TextEdit",
    "photos": "Photos",
    "messages": "Messages",
    "mail": "Mail",
    "music": "Music",
}

# Well-known websites that can be opened by name when no app matches.
SITES = {
    "netflix": "https://www.netflix.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "google classroom": "https://classroom.google.com",
    "khan academy": "https://www.khanacademy.org",
    "quizlet": "https://quizlet.com",
    "kahoot": "https://kahoot.it",
    "duolingo": "https://www.duolingo.com",
    "coursera": "https://www.coursera.org",
    "google scholar": "https://scholar.google.com",
    "classroom": "https://classroom.google.com",
    "google meet": "https://meet.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",  # not the native Calendar app: Jervis can only read/write Google's
    "google photos": "https://photos.google.com",
    "google docs": "https://docs.google.com/document",
    "google doc": "https://docs.google.com/document",
    "google sheets": "https://docs.google.com/spreadsheets",
    "google slides": "https://docs.google.com/presentation",
    "drive": "https://drive.google.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "twitch": "https://www.twitch.tv",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "imdb": "https://www.imdb.com",
    "wikipedia": "https://www.wikipedia.org",
    "disney plus": "https://www.disneyplus.com",
    "prime video": "https://www.primevideo.com",
    "hbo max": "https://www.max.com",
    "spotify web": "https://open.spotify.com",
}
_WEB_HINT = re.compile(r"\s+(?:on|in)\s+(?:the\s+|my\s+)?(?:web\s+)?(?:browser|chrome|google chrome|internet|web)$|\s+(?:website|web site|site|web page)$")

# Spoken shorthand on Windows, where the same programs have different names.
if osal.IS_WIN:
    ALIASES.update({
        "browser": ("Google Chrome", "Microsoft Edge", "Firefox"),
        "settings": "Settings", "system preferences": "Settings", "preferences": "Settings",
        "task manager": "Task Manager", "activity monitor": "Task Manager",
        "text edit": "Notepad", "textedit": "Notepad", "notes": "Sticky Notes",
        "visual studio": "Visual Studio Code", "files": "File Explorer", "finder": "File Explorer",
        "terminal": "Terminal", "command prompt": "Command Prompt",
    })

VENDOR_PREFIXES = ("microsoft ", "google ", "apple ", "adobe ")
FILLER_LEAD = ("the ", "my ", "up ")
FILLER_TAIL = (" app", " application", " for me", " please", " now", " on my computer", " on my mac")

_OPEN_RE = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) |please |can you |could you |would you |"
    r"i want you to |i want to |i need to |go ahead and |just )*"
    r"(open|launch|start|run)(?: up)? (.+)$"
)

_cache = {"at": 0.0, "apps": {}}
_CACHE_SECONDS = 60


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


_WIN_APP_IDS = {}  # display name -> Windows app id, filled by installed_apps()


def _windows_apps() -> dict:
    """Everything in the Start menu (desktop programs and Store apps alike)."""
    try:
        code, out, _err = osal.run_powershell("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress", timeout=25)
        rows = json.loads(out) if code == 0 and out else []
    except Exception:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    apps = {}
    for row in rows:
        name, app_id = (row.get("Name") or "").strip(), row.get("AppID") or ""
        if name and app_id:
            apps.setdefault(_norm(name), name)
            _WIN_APP_IDS.setdefault(name, app_id)
    return apps


def installed_apps() -> dict:
    """Map normalized app name -> display name (macOS and Windows; empty elsewhere)."""
    if platform.system() not in ("Darwin", "Windows"):
        return {}
    if time.time() - _cache["at"] < _CACHE_SECONDS and _cache["apps"]:
        return _cache["apps"]
    if platform.system() == "Windows":
        apps = _windows_apps()
        _cache.update(at=time.time(), apps=apps)
        return apps
    apps = {}
    for directory in APP_DIRS:
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            if entry.endswith(".app"):
                apps.setdefault(_norm(entry[:-4]), entry[:-4])
    _cache.update(at=time.time(), apps=apps)
    return apps


def _strip_vendor(name: str) -> str:
    for prefix in VENDOR_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def resolve_app(spoken: str):
    """Return ("ok", name), ("ambiguous", [names]) or ("missing", None)."""
    query = _norm(spoken)
    apps = installed_apps()
    if not query:
        return "missing", None
    if not apps:  # Not macOS (or nothing found): trust the spoken name.
        return "ok", spoken.strip()

    alias = ALIASES.get(query)
    for candidate in ([alias] if isinstance(alias, str) else list(alias or [])):
        if _norm(candidate) in apps:
            return "ok", apps[_norm(candidate)]

    # Exact match, with or without a vendor prefix ("word" -> "Microsoft Word").
    exact = {display for key, display in apps.items() if query in (key, _strip_vendor(key))}
    if len(exact) == 1:
        return "ok", exact.pop()
    if len(exact) > 1:
        return "ambiguous", sorted(exact)

    # Every spoken word is the start of some word in the app name ("spot" -> "Spotify").
    if len(query) >= 3:
        words = query.split()
        partial = {
            display for key, display in apps.items()
            if all(any(t.startswith(w) for t in key.split()) for w in words)
        }
        if len(partial) == 1:
            return "ok", partial.pop()
        if len(partial) > 1:
            return "ambiguous", sorted(partial)

    # Fuzzy match for mishearings ("spotifi", "whats app", "calculater").
    squashed = {key.replace(" ", ""): display for key, display in apps.items()}
    squashed.update({_strip_vendor(key).replace(" ", ""): display for key, display in apps.items()})
    match = difflib.get_close_matches(query.replace(" ", ""), list(squashed), n=1, cutoff=0.72)
    if match:
        return "ok", squashed[match[0]]

    return "missing", None


def _clean_target(target: str) -> str:
    target = target.strip()
    changed = True
    while changed:
        changed = False
        for lead in FILLER_LEAD:
            if target.startswith(lead):
                target, changed = target[len(lead):], True
        for tail in FILLER_TAIL:
            if target.endswith(tail):
                target, changed = target[: -len(tail)], True
    return target.strip()


def parse_open_request(text: str):
    """Return the app name from "open X" style requests, else None.

    "open" / "launch" always count. "start" / "run" are ambiguous in normal
    conversation, so they only count when X is an installed app.
    """
    match = _OPEN_RE.match(_norm(text))
    if not match:
        return None
    verb, target = match.group(1), _clean_target(match.group(2))
    if not target:
        return None
    if verb in ("open", "launch"):
        return target
    return target if resolve_app(target)[0] != "missing" else None


def _launch(name: str) -> str:
    system = platform.system()
    try:
        if system == "Windows":
            app_id = _WIN_APP_IDS.get(name)
            if app_id:  # exactly what the Start menu does, so it works for Store apps too
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
            else:
                subprocess.Popen(["cmd", "/c", "start", "", name], creationflags=osal._NO_WINDOW)
        elif system == "Darwin":
            subprocess.run(["open", "-a", name], check=True, capture_output=True, text=True, timeout=15)
        else:
            subprocess.Popen([name])
        return f"Opened {name}."
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip() or str(e)
        return f"I couldn't open {name}: {detail}"
    except Exception as e:
        return f"I couldn't open {name}: {e}"


def _site_for(target: str):
    """Return (url, host) if the spoken name is a known website or "<name> dot com"."""
    key = re.sub(r"\s+(?:dot\s+)?com$", "", target) if target.endswith("com") and target != "com" else target
    if key in SITES:
        url = SITES[key]
    elif key != target and re.fullmatch(r"[a-z0-9]+", key):
        url = f"https://www.{key}.com"
    else:
        return None
    return url, re.sub(r"^https://(?:www\.)?", "", url)


def _open_site(url: str, host: str, name: str) -> str:
    try:
        import google_accounts
        if google_accounts.applies(host):
            # Google pages open under the right account (school for learning, personal for the rest), in a NEW tab
            google_accounts.open_page(url, name)
            return f"Opened {name}."
        from youtube_browser import open_site
        open_site(url, host, name)
        return f"Opened {name}."
    except Exception as e:
        return f"I couldn't open {name}: {e}"


def open_application(app_name: str, **kwargs) -> str:
    """Open one or more apps or well-known websites ("Chrome and Netflix") and describe what happened."""
    spoken = _norm(app_name)
    web_only = bool(_WEB_HINT.search(spoken))  # "netflix on browser" always means the website
    spoken = _WEB_HINT.sub("", spoken).strip() or spoken

    targets = [spoken]
    if resolve_app(spoken)[0] == "missing" and not _site_for(spoken):
        targets = [t for t in re.split(r"\s+(?:and|then|plus)\s+", spoken) if t]

    results = []
    for target in targets:
        site = _site_for(target)
        # A named site wins over fuzzy app matches ("google" would otherwise open Google Chrome).
        import google_accounts
        google_doc_site = bool(site and google_accounts.applies(site[1]))
        # (an installed Google Docs / Drive app would open under whatever account it was installed with)
        if site and (web_only or google_doc_site or target not in installed_apps()):
            results.append(_open_site(*site, target.title()))
            continue
        status, value = resolve_app(target)
        if status == "ok":
            results.append(_launch(value))
        elif status == "ambiguous":
            names = value[:4]
            results.append(f"Which one did you mean: {', '.join(names[:-1])} or {names[-1]}?")
        else:
            results.append(f"I couldn't find an app called {target}.")
    return " ".join(results)
