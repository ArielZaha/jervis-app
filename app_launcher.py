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

_LEAD = (r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) |please |can you |could you |would you |"
         r"i want you to |i want to |i need to |go ahead and |just )*")
_OPEN_RE = re.compile(_LEAD + r"(open|launch|start|run)(?: up)? (.+)$")
_CLOSE_RE = re.compile(_LEAD + r"(?:close|quit|exit)(?: out of)? (.+?)(?: for me| please| now)*$")
# "Open this app" / "close this app": no name, so "this" means the window being worked in (never Jervis's own).
THIS_APP = {"this", "that", "it", "this app", "that app", "the app", "this application", "this program", "this window",
            "the current app", "current app", "the current window", "current window", "the active window",
            "the window", "the program", "this one"}
OWN_PROCESSES = {"jervis.exe", "electron.exe", "jervis-backend.exe"}   # never close or "find" Jervis himself
# Windows programs whose process name doesn't follow from the Start-menu name.
WIN_EXE = {"visual studio code": "code.exe", "word": "winword.exe", "microsoft word": "winword.exe",
           "excel": "excel.exe", "powerpoint": "powerpnt.exe", "outlook": ("olk.exe", "outlook.exe"), "file explorer": "explorer.exe",
           "task manager": "taskmgr.exe", "command prompt": "cmd.exe", "terminal": "windowsterminal.exe"}
LAUNCH_CONFIRM_SECONDS = 5.0   # how long to watch for the new window before saying "it's starting" instead
last_choices = []   # the names offered by the latest "Which one did you mean…?" (app.py turns the answer into one)

_cache = {"at": 0.0, "apps": {}}
_CACHE_SECONDS = 60


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


_WIN_APP_IDS = {}  # display name -> Windows app id, filled by installed_apps()
BROKEN_APPS = {}   # display name -> the missing program: Start-menu entries left behind by an uninstall
_known_folders = {}


def _known_folder(guid: str):
    """The path of a Windows "known folder" ({6D809377-…} is Program Files), or None."""
    if guid in _known_folders:
        return _known_folders[guid]
    path = None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]
        folder_id = GUID.from_buffer_copy(uuid.UUID(guid).bytes_le)
        result = ctypes.c_wchar_p()
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHGetKnownFolderPath.argtypes = (ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p))
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(result)) == 0:
            path = result.value
        ctypes.windll.ole32.CoTaskMemFree(result)
    except Exception:
        path = None
    _known_folders[guid] = path
    return path


def app_id_program(app_id: str):
    """The program a Start-menu entry runs, when its id is a file path ("{6D809377-…}\\Blender Foundation\\Blender 4.5\\
    blender-launcher.exe", "C:\\Tools\\x.exe"); None for Store apps and others that aren't a path."""
    m = re.match(r"^(\{[0-9A-Fa-f-]{36}\})\\(.+)$", app_id or "")
    if m:
        root = _known_folder(m.group(1))
        return os.path.join(root, m.group(2)) if root else None
    if re.match(r"^[A-Za-z]:\\", app_id or "") and (app_id or "").lower().endswith(".exe"):
        return app_id
    return None


def program_path(display_name: str):
    """The real .exe behind a Start-menu display name (e.g. "Blender 4.5" -> "...\\Blender Foundation\\Blender 4.5\\
    blender-launcher.exe"), so it can be launched directly with extra command-line arguments. None if it can't be
    resolved (not Windows, not found, or a Store app with no plain exe)."""
    if not osal.IS_WIN:
        return None
    installed_apps()   # make sure _WIN_APP_IDS is populated
    app_id = _WIN_APP_IDS.get(display_name)
    return app_id_program(app_id) if app_id else None


def _windows_apps() -> dict:
    """Everything in the Start menu (desktop programs and Store apps alike), except entries whose program is gone
    (an uninstall that left its shortcut behind): those can't open, so they're never offered."""
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
            program = app_id_program(app_id)
            if program and not os.path.exists(program):
                BROKEN_APPS[name] = program
                continue
            BROKEN_APPS.pop(name, None)
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

    # Fuzzy match for mishearings ("spotifi", "whats app", "calculater") — but never across version numbers:
    # "Blender 4.3" must not quietly open Blender 4.5.
    squashed = {key.replace(" ", ""): display for key, display in apps.items()}
    squashed.update({_strip_vendor(key).replace(" ", ""): display for key, display in apps.items()})
    digits = "".join(re.findall(r"\d", query))
    if digits:
        squashed = {k: d for k, d in squashed.items() if "".join(re.findall(r"\d", k)) == digits}
    match = difflib.get_close_matches(query.replace(" ", ""), list(squashed), n=1, cutoff=0.72)
    if match:
        return "ok", squashed[match[0]]

    return "missing", None


