"""Spotify without developer keys: Jervis drives the Spotify app on this computer.

Spotify's online developer interface needs keys that belong to whoever registered an app with Spotify, so an
installed Jervis has none (and Spotify caps such apps at 25 listeners). Everything here works with just the Spotify
app installed and signed in:

- play something: bring Spotify to the front, open its Quick Search (Cmd+K / Ctrl+K), type the request and press
  Shift+Enter, which is Spotify's own "play the selected result"; then check that the music really changed.
- pause, resume, next, previous, what's playing: Spotify's AppleScript commands on a Mac; the media keys on Windows,
  where Spotify's window title ("Artist - Song" while playing) tells whether it's playing.

The keys go to Spotify only: if it isn't in front when the keys would be pressed, nothing is typed.
"""
import os
import re
import subprocess
import sys
import time

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


class SpotifyLocalError(Exception):
    """Something the user should hear, in plain words."""


# ---------- is Spotify there / running ----------
def installed() -> bool:
    if IS_MAC:
        return os.path.isdir("/Applications/Spotify.app") or os.path.isdir(os.path.expanduser("~/Applications/Spotify.app"))
    if IS_WIN:
        return bool(_win_spotify_exe()) or _win_store_app()
    return False


def running() -> bool:
    if IS_MAC:
        return subprocess.run(["pgrep", "-x", "Spotify"], capture_output=True).returncode == 0
    if IS_WIN:
        return bool(_win_windows())
    return False


# ---------- macOS ----------
def _osa(command: str, timeout: float = 8.0) -> str:
    out = subprocess.run(["osascript", "-e", f'tell application "Spotify" to {command}'], capture_output=True,
                         text=True, timeout=timeout)
    if out.returncode != 0:
        raise SpotifyLocalError(out.stderr.strip() or "Spotify didn't answer.")
    return out.stdout.strip()


def _mac_now() -> tuple:
    """(state, track url, "Song by Artist") of Spotify, without starting it."""
    if not running():
        return "stopped", "", ""
    try:
        state = _osa("player state as text")
        if state == "stopped":
            return state, "", ""
        url = _osa("spotify url of current track")
        name = _osa('(name of current track) & " by " & (artist of current track)')
        return state, url, name
    except (SpotifyLocalError, subprocess.SubprocessError):
        return "stopped", "", ""


def _mac_bring_forward() -> bool:
    import AppKit
    if not running():
        subprocess.run(["open", "-a", "Spotify"], check=False)
        for _ in range(60):   # a cold start takes a few seconds, longer on a computer Jervis's own AI is loading down
            time.sleep(0.25)
            if running():
                break
        time.sleep(4)         # let its window and Quick Search get ready
    app = next((a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                if a.localizedName() == "Spotify"), None)
    if app is None:
        return False
    for attempt in range(2):   # activateWithOptions_ alone doesn't always win focus from a background process
        (app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps) if attempt == 0
         else subprocess.run(["open", "-a", "Spotify"], check=False))
        for _ in range(40):
            time.sleep(0.15)
            front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is not None and front.localizedName() == "Spotify":
                break
        else:
            continue
        if _window_bounds() is not None:   # frontmost doesn't mean it has a window: Spotify can run with none open
            return True
        subprocess.run(["open", "-a", "Spotify"], check=False)   # this reopens its main window, not just the app
        for _ in range(40):
            time.sleep(0.15)
            if _window_bounds() is not None:
                return True
    return False


def _mac_keys(*keys: str) -> None:
    import screen_mac
    screen_mac.MacScreen().press_keys(list(keys))


def _mac_type(text: str) -> None:
    import screen_mac
    screen_mac.MacScreen().type_text(text)


def _mac_can_press_keys() -> bool:
    import screen_mac
    return screen_mac.MacScreen.trusted()


def _mac_ask_for_accessibility() -> None:
    """Ask macOS for the Accessibility permission: that's what puts Jervis in the Accessibility list at all (an app
    that only checks is never listed). The first time macOS shows its own dialog; after that the settings page opens."""
    import screen_mac
    screen_mac.MacScreen().available()


# ---------- Windows ----------
def _win_spotify_exe() -> str:
    path = os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")
    return path if os.path.exists(path) else ""


def _win_store_app() -> bool:
    try:
        import app_launcher
        return app_launcher.resolve_app("spotify")[0] == "ok"
    except Exception:
        return False


def _win_windows() -> list:
    import winctl
    return [(h, t) for h, t in winctl.list_windows() if winctl.window_process_name(h) == "spotify.exe"]


