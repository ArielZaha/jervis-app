"""Windows desktop control through ctypes only (no extra packages): media keys, key presses, window focus.

Everything here is Windows-only, but the module imports fine anywhere so other code can reference it.
"""
import ctypes
import platform
import time
from ctypes import wintypes

IS_WIN = platform.system() == "Windows"

VK = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "space": 0x20, "tab": 0x09, "esc": 0x1B,
    "home": 0x24, "left": 0x25, "right": 0x27,
    "play_pause": 0xB3, "next": 0xB0, "prev": 0xB1, "vol_up": 0xAF, "vol_down": 0xAE, "vol_mute": 0xAD,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)
# The rest of the keyboard, for computer control (screen_windows.py).
VK.update({"backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "up": 0x26, "down": 0x28, "pageup": 0x21,
           "pagedown": 0x22, "end": 0x23, "win": 0x5B, "escape": 0x1B, "capslock": 0x14,
           ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC,
           "]": 0xDD, "'": 0xDE})
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_EXTENDED = {VK["play_pause"], VK["next"], VK["prev"], VK["vol_up"], VK["vol_down"], VK["vol_mute"], VK["home"],
             VK["left"], VK["right"], VK["up"], VK["down"], VK["delete"], VK["insert"], VK["pageup"],
             VK["pagedown"], VK["end"], VK["win"]}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
SW_RESTORE = 9

# Titles of browser windows end with the browser's name; the tab title is the part before it.
BROWSER_SUFFIXES = ("Google Chrome", "Microsoft Edge", "Brave", "Mozilla Firefox", "Opera", "Vivaldi")


def _need_windows() -> None:
    if not IS_WIN:
        raise RuntimeError("This action only works on Windows.")


# ---------- keyboard ----------
class InputRefused(OSError):
    """Windows didn't take the key presses or clicks: the screen is locked, or the window in front runs as
    administrator while Jervis doesn't (Windows then protects it from other programs' input)."""


def _send(events: list, strict: bool = False) -> None:
    """Hand input events to Windows. strict: raise InputRefused if Windows didn't take them all (computer control
    must know; the older voice commands carry on as they always did)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    array = (_INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    if strict and sent != len(events):
        raise InputRefused(f"Windows took {sent} of {len(events)} input events (error {ctypes.get_last_error()}).")


def _key_event(vk: int, up: bool, strict: bool = False) -> None:
    flags = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    _send([_INPUT(type=1, ki=_KEYBDINPUT(vk, 0, flags, 0, 0))], strict)


def press(*names: str, strict: bool = False) -> None:
    """Press keys together, e.g. press("ctrl", "l") or press("space")."""
    _need_windows()
    codes = [VK[n] for n in names]
    try:
        for code in codes:
            _key_event(code, False, strict)
    finally:
        for code in reversed(codes):   # always let go, so no key is left held down
            _key_event(code, True)
    time.sleep(0.03)


def media_key(name: str) -> None:
    """name: play_pause, next, prev, vol_up, vol_down, vol_mute. Works for whatever app owns the media session."""
    press(name)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def type_text(text: str, strict: bool = False) -> None:
    """Type text into the focused window, any language (sends Unicode characters, not key codes)."""
    _need_windows()
    events = []
    for ch in text:
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):
            unit = units[i] | (units[i + 1] << 8)
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                events.append(_INPUT(type=1, ki=_KEYBDINPUT(0, unit, flags, 0, 0)))
    if events:
        _send(events, strict)
    time.sleep(0.05)


# ---------- mouse (computer control) ----------
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800


def make_dpi_aware() -> None:
    """Use real pixels everywhere, so positions read from the screen and positions clicked are the same numbers."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _mouse(flags: int, data: int = 0) -> None:
    _send([_INPUT(type=0, mi=_MOUSEINPUT(0, 0, data, flags, 0, 0))], strict=True)   # only computer control clicks


def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    _need_windows()
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else \
               (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    for _ in range(2 if double else 1):
        _mouse(down)
        _mouse(up)
        time.sleep(0.06)


def scroll(amount: int, x: int = None, y: int = None) -> None:
    """amount: positive scrolls up, negative down (in notches)."""
    _need_windows()
    if x is not None and y is not None:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    _mouse(MOUSEEVENTF_WHEEL, ctypes.c_uint32(int(amount) * 120).value)


def cursor_position() -> tuple:
    _need_windows()
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def window_process_name(hwnd: int) -> str:
    """The program a window belongs to, e.g. "chrome.exe" (lower case), or "" if it can't be read."""
    _need_windows()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return ""


def foreground_window() -> int:
    _need_windows()
    return ctypes.windll.user32.GetForegroundWindow()


def window_title(hwnd: int) -> str:
    _need_windows()
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


# ---------- windows ----------
def list_windows() -> list:
    """Visible top-level windows with a title, front-most first: [(hwnd, title)]."""
    _need_windows()
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return found


def is_browser_title(title: str) -> bool:
    return any(title.endswith(suffix) for suffix in BROWSER_SUFFIXES)


def find_windows(*needles: str, browsers_only: bool = True) -> list:
    """Windows whose title contains any needle (case-insensitive), front-most first."""
    lowered = [n.lower() for n in needles if n]
    return [(h, t) for h, t in list_windows()
            if (not browsers_only or is_browser_title(t)) and any(n in t.lower() for n in lowered)]


def focus(hwnd: int) -> bool:
    """Bring a window to the front. Windows blocks this for background apps unless an Alt key press comes first."""
    _need_windows()
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    _key_event(VK["alt"], False)
    _key_event(VK["alt"], True)
    ok = bool(user32.SetForegroundWindow(hwnd))
    time.sleep(0.25)
    return ok


def process_running(image_name: str) -> bool:
    """True if a process with this executable name is running (uses tasklist, which ships with Windows)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"], capture_output=True,
                             text=True, timeout=8, creationflags=0x08000000).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    return image_name.lower() in out.lower()
