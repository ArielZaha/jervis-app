"""Keep YouTube in one browser tab and control its playback.

macOS: Chrome is scripted directly (AppleScript), so tabs are found, reused, closed and controlled exactly.
Windows: there is no scripting interface, so this drives the browser window like a person would: it finds the window
by its title, brings it forward, and uses keyboard shortcuts and media keys (see winctl.py). Chrome, Edge, Brave and
Firefox all work, but only for a tab that is the ACTIVE tab of its window (the title shows the active tab).
Anything else falls back to the system default browser, which simply opens a new tab.
"""
import platform
import subprocess
import time
import webbrowser
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import google_accounts
import osal
import winctl

CHROME = "Google Chrome"

# Reuse the first YouTube tab found in any window: navigate it, then bring it to the front.
_REUSE_TAB = f'''
on run argv
    set targetUrl to item 1 of argv
    set needle to item 2 of argv
    tell application "{CHROME}"
        repeat with w in windows
            set i to 0
            repeat with t in tabs of w
                set i to i + 1
                if URL of t contains needle then
                    set URL of t to targetUrl
                    set active tab index of w to i
                    set index of w to 1
                    activate
                    return "reused"
                end if
            end repeat
        end repeat
    end tell
    return "none"
end run
'''

# Run JavaScript in every YouTube tab; "ok:<result>" joins what each tab returned.
_RUN_JS = f'''
on run argv
    set js to item 1 of argv
    set found to false
    set results to ""
    tell application "{CHROME}"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "youtube.com" or URL of t contains "netflix.com" then
                    set found to true
                    try
                        set r to execute t javascript js
                    on error
                        return "js-disabled"
                    end try
                    try
                        set results to results & (r as text) & ","
                    end try
                end if
            end repeat
        end repeat
    end tell
    if found then return "ok:" & results
    return "no-tab"
end run
'''


# Close every tab whose URL contains argv item 1, or the active tab when it is empty.
_CLOSE_TABS = f'''
-- argv: how, then the words to look for (how: active | one | all | count | other | everything)
on run argv
    set how to item 1 of argv
    set closed to 0
    tell application "{CHROME}"
        if (count of windows) is 0 then return "0"
        if how is "active" then
            close active tab of front window
            return "1"
        end if
        if how is "other" or how is "everything" then
            set w to front window
            set activeIndex to active tab index of w
            repeat with i from (count of tabs of w) to 1 by -1
                if how is "everything" or i is not activeIndex then
                    close tab i of w
                    set closed to closed + 1
                end if
            end repeat
            return closed as text
        end if
        set needles to items 2 thru -1 of argv
        repeat with w in windows
            repeat with i from (count of tabs of w) to 1 by -1
                set t to tab i of w
                set hit to false
                repeat with wanted in needles
                    if (URL of t contains (wanted as text)) or (title of t contains (wanted as text)) then set hit to true
                end repeat
                if hit then
                    set closed to closed + 1
                    if how is not "count" then close t
                    if how is "one" then return closed as text
                end if
            end repeat
        end repeat
    end tell
    return closed as text
end run
'''

# Bring forward an existing tab whose URL contains argv item 1 (a host name).
_FOCUS_TAB = f'''
on run argv
    set needle to item 1 of argv
    tell application "{CHROME}"
        repeat with w in windows
            set i to 0
            repeat with t in tabs of w
                set i to i + 1
                if URL of t contains needle then
                    set active tab index of w to i
                    set index of w to 1
                    activate
                    return "focused"
                end if
            end repeat
        end repeat
    end tell
    return "none"
end run
'''

_SITES = {"youtube": "youtube.com", "google": "google.com", "netflix": "netflix.com"}


# ---------- Windows implementation ----------
_TITLE_KEYS = {"youtube.com": "YouTube", "netflix.com": "Netflix", "google.com": "Google",
               "docs.google.com/document": "Google Docs", "docs.google.com": "Google Docs"}


