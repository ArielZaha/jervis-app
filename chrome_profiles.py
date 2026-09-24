"""Find the Chrome profile a Google account is signed in to, and open a page in exactly that profile.

Chrome keeps each person / account in its own profile ("Default", "Profile 1", ...). A page opened without saying
which one lands in whichever profile was used last, under that profile's Google account. Launching Chrome with
--profile-directory hands the page to the right profile, even while Chrome is already running.
"""
import json
import os
import platform
import subprocess

SYSTEM = platform.system()


def user_data_dir():
    if SYSTEM == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if SYSTEM == "Windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    return os.path.expanduser("~/.config/google-chrome")


def chrome_binary():
    if SYSTEM == "Darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif SYSTEM == "Windows":
        candidates = [os.path.join(os.environ.get(v, ""), "Google", "Chrome", "Application", "chrome.exe")
                      for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    else:
        candidates = ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def profiles() -> dict:
    """{profile directory: [emails signed in to it]} (the sync account first)."""
    root = user_data_dir()
    info = _read_json(os.path.join(root, "Local State")).get("profile", {}).get("info_cache", {})
    result = {}
    for directory, details in info.items():
        emails = []
        if details.get("user_name"):
            emails.append(details["user_name"])
        for account in _read_json(os.path.join(root, directory, "Preferences")).get("account_info", []):
            email = account.get("email")
            if email and email not in emails:
                emails.append(email)
        result[directory] = emails
    return result


def find_profile(account: str):
    """The profile directory that has this Google account, preferring the one where it is the main account."""
    wanted = (account or "").strip().lower()
    found = profiles()
    for directory, emails in found.items():  # the profile whose main (sync) account it is
        if emails and emails[0].lower() == wanted:
            return directory
    for directory, emails in found.items():  # otherwise any profile that is signed in with it
        if wanted in [e.lower() for e in emails]:
            return directory
    return None


def open_in_profile(url: str, directory: str) -> bool:
    """Open a page in a new tab of that profile. Returns False if Chrome can't be started."""
    binary = chrome_binary()
    if not binary:
        return False
    try:
        subprocess.Popen([binary, f"--profile-directory={directory}", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# ---------- reusing the tab Jervis opened, per profile (macOS) ----------
# Chrome's AppleScript can't say which profile a window belongs to, so a plain "find the YouTube tab" could pick the other
# account's tab. Instead Jervis remembers the id of the tab it opened itself in each profile, and reuses exactly that one.
_SNAPSHOT = """tell application "Google Chrome"
    set out to ""
    repeat with w in windows
        repeat with t in tabs of w
            set out to out & (id of w) & ":" & (id of t) & " " & (URL of t) & linefeed
        end repeat
    end repeat
    return out
end tell"""
_GOTO = """on run argv
    set wid to item 1 of argv
    set tid to item 2 of argv
    set targetUrl to item 3 of argv
    tell application "Google Chrome"
        repeat with w in windows
            if ((id of w) as text) is wid then
                set i to 0
                repeat with t in tabs of w
                    set i to i + 1
                    if ((id of t) as text) is tid then
                        set URL of t to targetUrl
                        set active tab index of w to i
                        set index of w to 1
                        activate
                        return "ok"
                    end if
                end repeat
            end if
        end repeat
    end tell
    return "gone"
end run"""
_REVEAL = """on run argv
    set wid to item 1 of argv
    set tid to item 2 of argv
    tell application "Google Chrome"
        repeat with w in windows
            if ((id of w) as text) is wid then
                set i to 0
                repeat with t in tabs of w
                    set i to i + 1
                    if ((id of t) as text) is tid then
                        try
                            set minimized of w to false
                        end try
                        set active tab index of w to i
                        set index of w to 1
                        activate
                        return "ok"
                    end if
                end repeat
            end if
        end repeat
    end tell
    return "gone"
end run"""
_RUN_JS = """on run argv
    set wid to item 1 of argv
    set tid to item 2 of argv
    set js to item 3 of argv
    tell application "Google Chrome"
        repeat with w in windows
            if ((id of w) as text) is wid then
                repeat with t in tabs of w
                    if ((id of t) as text) is tid then
                        return (execute t javascript js) as text
                    end if
                end repeat
            end if
        end repeat
    end tell
    return "tab-gone"
end run"""
_owned_tabs = {}  # (profile, site) -> (window id, tab id)
last_tab = {"ids": None}  # the tab the most recent open_and_show created, for callers that want to read or navigate it


def site_key(host: str) -> str:
    """"www.youtube.com" -> "youtube.com"."""
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _osascript(script: str, *args: str, timeout: int = 10) -> str:
    result = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip() if result.returncode == 0 else ""


def tab_snapshot():
    """{(window id, tab id): url} of every open tab, or None where this can't be read (not macOS)."""
    if SYSTEM != "Darwin":
        return None
    tabs = {}
    for line in _osascript(_SNAPSHOT).splitlines():
        ids, _, url = line.partition(" ")
        window, _, tab = ids.partition(":")
        if window.isdigit() and tab.isdigit():
            tabs[(int(window), int(tab))] = url
    return tabs


def reuse_tab(profile: str, host: str, url: str) -> bool:
    """Send the tab Jervis opened earlier for this site in this profile to a new address. False if there is none."""
    ids = _owned_tabs.get((profile, site_key(host)))
    if not ids or SYSTEM != "Darwin":
        return False
    try:
        return _osascript(_GOTO, str(ids[0]), str(ids[1]), url) == "ok"
    except (subprocess.SubprocessError, OSError):
        return False


def find_new_tab(before, host: str, wait: float = 3.0):
    """(window id, tab id) of the tab that appeared after opening a page, or None. `before` is a tab_snapshot()."""
    import time
    if before is None:
        return None
    key = site_key(host)
    deadline = time.time() + wait
    while True:
        after = tab_snapshot() or {}
        new = {ids: url for ids, url in after.items() if ids not in before}
        match = [ids for ids, url in new.items() if key in url]
        if match or len(new) == 1:
            return (match or list(new))[-1]
        if time.time() >= deadline:
            return None
        time.sleep(0.25)


def reveal(ids) -> bool:
    """Bring a tab (and its window, even from another profile or minimized) to the front and make it the visible one."""
    if SYSTEM == "Darwin" and ids:
        try:
            return _osascript(_REVEAL, str(ids[0]), str(ids[1])) == "ok"
        except (subprocess.SubprocessError, OSError):
            pass
    return False


def bring_browser_forward() -> None:
    """Fallback when the new tab can't be identified: at least put the browser in front of Jervis's own window."""
    try:
        if SYSTEM == "Darwin":
            _osascript('tell application "Google Chrome" to activate')
        elif SYSTEM == "Windows":
            import time
            import winctl
            time.sleep(1.5)  # Chrome needs a moment to show its window
            windows = winctl.find_windows(*winctl.BROWSER_SUFFIXES)
            if windows:
                winctl.focus(windows[0][0])
    except (subprocess.SubprocessError, OSError, RuntimeError):
        pass


def open_and_show(url: str, profile: str, host: str, remember: bool = False) -> bool:
    """Open a page in a profile AND bring it into view: the tab that opened is found and raised to the front, so nobody
    has to hunt for the window. With remember=True the tab is kept for later reuse (sites like YouTube and Netflix)."""
    before = tab_snapshot()
    if not open_in_profile(url, profile):
        return False
    ids = find_new_tab(before, host)
    last_tab["ids"] = ids
    if ids and remember:
        _owned_tabs[(profile, site_key(host))] = ids
    if not reveal(ids):
        bring_browser_forward()
    return True


def run_js(ids, script: str, timeout: int = 20) -> tuple:
    """Run JavaScript in a specific tab. Returns (True, result text) or (False, reason).

    Chrome only allows this if View > Developer > Allow JavaScript from Apple Events is switched on (it is a
    per-profile setting), so a refusal is reported as reason "js-disabled"."""
    if SYSTEM != "Darwin" or not ids:
        return False, "unsupported"
    try:
        result = subprocess.run(["osascript", "-e", _RUN_JS, str(ids[0]), str(ids[1]), script],
                                capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:
        return False, str(e)
    if result.returncode != 0:
        error = result.stderr.lower()
        if "javascript" in error and ("turned off" in error or "apple events" in error):
            return False, "js-disabled"
        return False, result.stderr.strip()[:200]
    value = result.stdout.strip()
    return (False, "tab-gone") if value == "tab-gone" else (True, value)


def goto(ids, url: str) -> bool:
    """Send a specific tab to another address (and keep it in view)."""
    if SYSTEM != "Darwin" or not ids:
        return False
    try:
        return _osascript(_GOTO, str(ids[0]), str(ids[1]), url) == "ok"
    except (subprocess.SubprocessError, OSError):
        return False