def broken_app(spoken: str):
    """The Start-menu name of a left-behind entry matching what was said ("blender 4.3" -> "Blender 4.3"), or None."""
    query = _norm(spoken)
    for name in BROKEN_APPS:
        if query and query in (_norm(name), _strip_vendor(_norm(name))):
            return name
    return None


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


def means_this_app(target: str, strict: bool = False) -> bool:
    """"this app", "the current window", "it": no name was given, the app being worked in is meant. strict (for
    closing): only when an app/window/program is actually said, so a stray "close it" never closes your work."""
    t = _norm(target)
    if strict and not re.search(r"\b(?:app|application|program|window)\b", t):
        return False
    return t in THIS_APP or _clean_target(t) in THIS_APP or _clean_target(t) in ("current", "active window")


def parse_close_request(text: str):
    """"Close Discord" -> "discord"; "close this app" -> "this app"; else None (tabs are app.py's parse_close_command)."""
    match = _CLOSE_RE.match(_norm(text))
    if not match:
        return None
    target = match.group(1).strip()
    if means_this_app(target, strict=True):
        return target
    if means_this_app(target):
        return None   # "close it" / "close this": too vague to close anything (tabs and panels handle their own)
    return _clean_target(target) or None


# ---------- open windows (Windows): which belong to an app, so "open" can bring it forward and "close" can close it ----------
def _app_keys(name: str) -> set:
    """The ways a window can show it belongs to an app: "Google Chrome" -> {"google chrome", "chrome", "googlechrome"…}."""
    n = _norm(name)
    keys = {n, _strip_vendor(n)}
    base = re.sub(r"(?: \d+)+$", "", n)   # "blender 4 5" -> "blender"
    keys |= {base, _strip_vendor(base)}
    keys |= {k.replace(" ", "") for k in list(keys)}
    return {k for k in keys if k}


def _exe_names(name: str) -> set:
    wanted = WIN_EXE.get(_norm(name)) or WIN_EXE.get(_strip_vendor(_norm(name))) or ()
    return {wanted} if isinstance(wanted, str) else set(wanted)


def _version(name: str) -> str:
    """"Blender 4.5" -> "4 5" (normalized), "" when the name has no version: then any version's window matches."""
    m = re.search(r"(?:^|\s)(\d+(?:\.\d+)*)$", (name or "").strip())
    return _norm(m.group(1)) if m else ""


def app_windows(name: str) -> list:
    """Open windows of an app, front-most first: [(hwnd, title)]. Matched on the program's file name ("chrome.exe")
    and on the window title ("Untitled - Notepad", "x - Visual Studio Code"). A name with a version ("Blender 4.5")
    only matches windows of that version, told apart by the program's folder ("…\\Blender 4.5\\blender.exe") or
    title, so an open Blender 4.3 is never taken for 4.5. Windows only; [] elsewhere."""
    if not osal.IS_WIN:
        return []
    import winctl
    keys, exes, version = _app_keys(name), _exe_names(name), _version(name)
    found = []
    try:
        windows = winctl.list_windows()
    except Exception:
        return []
    for hwnd, title in windows:
        if title == "Program Manager":   # the desktop itself (closing it would bring up the shut-down dialog)
            continue
        path = winctl.window_process_path(hwnd) if hasattr(winctl, "window_process_path") else ""
        exe = path.rsplit("\\", 1)[-1].lower() if path else winctl.window_process_name(hwnd)
        if not exe or exe in OWN_PROCESSES:
            continue
        stem = _norm(exe.removesuffix(".exe")).replace(" ", "")
        t = _norm(title)
        folder = _norm(path).replace(" ", "")
        if not (exe in exes or stem in keys or t in keys or any(len(k) > 4 and t.endswith(" " + k) for k in keys)
                or any(len(k) > 5 and " " not in k and k in folder for k in keys)):
            continue
        if version and f" {version} " not in f" {_norm(path)} {t} ":
            continue
        found.append((hwnd, title))
    return found


