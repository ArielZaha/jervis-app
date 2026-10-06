"""Jarvis's side of the Blender bridge (see blender_bridge.py, which runs *inside* Blender): finding Blender's real
exe, launching it with the bridge script so it can run Python from the moment it opens, and sending it code to run.
"""
import json
import os
import re
import subprocess
import sys
import time

import app_launcher
import blender_bridge

LAUNCH_SECONDS = 60
RUN_TIMEOUT = 20
RESTART_GRACE_SECONDS = 10   # a Blender just opened with the bridge may still be starting up; see ensure_bridge
_next_id = [0]


class BlenderBridge:
    """A Blender process that was launched with blender_bridge.py, so it executes Python Jarvis sends it and
    answers back through the same two files blender_bridge.py reads and writes."""

    def run(self, code: str, timeout: float = RUN_TIMEOUT) -> dict:
        """Send `code` to Blender's own Python and wait for the result: {"ok", "output", "error"}."""
        _next_id[0] += 1
        request_id = _next_id[0]
        os.makedirs(blender_bridge.BRIDGE_DIR, exist_ok=True)
        try:
            os.remove(blender_bridge.RESPONSE_FILE)   # never read a stale answer as if it were this request's
        except OSError:
            pass
        blender_bridge._write_json_atomic(blender_bridge.REQUEST_FILE, {"id": request_id, "code": code})
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self._read_response()
            if response and response.get("id") == request_id:
                return response
            time.sleep(0.1)
        return {"ok": False, "output": "", "error": "Blender didn't answer in time."}

    def ping(self, timeout: float = 3.0) -> bool:
        response = self.run("RESULT = 'pong'", timeout=timeout)
        return bool(response.get("ok")) and response.get("output", "").strip() == "pong"

    @staticmethod
    def _read_response():
        try:
            with open(blender_bridge.RESPONSE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except ValueError:   # caught Blender's own write mid-replace: the next poll a moment later will see it fine
            return None
        except OSError:
            return None


STARTUP_SCRIPT_NAME = "jarvis_bridge.py"


def _blender_config_root() -> str:
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Blender")
    return os.path.expanduser("~/.config/blender")


def install_startup_script(root: str = None, versions=()) -> int:
    """Put the bridge in each Blender version's startup scripts folder, so Blender runs it every time it opens —
    from the Start menu, a .blend file, anywhere — and Jarvis never has to restart Blender to reach it. Returns how
    many versions have it now."""
    root = root or _blender_config_root()
    found = set(versions)
    if os.path.isdir(root):
        found |= {d for d in os.listdir(root) if re.fullmatch(r"\d+\.\d+", d)}
    if not versions:
        status, value = app_launcher.resolve_app("blender")
        for name in ([value] if status == "ok" else list(value or []) if status == "ambiguous" else []):
            match = re.search(r"\d+\.\d+", name)
            if match:
                found.add(match.group(0))
    with open(blender_bridge.__file__, "r", encoding="utf-8") as f:
        source = f.read()
    installed = 0
    for version in found:
        path = os.path.join(root, version, "scripts", "startup", STARTUP_SCRIPT_NAME)
        try:
            current = None
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    current = f.read()
            if current != source:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(source)
            installed += 1
        except OSError:
            pass
    return installed


def blender_running() -> bool:
    return bool(app_launcher.app_windows("Blender"))


def _blender_display_name() -> str:
    """Which installed Blender to launch when the goal didn't say a version. Picking one here (rather than asking)
    is fine: _which_app_first already asks "4.3 or 4.5?" earlier in the flow when the user said "open Blender"
    explicitly, before this is ever reached for a fresh launch."""
    status, value = app_launcher.resolve_app("blender")
    if status == "ok":
        return value
    if status == "ambiguous" and value:
        return max(value)   # "Blender 4.5" > "Blender 4.3": good enough to prefer the newer one
    return "Blender"


def launch_with_bridge(confirm_seconds: float = LAUNCH_SECONDS):
    """Start Blender directly (bypassing the Start menu) with --python blender_bridge.py, so the bridge is running
    from the moment its window appears. Returns a ready BlenderBridge, or None if it couldn't be started/confirmed.

    Never opens a second Blender: the request/response files are shared by whichever one process is running, so
    two at once would collide on them. If one is already open, this brings it forward and tries to attach to
    whatever bridge it already has instead — None if it has none (the caller, ensure_bridge, asks before
    restarting; a plain "open Blender" just leaves it focused either way)."""
    if blender_running():
        windows = app_launcher.app_windows("Blender")
        if windows:
            import winctl
            winctl.focus(windows[0][0])
        bridge = BlenderBridge()
        deadline = time.time() + min(confirm_seconds, RESTART_GRACE_SECONDS)
        while time.time() < deadline:
            if bridge.ping(timeout=2):
                return bridge
            time.sleep(0.5)
        return None
    exe = app_launcher.program_path(_blender_display_name())
    if not exe or not os.path.exists(exe):
        return None
    before = app_launcher._window_handles()
    try:
        subprocess.Popen([exe, "--python", os.path.abspath(blender_bridge.__file__)])
    except OSError:
        return None
    opened = app_launcher._wait_for_app_window("Blender", before, confirm_seconds)
    if not opened or opened == "broken":
        return None
    bridge = BlenderBridge()
    deadline = time.time() + confirm_seconds
    while time.time() < deadline:
        if bridge.ping(timeout=2):
            return bridge
        time.sleep(0.5)
    return None


def ensure_bridge(session, confirm):
    """Make sure a BlenderBridge is ready to use for this session: reuse one that still answers, launch Blender
    fresh if it isn't running at all, or ask before restarting it if it's already open without the bridge (that
    would lose unsaved work). `confirm(question) -> bool` is the existing yes/no voice confirmation. Returns the
    bridge, or None if Blender couldn't be reached (caller falls back to plain mouse/keyboard control)."""
    if session.blender and session.blender.ping():
        return session.blender
    if not blender_running():
        session.blender = launch_with_bridge()
        return session.blender
    # Blender may have just been opened (with the bridge) and still be starting up: give it a few seconds before
    # concluding it has no bridge at all and asking to restart it.
    probe = BlenderBridge()
    deadline = time.time() + RESTART_GRACE_SECONDS
    while time.time() < deadline:
        if probe.ping(timeout=2):
            session.blender = probe
            return probe
        time.sleep(1)
    if not confirm("Blender's open without my scripting bridge. I'd need to restart it to build things with code, "
                   "and any unsaved work in it would be lost. Restart it?"):
        return None
    app_launcher.close_application("Blender")
    time.sleep(1.5)
    session.blender = launch_with_bridge()
    return session.blender
