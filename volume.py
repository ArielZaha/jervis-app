"""System volume control.

macOS: AppleScript, no extra permissions. Windows: the Windows audio API through the optional `pycaw` package (exact
levels, real mute state); without it the keyboard volume keys are pressed instead (each press is about 2 percent).
"""
import platform
import subprocess
import time

import winctl

STEP = 10


def _osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "osascript failed")
    return result.stdout.strip()


def _windows_endpoint():
    """The Windows master-volume control from pycaw, or None if pycaw isn't installed."""
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        speakers = AudioUtilities.GetSpeakers()
        if hasattr(speakers, "EndpointVolume"):  # newer pycaw
            return speakers.EndpointVolume
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def _windows_change(action: str, amount: int = None) -> str:
    endpoint = _windows_endpoint()
    if endpoint is not None:
        try:
            if action == "mute":
                endpoint.SetMute(1, None)
                return "Muted."
            current = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            if action == "unmute":
                endpoint.SetMute(0, None)
                return f"Unmuted. Volume is {current}%."
            if action == "up":
                level = current + (amount or STEP)
            elif action == "down":
                level = current - (amount or STEP)
            else:
                level = amount if amount is not None else current
            level = max(0, min(100, level))
            endpoint.SetMute(0, None)
            endpoint.SetMasterVolumeLevelScalar(level / 100, None)
            if action == "up" and level == current == 100:
                return "The volume is already at maximum."
            if action == "down" and level == current == 0:
                return "The volume is already at zero."
            return f"Volume {'up to' if action == 'up' else 'down to' if action == 'down' else 'set to'} {level}%."
        except Exception as e:
            return f"I couldn't change the volume: {e}"
    # No pycaw: press the keyboard volume keys (about 2 percent each).
    try:
        if action in ("mute", "unmute"):
            winctl.media_key("vol_mute")
            return "Toggled mute. For exact levels, install pycaw (pip install pycaw)."
        if action == "set":
            for _ in range(50):
                winctl.media_key("vol_down")
            for _ in range(round((amount or 0) / 2)):
                winctl.media_key("vol_up")
            return f"Volume set to about {amount}%."
        for _ in range(max(1, round((amount or STEP) / 2))):
            winctl.media_key("vol_up" if action == "up" else "vol_down")
            time.sleep(0.01)
        return "Volume up." if action == "up" else "Volume down."
    except (RuntimeError, OSError) as e:
        return f"I couldn't change the volume: {e}"


def change_volume(action: str, amount: int = None) -> str:
    """action: up, down, set, mute or unmute. Returns a short spoken result."""
    if platform.system() == "Windows":
        return _windows_change(action, amount)
    if platform.system() != "Darwin":
        return "Volume control only works on macOS and Windows for now."
    try:
        if action == "mute":
            _osascript("set volume with output muted")
            return "Muted."
        if action == "unmute":
            _osascript("set volume without output muted")
            return f"Unmuted. Volume is {int(_osascript('output volume of (get volume settings)'))}%."
        current = int(_osascript("output volume of (get volume settings)"))
        if action == "up":
            level = current + (amount or STEP)
        elif action == "down":
            level = current - (amount or STEP)
        else:
            level = amount if amount is not None else current
        level = max(0, min(100, level))
        _osascript(f"set volume without output muted\nset volume output volume {level}")
        if action == "up" and level == current == 100:
            return "The volume is already at maximum."
        if action == "down" and level == current == 0:
            return "The volume is already at zero."
        return f"Volume {'up to' if action == 'up' else 'down to' if action == 'down' else 'set to'} {level}%."
    except (RuntimeError, subprocess.SubprocessError, ValueError, OSError) as e:
        return f"I couldn't change the volume: {e}"
