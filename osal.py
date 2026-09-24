"""The few things Jervis does that differ per operating system, in one place: speech, notifications, chime, clipboard.

macOS uses the built-in tools (say, osascript, afplay, pbcopy). Windows uses PowerShell, which ships with every
Windows 10/11 (System.Speech for the voice, a toast for notifications, Set-Clipboard). Linux uses espeak / xclip when
they are installed.
"""
import base64
import os
import platform
import re
import shutil
import subprocess

SYSTEM = platform.system()
IS_MAC = SYSTEM == "Darwin"
IS_WIN = SYSTEM == "Windows"
IS_LINUX = SYSTEM == "Linux"

_NO_WINDOW = 0x08000000 if IS_WIN else 0  # don't flash a console window when running PowerShell


# ---------- macOS: never fork this process ----------
# Jervis runs many threads (microphone, network, timers). On macOS, fork()ing a multi-threaded process can crash the
# forked copy before it ever starts the program ("crashed on child side of fork pre-exec": Apple's networking library
# runs code in the child that isn't safe there). Python's subprocess forks by default, so every launch (say, osascript,
# open, ...) risked it. posix_spawn starts the program without forking, so this makes subprocess use it everywhere:
#   - the program is given as an absolute path and close_fds=False (Python's own file handles are already
#     non-inheritable, so nothing leaks into the new program);
#   - a working directory (`cwd`), which would force a fork, is applied by a tiny `sh` wrapper instead.
def _make_subprocess_fork_free() -> None:
    original_init = subprocess.Popen.__init__
    if getattr(original_init, "_jervis_fork_free", False):
        return

    def init(self, args, *pos, **kw):
        if not pos and not kw.get("shell") and isinstance(args, (list, tuple)) and args \
                and kw.get("executable") is None and not kw.get("preexec_fn") and not kw.get("pass_fds"):
            args = list(args)
            first = os.fspath(args[0])
            if not os.path.dirname(first):
                resolved = shutil.which(first)
                if resolved:
                    args[0] = resolved
            cwd = kw.get("cwd")
            if cwd is not None:
                kw["cwd"] = None
                args = ["/bin/sh", "-c", 'cd "$0" && exec "$@"', os.fspath(cwd), *args]
            kw.setdefault("close_fds", False)
        original_init(self, args, *pos, **kw)

    init._jervis_fork_free = True
    subprocess.Popen.__init__ = init


if IS_MAC:
    _make_subprocess_fork_free()
_HEBREW = re.compile(r"[֐-׿]")


def has_hebrew(text: str) -> bool:
    return bool(_HEBREW.search(text or ""))


# ---------- PowerShell ----------
def powershell_command(script: str) -> list:
    """argv that runs a script without any quoting problems (the script travels base64 encoded)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def run_powershell(script: str, env: dict = None, timeout: int = 30):
    """Run a PowerShell script. Text data goes in through `env` (read as $env:NAME), never pasted into the script."""
    merged = {**os.environ, **{k: str(v) for k, v in (env or {}).items()}}
    utf8 = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"  # so names and clipboard text in any language survive
    result = subprocess.run(powershell_command(utf8 + script), capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, env=merged, creationflags=_NO_WINDOW)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ---------- speech ----------
_WIN_SPEECH = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:JERVIS_HEBREW -eq '1') {
  foreach ($v in $s.GetInstalledVoices()) {
    if ($v.Enabled -and $v.VoiceInfo.Culture.Name -like 'he*') { $s.SelectVoice($v.VoiceInfo.Name); break }
  }
}
$s.Speak($env:JERVIS_TEXT)
"""


def speech_process(text: str):
    """Start speaking `text` and return the running process (so it can be stopped), or None if this machine can't."""
    if IS_MAC:
        voice = ["-v", "Carmit"] if has_hebrew(text) else []
        return subprocess.Popen(["say", *voice, text])
    if IS_WIN:
        env = {**os.environ, "JERVIS_TEXT": text, "JERVIS_HEBREW": "1" if has_hebrew(text) else "0"}
        return subprocess.Popen(powershell_command(_WIN_SPEECH), env=env, creationflags=_NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for tool in ("espeak-ng", "espeak", "spd-say"):
        if shutil.which(tool):
            return subprocess.Popen([tool, text])
    return None


# ---------- notification + chime ----------
_WIN_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
$text.Item(0).AppendChild($xml.CreateTextNode($env:JERVIS_TITLE)) | Out-Null
$text.Item(1).AppendChild($xml.CreateTextNode($env:JERVIS_MESSAGE)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


def notify(title: str, message: str) -> None:
    try:
        if IS_MAC:
            subprocess.run(
                ["osascript", "-e", "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run",
                 title, message], capture_output=True, timeout=5)
        elif IS_WIN:
            run_powershell(_WIN_TOAST, {"JERVIS_TITLE": title, "JERVIS_MESSAGE": message}, timeout=15)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass


def chime(times: int = 2) -> None:
    """A short system sound, used when a timer ends and the window can't play its own."""
    import time
    for _ in range(times):
        try:
            if IS_MAC:
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], timeout=10)
            elif IS_WIN:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
                time.sleep(0.9)
            else:
                print("\a", end="", flush=True)
                time.sleep(0.6)
        except (subprocess.SubprocessError, OSError, RuntimeError):
            return
        time.sleep(0.3)


# ---------- opening a file with its default app ----------
def open_path(path: str) -> None:
    if IS_MAC:
        subprocess.run(["open", path], check=True, timeout=10)
    elif IS_WIN:
        os.startfile(path)  # type: ignore[attr-defined]
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", path], check=True, timeout=10)
    else:
        raise RuntimeError("no way to open files on this system")


# ---------- clipboard ----------
def set_clipboard(text: str) -> None:
    """Copy text to the clipboard (any language)."""
    if IS_MAC:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), timeout=5)
    elif IS_WIN:
        run_powershell("Set-Clipboard -Value $env:JERVIS_TEXT", {"JERVIS_TEXT": text}, timeout=15)
    else:
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, input=text.encode("utf-8"), timeout=5)
                return