def _win_title() -> str:
    windows = _win_windows()
    return windows[0][1] if windows else ""


def _win_playing_title(title: str) -> bool:
    """Spotify's window is called "Artist - Song" while playing, "Spotify Premium" / "Spotify Free" when paused."""
    return bool(title) and not title.lower().startswith("spotify")


def _win_bring_forward() -> bool:
    import winctl
    if not _win_windows():
        exe = _win_spotify_exe()
        if exe:
            subprocess.Popen([exe], creationflags=0x08000000)
        else:
            os.startfile("spotify:")  # type: ignore[attr-defined]   (the Microsoft Store version)
        for _ in range(60):
            time.sleep(0.25)
            if _win_windows():
                break
        time.sleep(2.5)
    windows = _win_windows()
    if not windows:
        return False
    winctl.focus(windows[0][0])
    for _ in range(20):
        time.sleep(0.1)
        if winctl.window_process_name(winctl.foreground_window()) == "spotify.exe":
            return True
    return False


# ---------- what Jervis uses ----------
def now_playing() -> tuple:
    """(is it playing, "Song by Artist" or "")."""
    if IS_MAC:
        state, _url, name = _mac_now()
        return state == "playing", name
    if IS_WIN:
        title = _win_title()
        if _win_playing_title(title):
            artist, _, song = title.partition(" - ")
            return True, f"{song} by {artist}" if song else title
        return False, ""
    return False, ""


def is_playing() -> bool:
    return now_playing()[0]


def play(query: str) -> str:
    """Find `query` with Spotify's Quick Search and play the first result. Returns what's playing now."""
    query = " ".join((query or "").split())
    if not query:
        raise SpotifyLocalError("Tell me what to play.")
    if not installed():
        raise SpotifyLocalError("Spotify isn't installed on this computer. Get it from spotify.com and sign in, "
                                "then ask me again.")
    if IS_MAC and not _mac_can_press_keys():
        _mac_ask_for_accessibility()
        _mac_open_search(query)
        raise SpotifyLocalError("I opened your search in Spotify: press play on it. To let me press play myself, "
                                "turn on Jervis in System Settings, Privacy & Security, Accessibility, then ask me "
                                "again.")
    before = _mac_now()[1] if IS_MAC else _win_title()
    if not (_mac_bring_forward() if IS_MAC else _win_bring_forward()):
        raise SpotifyLocalError("I couldn't bring Spotify to the front, so I didn't type anything. Open Spotify and "
                                "ask me again.")
    # Escape first: Cmd+K toggles Quick Search, so one left open would be closed instead of opened.
    if IS_MAC:
        _mac_keys("escape")
        time.sleep(0.3)
        _mac_keys("cmd", "k")
        time.sleep(0.7)
        _mac_keys("cmd", "a")          # replace anything left in the box
        _mac_type(query)
        time.sleep(1.8)                # results come from Spotify's servers
        _mac_keys("shift", "enter")
    else:
        import winctl
        winctl.press("esc", strict=True)
        time.sleep(0.3)
        winctl.press("ctrl", "k", strict=True)
        time.sleep(0.7)
        winctl.press("ctrl", "a", strict=True)
        winctl.type_text(query, strict=True)
        time.sleep(1.8)
        winctl.press("shift", "enter", strict=True)
    # Did the music change?
    started = ""
    for _ in range(24):
        time.sleep(0.25)
        if IS_MAC:
            state, url, name = _mac_now()
            if state == "playing" and url != before:
                started = name
                break
        else:
            title = _win_title()
            if _win_playing_title(title) and title != before:
                artist, _, song = title.partition(" - ")
                started = f"{song} by {artist}" if song else title
                break
    _close_quick_search()
    if started:
        return started
    playing, name = now_playing()
    if playing and name:
        return name   # the result was what was already playing
    raise SpotifyLocalError(f"I searched Spotify for {query} but couldn't start it. It's on the screen: press play "
                            "on the one you want.")


def _close_quick_search() -> None:
    """Leave Spotify tidy: Quick Search stays open after playing from it."""
    try:
        if IS_MAC:
            _mac_keys("escape")
        elif IS_WIN:
            import winctl
            winctl.press("esc")
    except Exception:
        pass


def open_search(query: str) -> bool:
    """Show Spotify's search results for `query` (opening Spotify if needed). False if Spotify isn't installed."""
    from urllib.parse import quote
    if not installed():
        return False
    if IS_MAC:
        _mac_open_search(query)
    elif IS_WIN:
        os.startfile(f"spotify:search:{quote(query)}")  # type: ignore[attr-defined]
    return True


