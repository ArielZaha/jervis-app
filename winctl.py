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
_EXTENDED = {VK["play_pause"], VK["next"], VK["prev"], VK["vol_up"], VK["vol_down"], VK["vol_mute"], VK["home"],
             VK["left"], VK["right"]}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
SW_RESTORE = 9

# Titles of browser windows end with the browser's name; the tab title is the part before it.
BROWSER_SUFFIXES = ("Google Chrome", "Microsoft​ Edge", "Microsoft Edge", "Brave", "Mozilla Firefox", "Opera", "Vivaldi")


def _need_windows() -> None:
    if not IS_WIN:
        raise RuntimeError("This action only works on Windows.")


# ---------- keyboard ----------
def _key_event(vk: int, up: bool) -> None:
    flags = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    ctypes.windll.user32.keybd_event(vk, 0, flags, 0)


def press(*names: str) -> None:
    """Press keys together, e.g. press("ctrl", "l") or press("space")."""
    _need_windows()
    codes = [VK[n] for n in names]
    for code in codes:
        _key_event(code, False)
    for code in reversed(codes):
        _key_event(code, True)
    time.sleep(0.03)


def media_key(name: str) -> None:
    """name: play_pause, next, prev, vol_up, vol_down, vol_mute. Works for whatever app owns the media session."""
    press(name)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):  # only here so the union has its real size
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def type_text(text: str) -> None:
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
        array = (_INPUT * len(events))(*events)
        ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    time.sleep(0.05)


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