def _title_key(host: str) -> str:
    """The word that appears in a browser window's title when that site's tab is active."""
    return _TITLE_KEYS.get(host) or host.split(".")[0].capitalize()


def _win_windows(host_or_key: str) -> list:
    return winctl.find_windows(_title_key(host_or_key) if "." in host_or_key else host_or_key)


def _win_navigate(hwnd: int, url: str) -> None:
    winctl.focus(hwnd)
    winctl.press("ctrl", "l")
    time.sleep(0.15)
    winctl.type_text(url)
    winctl.press("enter")


def _win_current_url(hwnd: int):
    """Read the address of a browser window's active tab by copying the address bar (the clipboard is put back)."""
    prior = osal.run_powershell("Get-Clipboard -Raw")[1]
    winctl.focus(hwnd)
    winctl.press("ctrl", "l")
    time.sleep(0.15)
    winctl.press("ctrl", "c")
    time.sleep(0.25)
    url = osal.run_powershell("Get-Clipboard -Raw")[1]
    winctl.press("esc")
    if prior:
        osal.set_clipboard(prior)
    return url if url.startswith("http") else None


def _win_seek(seconds: int) -> str:
    """Jump the YouTube or Netflix tab to a time by reloading it at that time (both sites support a t= parameter)."""
    for hwnd, title in winctl.find_windows("YouTube", "Netflix"):
        url = _win_current_url(hwnd)
        if not url:
            continue
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query))
        if "netflix" in parsed.netloc and parsed.path.startswith("/watch/"):
            query["t"] = str(int(seconds))
        elif "youtube" in parsed.netloc and parsed.path == "/watch":
            query["t"] = f"{int(seconds)}s"
        else:
            continue
        _win_navigate(hwnd, urlunparse(parsed._replace(query=urlencode(query))))
        return "seek"
    return ""


def _win_control(action: str, seconds: int = None) -> str:
    try:
        if action in ("pause", "resume"):
            winctl.media_key("play_pause")  # a toggle: Windows does not say whether the video is playing
            return "Paused." if action == "pause" else "Resuming."
        if action in ("next", "previous"):
            winctl.media_key("next" if action == "next" else "prev")
            return "Skipping to the next one." if action == "next" else "Going back to the previous one."
        if action in ("restart", "seek"):
            target = 0 if action == "restart" else int(seconds or 0)
            if not _win_seek(target):
                return "Open the video in your browser first: I can only jump to a time on a YouTube or Netflix tab."
            return ("Starting it over from the beginning." if action == "restart"
                    else f"Jumping to {target // 60}:{target % 60:02d}.")
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return f"I couldn't control the browser: {e}"
    return "I can't do that on Windows yet."


def _win_close_tabs(target: str, mode: str) -> str:
    """Windows can only see the ACTIVE tab of each browser window (its title), so only those can be found and closed."""
    try:
        if mode in ("other", "everything"):
            return "On Windows I can only close the tab you are looking at, or one I can see by name."
        if target:
            windows = winctl.find_windows(*needles_for(target))
        else:
            windows = winctl.find_windows(*winctl.BROWSER_SUFFIXES)[:1]  # the front-most browser window
        if not windows:
            return f"I don't see a {target} tab open." if target else "There's no tab to close."
        closed = 0
        for hwnd, _title in windows[: (5 if mode == "all" else 1)]:  # closing changes the titles, so stop after a few
            winctl.focus(hwnd)
            winctl.press("ctrl", "w")
            closed += 1
        label = f"{target} tab" if target else "tab"
        return f"Closed the {label}." if closed == 1 else f"Closed {closed} {target} tabs."
    except (RuntimeError, OSError) as e:
        return f"I couldn't close the tab: {e}"