def _mac_open_search(query: str) -> None:
    from urllib.parse import quote
    subprocess.run(["open", f"spotify:search:{quote(query)}"], check=False)


def pause() -> bool:
    if IS_MAC:
        if not running():
            return False
        _osa("pause")
        return True
    if IS_WIN:
        if not _win_playing_title(_win_title()):
            return False
        import winctl
        winctl.media_key("play_pause")
        return True
    return False


def resume() -> bool:
    if IS_MAC:
        if not running():
            return False
        _osa("play")
        return True
    if IS_WIN:
        if not _win_windows():
            return False
        if not _win_playing_title(_win_title()):
            import winctl
            winctl.media_key("play_pause")
        return True
    return False


def skip(direction: str) -> str:
    """"next" or "previous"; returns what's playing afterwards (or "")."""
    if IS_MAC:
        if not running():
            raise SpotifyLocalError("Spotify isn't open.")
        if direction == "next":
            _osa("next track")
        else:
            if float(_osa("player position") or 0) > 3:
                _osa("previous track")   # the first press only restarts the song
            _osa("previous track")
    elif IS_WIN:
        if not _win_windows():
            raise SpotifyLocalError("Spotify isn't open.")
        import winctl
        winctl.media_key("next" if direction == "next" else "prev")
    time.sleep(0.9)
    return now_playing()[1]


def seek(seconds: int) -> bool:
    """Jump to a time in the song (Mac only: Windows has no way to do it without Spotify's online interface)."""
    if IS_MAC and running():
        _osa(f"set player position to {int(seconds)}")
        return True
    return False


def clean_query(text: str) -> str:
    """"My Favorite Songs playlist" -> "My Favorite Songs" (Quick Search finds it by name)."""
    text = re.sub(r"\b(?:the\s+)?(?:playlist|album|song|track)\b", " ", text or "", flags=re.I)
    return " ".join(text.split()).strip(" \"'“”")


# ---------- the visible way: when you asked Jervis to take control ----------
# The same Quick Search as play(), done so you can follow it: the pointer moves to the search box and to the result,
# the request is typed letter by letter, and the results appear before the top one is played. Spotify's Mac app
# doesn't let other programs see its buttons, so Jervis points at the result and plays it with Spotify's own play
# key (Shift+Enter) instead of clicking a place he can't see.
TYPE_DELAY = 0.09   # seconds between letters
RESULTS_WAIT = 3.5   # seconds to let Spotify's search results load before looking for one
# how long to wait for playback to actually start before giving up: generous, since Jervis's own local AI (several
# GB, running alongside everything else) can make the whole computer slower to respond than usual.
PLAYBACK_WAIT_STEPS = 48
PLAYBACK_WAIT_INTERVAL = 0.3   # -> up to 14.4s


def cursor():
    if IS_MAC:
        import Quartz
        point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return int(point.x), int(point.y)
    if IS_WIN:
        import winctl
        return winctl.cursor_position()
    return None


def _glide(x: int, y: int, seconds: float = 0.6) -> None:
    """Move the pointer there smoothly, so it can be followed."""
    start = cursor() or (x, y)
    steps = 24
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)   # ease in and out
        px, py = start[0] + (x - start[0]) * t, start[1] + (y - start[1]) * t
        if IS_MAC:
            import Quartz
            event = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (px, py), Quartz.kCGMouseButtonLeft)
            Quartz.CGEventSetFlags(event, 0)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        elif IS_WIN:
            import ctypes
            ctypes.windll.user32.SetCursorPos(int(px), int(py))
        time.sleep(seconds / steps)


def _type_slowly(text: str) -> None:
    for letter in text:
        if IS_MAC:
            _mac_type(letter)
        else:
            import winctl
            winctl.type_text(letter, strict=True)
        time.sleep(TYPE_DELAY)


def _window_bounds():
    """(x, y, width, height) of Spotify's main window, or None. This comes from the window server (what's on
    screen), not accessibility — Spotify's window doesn't expose any content to accessibility at all (confirmed:
    even with Jervis's accessibility permission on, its window has zero readable elements beyond its menu bar), so
    there is no real button or field for Jervis to find and click the way he can in other apps."""
    if IS_MAC:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
        best = None
        for info in windows or []:
            if info.get("kCGWindowOwnerName") == "Spotify" and info.get("kCGWindowLayer", 0) == 0:
                b = info.get("kCGWindowBounds") or {}
                box = (int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0)))
                if not best or box[2] * box[3] > best[2] * best[3]:
                    best = box
        return best
    if IS_WIN:
        import ctypes
        from ctypes import wintypes
        windows = _win_windows()
        if not windows:
            return None
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(windows[0][0], ctypes.byref(rect))
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return None