def front_app_window():
    """The window the user is working in: the front one, or the one right behind Jervis's own window. (hwnd, title,
    friendly app name) or None."""
    if not osal.IS_WIN:
        return None
    import winctl
    try:
        for hwnd, title in winctl.list_windows():
            exe = winctl.window_process_name(hwnd)
            if exe and exe not in OWN_PROCESSES and title != "Program Manager":
                title = re.sub(r"[‎‏‪-‮⁦-⁩]", "", title).strip()   # invisible direction marks
                friendly =re.split(r"\s[-–—|]\s", title)[-1].strip() if " - " in title or " – " in title else ""
                return hwnd, title, friendly or exe.removesuffix(".exe").title() or title
    except Exception:
        return None
    return None


def _window_handles() -> set:
    try:
        import winctl
        return {hwnd for hwnd, _t in winctl.list_windows()}
    except Exception:
        return set()


def _wait_for_app_window(name: str, before: set, seconds: float):
    """After starting an app: wait for *its* new window (not just any window), bring it to the front, and return its
    handle; None if it didn't appear in time. So "Opened X" is only said once X is really there."""
    import winctl
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.3)
        # Windows' own "Problem with Shortcut" box: the program the Start menu points to is gone. Nothing will open,
        # so close the box and say so now rather than waiting out the clock.
        for hwnd, title in winctl.list_windows():
            if hwnd not in before and title == "Problem with Shortcut" and winctl.window_process_name(hwnd) == "explorer.exe":
                winctl.close_window(hwnd)
                return "broken"
        fresh = [hwnd for hwnd, _title in app_windows(name) if hwnd not in before]
        if fresh:
            time.sleep(0.4)   # let it finish appearing, or the focus change can land on its splash screen
            current = [hwnd for hwnd, _title in app_windows(name) if hwnd not in before] or fresh
            try:
                winctl.focus(current[0])
            except Exception as e:
                print(f"App launch: couldn't bring {name!r} to the front: {e!r}", flush=True)
            return current[0]
    return None


def _launch(name: str, confirm_seconds=None) -> str:
    system = platform.system()
    wait = LAUNCH_CONFIRM_SECONDS if confirm_seconds is None else confirm_seconds
    try:
        if system == "Windows":
            before = _window_handles()
            app_id = _WIN_APP_IDS.get(name)
            if app_id:  # exactly what the Start menu does, so it works for Store apps too
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
            else:
                # Not in the Start menu list (it couldn't be read): let Windows look it up, and say so if it can't.
                started = subprocess.run(["cmd", "/c", "start", "", name], creationflags=osal._NO_WINDOW,
                                         capture_output=True, text=True, timeout=15)
                if started.returncode != 0:
                    print(f"App launch: Windows couldn't start {name!r} (exit {started.returncode}).", flush=True)
                    return f"I couldn't find an app called {name}."
            opened = _wait_for_app_window(name, before, wait) if wait else True
            if opened == "broken":
                print(f"App launch: Windows says {name!r}'s shortcut points to a program that isn't there.", flush=True)
                return (f"{name} can't be opened: its Start menu shortcut points to a program that isn't on this "
                        "computer anymore. It looks uninstalled.")
            if not opened:
                print(f"App launch: started {name!r}, but its window didn't appear within {wait}s.", flush=True)
                return f"I started {name}, but its window hasn't appeared yet. It may still be loading."
            print(f"App launch: {name!r} is open.", flush=True)
        elif system == "Darwin":
            subprocess.run(["open", "-a", name], check=True, capture_output=True, text=True, timeout=15)
        else:
            subprocess.Popen([name])
        return f"Opened {name}."
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip() or str(e)
        print(f"App launch failed for {name!r}: {detail}", flush=True)
        return f"I couldn't open {name}: {detail}"
    except Exception as e:
        print(f"App launch failed for {name!r}: {e!r}", flush=True)
        return f"I couldn't open {name}: {e}"


def _bring_forward(name: str):
    """If the app already has a window, bring it to the front and say so; None if it isn't open (or can't be)."""
    windows = app_windows(name)
    if not windows:
        return None
    import winctl
    try:
        if winctl.focus(windows[0][0]):
            return f"{name} is already open, so I brought it to the front."
    except Exception as e:
        print(f"Bringing {name!r} forward failed: {e!r}", flush=True)
    return None   # Windows refused the focus change: starting it again brings a single-window app forward anyway


