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
        for _ in range(40):   # a cold start takes a few seconds
            time.sleep(0.25)
            if running():
                break
        time.sleep(2.5)       # let its window and Quick Search get ready
    app = next((a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                if a.localizedName() == "Spotify"), None)
    if app is None:
        return False
    app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    for _ in range(20):
        time.sleep(0.1)
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None and front.localizedName() == "Spotify":
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