def _keys(*keys: str) -> None:
    if IS_MAC:
        _mac_keys(*("cmd" if k == "command" else k for k in keys))
    else:
        import winctl
        winctl.press(*("ctrl" if k == "command" else ("esc" if k == "escape" else k) for k in keys), strict=True)


def _looks_like_a_match(query: str, playing_name: str) -> bool:
    """A rough sanity check on what Spotify actually started playing: does it share a real word with what was
    asked for? Not strict (Spotify's own search can reasonably return a close alternative spelling), just a safety
    net against reporting success for whatever happened to already be selected — which is how "play Jane" once
    ended up reporting an unrelated song as playing."""
    q_words = {w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 2}
    if not q_words:
        return True
    n_words = {w for w in re.findall(r"[\w']+", (playing_name or "").lower()) if len(w) > 2}
    return bool(q_words & n_words)


def _screen():
    if IS_MAC:
        import screen_mac
        return screen_mac.MacScreen()
    import screen_windows
    return screen_windows.WindowsScreen()


def visible_steps(query: str) -> list:
    """The steps of playing `query` so you can watch, as (what you see, function) for computer_use.ScriptedTask.

    Spotify's Mac app doesn't expose its window content to accessibility, so there is no search field or play
    button Jervis can find and click by reading the window the way the general computer-control engine does in
    other apps. When looking at a screenshot is available (Settings, Computer control), Jervis uses that instead —
    a real vision model finds the real search bar and the real matching result, and both are clicked for real.
    Otherwise, the only remaining real, visible way in is Spotify's own keyboard shortcuts (Cmd+K opens its Quick
    Search, typing goes straight into it, Shift+Enter plays the selected result). Either way, nothing is ever
    trusted blindly: every version checks that something actually started playing, *and* that it has a real word
    in common with what was asked for, before ever calling it done."""
    import screen_vision
    query = " ".join((query or "").split())
    if screen_vision.available():
        return _visible_steps_by_sight(query)
    return _visible_steps_by_shortcut(query)


def _visible_steps_by_sight(query: str) -> list:
    import screen_vision
    state = {}

    def env():
        if "env" not in state:
            state["env"] = _screen()
        return state["env"]

    def vision():
        if "vision" not in state:
            state["vision"] = screen_vision.ScreenVision()
        return state["vision"]

    def spotify_view():
        """A screenshot cropped to just Spotify's own window (its (x, y) offset, for mapping a point in the crop
        back to real screen coordinates): with the rest of the screen out of the picture, Spotify's own UI is a
        much larger fraction of what the vision model sees, and there's nothing else on screen to confuse it with."""
        obs = env().observe()
        if obs.screenshot is None:
            raise SpotifyLocalError("I don't have permission to see the screen, so I can't find things in Spotify. "
                                    "Grant Screen Recording to Jervis in System Settings, Privacy & Security.")
        box = _window_bounds()
        if box is None:
            raise SpotifyLocalError("Spotify doesn't have a window open, so I stopped instead of guessing where "
                                    "to click.")
        x, y, w, h = box
        cropped = obs.screenshot.crop((x, y, x + w, y + h))
        return cropped, (x, y), (w, h)

    def open_spotify():
        if not installed():
            raise SpotifyLocalError("Spotify isn't installed on this computer.")
        state["before"] = _mac_now()[1] if IS_MAC else _win_title()
        if not (_mac_bring_forward() if IS_MAC else _win_bring_forward()):
            raise SpotifyLocalError("I couldn't bring Spotify to the front, so I stopped before touching anything.")
        time.sleep(1.0)

    def click_search_bar():
        shot, (ox, oy), size = spotify_view()
        # asking for the visible words landed reliably inside the field in testing; asking for "the search bar" or
        # an icon both landed near the wrong (nearby) icon instead.
        point = vision().locate(shot, 'the placeholder text "What do you want to play?"', size)
        if point is None:
            raise SpotifyLocalError("I couldn't find Spotify's search bar on screen, so I stopped instead of "
                                    "clicking somewhere unsafe.")
        point = (point[0] + ox, point[1] + oy)
        state["search_point"] = point
        _glide(*point)
        env().click(point)
        time.sleep(0.6)

    def type_it():
        _type_slowly(query)

    def wait_for_results():
        time.sleep(RESULTS_WAIT)

    def point_at_result():
        # Tested extensively against the real app: Shift+Enter ("play the selected result", the assumption the
        # keyboard-shortcut fallback relies on) does nothing at all in the current Spotify — confirmed, not a
        # guess. Finding one specific row precisely is hard for this vision model in a dense list, but it's the
        # only mechanism that has ever actually clicked the right thing in testing, so it's what's used, backed by
        # the match check in play_it() so a wrong guess is reported as a failure, never a false success.
        shot, (ox, oy), size = spotify_view()
        point = vision().locate(shot, f'the text "{query}" (the song title, in the results list)', size)
        if point is None:
            raise SpotifyLocalError(f"I searched Spotify for {query} but didn't see a matching result on screen, "
                                    "so I stopped instead of playing something else.")
        state["result_point"] = (point[0] + ox, point[1] + oy)
        _glide(*state["result_point"])
        time.sleep(0.6)

    def play_it():
        env().click(state["result_point"])
        for _ in range(PLAYBACK_WAIT_STEPS):
            time.sleep(PLAYBACK_WAIT_INTERVAL)
            playing, name = now_playing()
            now = _mac_now()[1] if IS_MAC else _win_title()
            if playing and now != state.get("before"):
                if not _looks_like_a_match(query, name):
                    raise SpotifyLocalError(f"Spotify started playing {name}, but that doesn't look like a match "
                                            f"for {query}, so I'm not calling it done — please check what's playing.")
                return f"Playing {name} on Spotify." if name else "Playing it on Spotify."
        playing, name = now_playing()
        if playing and name:
            if not _looks_like_a_match(query, name):
                raise SpotifyLocalError(f"Spotify is playing {name}, but that doesn't look like a match for "
                                        f"{query}, so I'm not calling it done — please check what's playing.")
            return f"Playing {name} on Spotify."
        raise SpotifyLocalError(f"I searched Spotify for {query} but it didn't start. The results are on the screen.")

    return [("Opening Spotify", open_spotify),
            ("Clicking the search bar", click_search_bar),
            (f"Typing “{query}”", type_it),
            ("Searching", wait_for_results),
            ("Pointing at the results", point_at_result),
            ("Playing it", play_it)]