def close_application(spoken: str) -> str:
    """Close an app the polite way, as if its X was clicked (it can still ask to save). "this app" is the window being
    worked in. Returns what happened, or None when nothing by that name is installed or open (not a command then)."""
    if means_this_app(spoken, strict=True):
        front = front_app_window()
        if not front:
            return "I couldn't tell which app you mean. Say its name, like “close Notepad”."
        hwnd, _title, friendly = front
        import winctl
        winctl.close_window(hwnd)
        return _closed_message(friendly, [hwnd])
    target = _clean_target(_norm(spoken))
    status, value = resolve_app(target)
    # "close blender" with 4.3 and 4.5 installed: close whichever Blender is open, and say it the way it's written
    name = value if status == "ok" else (target.title() if status == "ambiguous" else target)
    if not osal.IS_WIN:
        if status != "ok":
            return None
        return _quit_mac(name) if osal.IS_MAC else None
    windows = app_windows(name) or (app_windows(target) if name != target else [])
    if not windows:
        if status == "missing" or not installed_apps():
            return None
        return f"{name} isn't open."
    import winctl
    for hwnd, _title in windows:
        winctl.close_window(hwnd)
    return _closed_message(name, [hwnd for hwnd, _t in windows])


def _closed_message(name: str, handles: list) -> str:
    import winctl
    deadline = time.time() + 2.0
    remaining = handles
    while time.time() < deadline:
        time.sleep(0.2)
        remaining = [h for h in handles if winctl.window_exists(h)]
        if not remaining:
            return f"Closed {name}."
    print(f"App close: {name!r} still has {len(remaining)} window(s) open after being asked to close.", flush=True)
    return f"I asked {name} to close. It's still open, so it may be asking you to save something."


def _quit_mac(name: str) -> str:
    try:
        subprocess.run(["osascript", "-e", f'tell application "{name}" to quit'], check=True, capture_output=True,
                       text=True, timeout=10)
        return f"Closed {name}."
    except Exception as e:
        return f"I couldn't close {name}: {e}"


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


def open_application(app_name: str, confirm_seconds=None, **kwargs) -> str:
    """Open one or more apps or well-known websites ("Chrome and Netflix") and describe what happened."""
    spoken = _norm(app_name)
    web_only = bool(_WEB_HINT.search(spoken))  # "netflix on browser" always means the website
    spoken = _WEB_HINT.sub("", spoken).strip() or spoken

    targets = [spoken]
    if resolve_app(spoken)[0] == "missing" and not _site_for(spoken):
        targets = [t for t in re.split(r"\s+(?:and|then|plus)\s+", spoken) if t]

    results = []
    last_choices.clear()
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
            results.append(_bring_forward(value) or _launch(value, confirm_seconds))
        elif status == "ambiguous":
            names = value[:4]
            last_choices[:] = names
            results.append(f"Which one did you mean: {', '.join(names[:-1])} or {names[-1]}?")
        else:
            broken = broken_app(target)
            if broken:
                results.append(f"{broken} can't be opened: its Start menu shortcut points to a program that isn't on "
                               "this computer anymore. It looks uninstalled.")
            else:
                results.append(f"I couldn't find an app called {target}.")
    return " ".join(results)


_ORDINALS = {"first": 0, "1st": 0, "one": 0, "older": 0, "oldest": 0, "second": 1, "2nd": 1, "two": 1, "third": 2,
             "3rd": 2, "three": 2, "fourth": 3, "4th": 3, "last": -1, "latest": -1, "newest": -1, "newer": -1}


def pick_choice(answer: str, options: list):
    """The answer to "Which one did you mean: Blender 4.3 or Blender 4.5?" ("4.5", "the second one", "the newest"),
    as one of `options`, or None if it doesn't pick one."""
    a = re.sub(r"^(?:(?:the|open|launch|start|use) )+", "", _norm(answer))
    a = re.sub(r"(?: (?:one|version|please))+$", "", a).strip()
    if not a or not options:
        return None
    for option in options:
        if a == _norm(option):
            return option
    matches = [o for o in options if _norm(o).endswith(" " + a) or (len(a) > 2 and a in _norm(o))]
    if len(matches) == 1:
        return matches[0]
    for word in a.split():
        if word in _ORDINALS and -len(options) <= _ORDINALS[word] < len(options):
            return options[_ORDINALS[word]]
    return None