def _chrome_running() -> bool:
    # pgrep needs no macOS automation permission, unlike asking System Events.
    if platform.system() != "Darwin":
        return False
    try:
        return subprocess.run(
            ["pgrep", "-x", CHROME], capture_output=True, timeout=5
        ).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _osascript(script: str, *args: str, timeout: int = 10) -> str:
    result = subprocess.run(
        ["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def open_youtube(url: str, new_tab: bool = False, host: str = "youtube.com", context: str = "", routed: bool = True) -> None:
    """Open a URL, reusing the existing tab on `host` unless a new one is requested.

    With Google accounts set up, the page goes to the Chrome profile of the right account (school for learning things,
    personal for the rest), see google_accounts.py; `context` is what the user asked for, which decides that.
    """
    if routed and google_accounts.route(url, new_tab, context):
        return
    if osal.IS_WIN:
        try:
            windows = [] if new_tab else _win_windows(host)
            if windows:
                _win_navigate(windows[0][0], url)
                return
        except (RuntimeError, OSError):
            pass
        webbrowser.open(url)
        return
    if platform.system() == "Darwin" and _chrome_running():
        if not new_tab:
            try:
                if _osascript(_REUSE_TAB, url, host) == "reused":
                    return
            except (subprocess.SubprocessError, OSError):
                pass
        # Open in Chrome itself so later pause/resume can find the tab.
        try:
            subprocess.run(["open", "-a", CHROME, url], check=True, timeout=10)
            return
        except (subprocess.SubprocessError, OSError):
            pass
    webbrowser.open(url)


def youtube_is_playing() -> bool:
    """True when a YouTube tab in Chrome has a video that is currently playing (not detectable on Windows)."""
    if not _chrome_running():
        return False
    try:
        out = _osascript(_RUN_JS, "var v=document.querySelector('video');(v&&!v.paused&&!v.ended)?'playing':'idle'")
    except (subprocess.SubprocessError, OSError):
        return False
    return out.startswith("ok:") and "playing" in out


def control_playback(action: str, seconds: int = None) -> str:
    """Pause, resume, restart or seek the video in Chrome. Returns a short spoken result."""
    if osal.IS_WIN:
        return _win_control(action, seconds)
    js = {
        "pause": "var v=document.querySelector('video');if(v)v.pause();'done'",
        "resume": "var v=document.querySelector('video');if(v)v.play();'done'",
        # Netflix errors out ("Pardon the interruption") if the video element is touched directly, so it is
        # restarted by reloading its own watch page at t=0. Other sites just seek the video.
        "restart": (
            "(function(){if(location.hostname.indexOf('netflix')>-1){"
            "if(location.pathname.indexOf('/watch/')===0){location.href=location.origin+location.pathname+'?t=0';}"
            "return 'done';}"
            "var v=document.querySelector('video');if(v){v.currentTime=0;v.play();}return 'done';})()"
        ),
        "next": ("var b=document.querySelector('.ytp-next-button');"
                 "if(b&&b.offsetParent!==null){b.click();'done'}else{'none'}"),
        "previous": ("var b=document.querySelector('.ytp-prev-button');"
                     "if(b&&b.offsetParent!==null){b.click();'done'}else{'none'}"),
        # Netflix again needs its own ?t= link; everywhere else the video element is seeked.
        "seek": (
            f"(function(){{var t={int(seconds or 0)};if(location.hostname.indexOf('netflix')>-1){{"
            "if(location.pathname.indexOf('/watch/')===0){location.href=location.origin+location.pathname+'?t='+t;}"
            "return 'done';}"
            "var v=document.querySelector('video');if(v){v.currentTime=t;}return 'done';})()"
        ),
    }[action]
    if not _chrome_running():
        return "I don't see a video playing in Chrome."
    try:
        status = _osascript(_RUN_JS, js)
    except (subprocess.SubprocessError, OSError) as e:
        return f"I couldn't reach Chrome: {e}"
    if status.startswith("ok:"):
        if action in ("next", "previous") and "done" not in status:
            return "There's no next video queued." if action == "next" else "There's no previous video to go back to."
        return {"pause": "Paused the video.", "resume": "Resuming the video.",
                "restart": "Starting it over from the beginning.",
                "next": "Skipping to the next video.", "previous": "Going back to the previous video.",
                "seek": f"Jumping to {int((seconds or 0) // 60)}:{int((seconds or 0) % 60):02d}."}[action]
    if status == "js-disabled":
        return ("I need permission to control Chrome. In Chrome, open View, Developer, "
                "and turn on Allow JavaScript from Apple Events.")
    return "I don't see a video playing in Chrome."


_TAB_ALIASES = {"docs": "google docs", "doc": "google docs", "sheets": "google sheets", "slides": "google slides",
                "mail": "gmail", "email": "gmail", "photos": "google photos", "calendar": "google calendar"}


def needles_for(target: str) -> list:
    """What to look for in a tab's address and title for a spoken name: "gmail" -> mail.google.com and "Gmail"."""
    import re
    t = _TAB_ALIASES.get(target.strip().lower(), target.strip().lower())
    needles = []
    if t == "google":  # only the Google search tab, not every google.com service
        return ["www.google.com/search", "- Google Search"]
    try:
        from app_launcher import SITES
        if t in SITES:
            needles.append(re.sub(r"^https?://(?:www\.)?", "", SITES[t]))
    except Exception:
        pass
    if _SITES.get(t):
        needles.append(_SITES[t])
    needles.append(t)
    return list(dict.fromkeys(n for n in needles if n))


def close_tabs(target: str = "", mode: str = "one") -> str:
    """Close browser tabs. target: a site or any word in a tab's title ("youtube", "gmail", "breaking bad"), or "" for the
    active tab. mode: one (a single match), all (every match), other (all but the active tab), everything."""
    if not target and mode == "one":
        mode = "active"
    if osal.IS_WIN:
        return _win_close_tabs(target, mode)
    if not _chrome_running():
        return "Chrome isn't open."
    args = [mode] + (needles_for(target) if mode in ("one", "all", "count") else [])
    try:
        closed = _osascript(_CLOSE_TABS, *args)
    except (subprocess.SubprocessError, OSError) as e:
        return f"I couldn't reach Chrome: {e}"
    if closed in ("", "0"):
        return f"I don't see a {target} tab open." if target else "There's no tab to close."
    count = int(closed) if closed.isdigit() else 1
    if mode in ("other", "everything"):
        return f"Closed {count} tab{'s' if count != 1 else ''}."
    label = f"{target} tab" if target else "tab"
    return f"Closed the {label}." if count == 1 else f"Closed {count} {target} tabs."


def open_in_site_tab(url: str, host: str, context: str = "") -> None:
    """Load a URL in the existing tab on `host` (new tab if there is none)."""
    open_youtube(url, new_tab=False, host=host, context=context)


def open_site(url: str, host: str, context: str = "") -> None:
    """Open a website, switching to a tab you already have on that host instead of duplicating it."""
    if google_accounts.route(url, new_tab=False, context=context or host):
        return
    if osal.IS_WIN:
        try:
            windows = _win_windows(host)
            if windows:
                winctl.focus(windows[0][0])
                return
        except (RuntimeError, OSError):
            pass
    if platform.system() == "Darwin" and _chrome_running():
        try:
            if _osascript(_FOCUS_TAB, host) == "focused":
                return
        except (subprocess.SubprocessError, OSError):
            pass
    open_youtube(url, new_tab=True, context=context or host)


def focus_tab(host: str) -> bool:
    """Bring the browser tab on `host` to the front. Returns False if there is none."""
    try:
        if osal.IS_WIN:
            windows = _win_windows(host)
            return bool(windows) and winctl.focus(windows[0][0])
        if _chrome_running():
            return _osascript(_FOCUS_TAB, host) == "focused"
    except (RuntimeError, OSError, subprocess.SubprocessError):
        pass
    return False