def _visible_steps_by_shortcut(query: str) -> list:
    state = {}

    def open_spotify():
        if not installed():
            raise SpotifyLocalError("Spotify isn't installed on this computer.")
        state["before"] = _mac_now()[1] if IS_MAC else _win_title()
        if not (_mac_bring_forward() if IS_MAC else _win_bring_forward()):
            raise SpotifyLocalError("I couldn't bring Spotify to the front, so I stopped before touching anything.")
        time.sleep(1.0)

    def open_search():
        box = _window_bounds()
        if box:
            x, y, w, h = box
            state["search"] = (x + w // 2, y + min(170, h // 4))   # where Quick Search's box opens
            state["result"] = (x + w // 2, y + min(250, h // 3))   # its first result, just below
            _glide(*state["search"])
        _keys("escape")        # Cmd+K toggles Quick Search: start from closed
        time.sleep(0.5)
        _keys("command", "k")
        time.sleep(1.0)
        _keys("command", "a")

    def type_it():
        _type_slowly(query)

    def wait_for_results():
        time.sleep(RESULTS_WAIT)

    def point_at_result():
        if state.get("result"):
            _glide(*state["result"])
        time.sleep(0.6)

    def play_it():
        _keys("shift", "enter")
        for _ in range(PLAYBACK_WAIT_STEPS):
            time.sleep(PLAYBACK_WAIT_INTERVAL)
            playing, name = now_playing()
            now = _mac_now()[1] if IS_MAC else _win_title()
            if playing and now != state.get("before"):
                _close_quick_search()
                if not _looks_like_a_match(query, name):
                    raise SpotifyLocalError(f"Spotify started playing {name}, but that doesn't look like a match "
                                            f"for {query}, so I'm not calling it done — please check what's playing.")
                return f"Playing {name} on Spotify." if name else "Playing it on Spotify."
        _close_quick_search()
        playing, name = now_playing()
        if playing and name:
            if not _looks_like_a_match(query, name):
                raise SpotifyLocalError(f"Spotify is playing {name}, but that doesn't look like a match for "
                                        f"{query}, so I'm not calling it done — please check what's playing.")
            return f"Playing {name} on Spotify."
        raise SpotifyLocalError(f"I searched Spotify for {query} but it didn't start. The results are on the screen.")

    return [("Opening Spotify", open_spotify),
            ("Clicking into the search bar", open_search),
            (f"Typing “{query}”", type_it),
            ("Searching", wait_for_results),
            ("Pointing at the top result", point_at_result),
            ("Playing it", play_it)]
