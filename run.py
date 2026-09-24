#!/usr/bin/env python3
"""Start Jervis on macOS or Windows with one command:   python run.py

The first run sets everything up (a private Python environment, the Python packages, the window's Node packages) and
creates a .env file to fill in. After that it just starts Jervis, and its window opens right away.
"""
import os
import shutil
import subprocess
import sys

VERSION = "1.0.0"  # printed at start, so it is obvious which copy of Jervis is running
ROOT = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform == "win32"
VENV = os.path.join(ROOT, "venv")
VENV_PYTHON = os.path.join(VENV, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
STAMP = os.path.join(VENV, ".requirements-installed")
ELECTRON_OK = os.path.join(ROOT, "node_modules", "electron", "path.txt")  # written when Electron's program was downloaded


def say(message: str) -> None:
    print(f"[Jervis] {message}", flush=True)


def run(cmd: list, **kwargs) -> int:
    return subprocess.call(cmd, cwd=ROOT, **kwargs)


# ---------- Windows: a folder path with non-English letters breaks Electron's installer ----------
def is_plain_path(path: str) -> bool:
    return path.isascii()


def move_to_plain_folder() -> None:
    """If this folder's path has non-English letters (e.g. C:\\Users\\<Hebrew name>\\...), the window's installer fails
    silently. Copy Jervis to C:\\Jervis and continue from there."""
    if not IS_WIN or is_plain_path(ROOT):
        return
    target = os.environ.get("JERVIS_PLAIN_ROOT") or r"C:\Jervis"
    say("This folder's path has non-English letters, which stops Jervis's window from installing.")
    say(f"Copying Jervis to {target} and continuing from there (your files here stay untouched)...")
    skip = shutil.ignore_patterns("venv", "node_modules", "__pycache__", "transcripts", "images", "*.zip", ".electron-cache")
    try:
        os.makedirs(target, exist_ok=True)
        for name in os.listdir(ROOT):
            source, destination = os.path.join(ROOT, name), os.path.join(target, name)
            if name in ("venv", "node_modules", "__pycache__", "transcripts", "images", ".electron-cache") or name.endswith(".zip"):
                continue
            if name == ".env" and os.path.exists(destination):
                continue  # keep the key already pasted into the new folder
            if os.path.isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True, ignore=skip)
            else:
                shutil.copy2(source, destination)
    except OSError as e:
        say(f"Could not copy to {target}: {e}")
        say("Please move the whole Jervis folder to a path with only English letters (for example C:\\Jervis) and run it again.")
        sys.exit(1)
    say(f"Done. From now on start Jervis from {target}  (double-click start_jervis.bat there).")
    sys.exit(subprocess.call([sys.executable, os.path.join(target, "run.py")], cwd=target))


def ensure_python_environment() -> None:
    if not os.path.exists(VENV_PYTHON):
        say("Creating a private Python environment (first run only)...")
        if run([sys.executable, "-m", "venv", VENV]) != 0:
            sys.exit("Could not create the Python environment.")
    stale = not os.path.exists(STAMP) or os.path.getmtime(STAMP) < os.path.getmtime(REQUIREMENTS)
    if stale:
        say("Installing Python packages (this can take a minute)...")
        run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
        if run([VENV_PYTHON, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS]) != 0:
            hint = ("On Windows, PyAudio needs a Python version that has a prebuilt wheel (3.11 or 3.12 are safest)."
                    if IS_WIN else "On macOS, run: brew install portaudio   and then try again.")
            sys.exit(f"Installing the packages failed. {hint}")
        open(STAMP, "w").close()


# ---------- Node.js (needed only for the window) ----------
def find_npm():
    found = shutil.which("npm.cmd" if IS_WIN else "npm") or shutil.which("npm")
    if found:
        return found
    candidates = ["/opt/homebrew/bin/npm", "/usr/local/bin/npm"]
    if IS_WIN:  # where the Node.js installer puts it, even before a new terminal has it on PATH
        candidates = [os.path.join(os.environ.get(var, ""), *rest) for var, rest in (
            ("ProgramFiles", ("nodejs", "npm.cmd")), ("ProgramFiles(x86)", ("nodejs", "npm.cmd")),
            ("LOCALAPPDATA", ("Programs", "nodejs", "npm.cmd")))]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def offer_node_install() -> None:
    """Windows 10/11 ships with winget, which can install Node.js in one step."""
    if not (IS_WIN and shutil.which("winget")):
        return
    say("Jervis's window needs Node.js, which isn't installed on this PC.")
    answer = input("[Jervis] Install it now? (about 1 minute)  [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
             "--accept-source-agreements", "--accept-package-agreements"])


def electron_installed() -> bool:
    return os.path.exists(ELECTRON_OK)


def install_electron(npm: str) -> bool:
    """npm can report success while Electron's own program file failed to download. Check, and retry with details."""
    base = {**os.environ, "PATH": os.path.dirname(npm) + os.pathsep + os.environ.get("PATH", ""),
            "ELECTRON_CACHE": os.path.join(ROOT, ".electron-cache")}  # a cache folder with a plain path
    say("Installing the window (Electron), first run only. This downloads about 100 MB...")
    run([npm, "install", "--no-audit", "--no-fund", "--foreground-scripts"], env=base)
    if electron_installed():
        return True
    attempts = [("again, with details", base),
                ("through a mirror (in case GitHub is blocked here)",
                 {**base, "ELECTRON_MIRROR": "https://npmmirror.com/mirrors/electron/"})]
    for label, env in attempts:
        say(f"The window didn't finish installing. Trying {label}...")
        shutil.rmtree(os.path.join(ROOT, "node_modules", "electron"), ignore_errors=True)
        result = subprocess.run([npm, "install", "electron", "--no-audit", "--no-fund", "--foreground-scripts"],
                                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if electron_installed():
            return True
        tail = "\n".join((result.stdout + "\n" + result.stderr).strip().splitlines()[-12:])
        say("What npm said:\n" + tail)
    return False


def ensure_window_packages():
    """Make sure the window (Electron) is installed. Returns the npm to use, or None if there is no Node.js."""
    npm = find_npm()
    if not npm:
        offer_node_install()
        npm = find_npm()
    if not npm:
        return None
    if not electron_installed() and not install_electron(npm):
        say("The window could not be installed. Jervis will still work by voice.")
        say("Common causes: antivirus blocking the download, a firewall/VPN, or no internet. Run this again to retry.")
    return npm


# ---------- optional: a free AI that runs on this computer (Ollama), used when the online AI can't be reached ----------
def find_ollama():
    found = shutil.which("ollama")
    if found:
        return found
    candidates = ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama"]
    if IS_WIN:
        candidates = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                      os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe")]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def ollama_running() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).read()
        return True
    except Exception:
        return False


def setup_local_ai(model: str = "llama3.2") -> bool:
    """Install Ollama if needed, make sure it is running, and download a small model (about 2 GB, once)."""
    import time
    say(f"Setting up a free AI that runs on this computer (Ollama, model {model}).")
    ollama = find_ollama()
    if not ollama:
        if IS_WIN and shutil.which("winget"):
            say("Installing Ollama...")
            run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--accept-source-agreements", "--accept-package-agreements"])
        elif sys.platform == "darwin" and shutil.which("brew"):
            say("Installing Ollama with Homebrew...")
            run(["brew", "install", "ollama"])
        ollama = find_ollama()
    if not ollama:
        say("Could not install Ollama automatically. Download it from https://ollama.com/download, install it, and run this again.")
        return False
    if not ollama_running():
        say("Starting Ollama...")
        kwargs = {"creationflags": 0x00000008 | 0x08000000} if IS_WIN else {}
        subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        for _ in range(30):
            if ollama_running():
                break
            time.sleep(1)
    if not ollama_running():
        say("Ollama didn't start. Open the Ollama app once, then run this again.")
        return False
    say(f"Downloading the model {model} (about 2 GB, one time only)...")
    if run([ollama, "pull", model]) != 0:
        say("The model download failed. Check your internet connection and run this again.")
        return False
    say("Local AI is ready. Jervis will use it automatically whenever the online AI can't be reached.")
    return True


def setup_local_images() -> bool:
    """Install the (large, optional) packages for generating images on this computer's own GPU/CPU instead of a
    cloud service — genuinely unlimited and free, but a multi-GB install; see requirements-local-images.txt."""
    requirements = os.path.join(ROOT, "requirements-local-images.txt")
    if not os.path.exists(requirements):
        say("requirements-local-images.txt is missing; can't set up local image generation.")
        return False
    say("Installing local image generation (PyTorch + diffusers, a few GB, one time only)...")
    if run([VENV_PYTHON, "-m", "pip", "install", "-r", requirements]) != 0:
        say("Installing local image generation failed. Check your internet connection and run this again.")
        return False
    say("Local image generation is ready. Jervis will use it automatically the next time you ask him to draw "
        "something (the very first picture also downloads the model itself, a few GB more, one time only).")
    return True


def ensure_env_file() -> None:
    env, example = os.path.join(ROOT, ".env"), os.path.join(ROOT, ".env.example")
    if not os.path.exists(env) and os.path.exists(example):
        shutil.copy(example, env)
        say("Created a .env file for optional settings. No key is needed: Jervis uses the AI on this computer. "
            "For the faster online AI, add a free Groq key in Settings (or GROQ_API_KEY in .env).")


def start_window(npm: str, env: dict) -> int:
    """Start Jervis's window, which starts and looks after the backend (the same way the installed app does)."""
    env = {**env, "JERVIS_PYTHON": VENV_PYTHON,
           "PATH": os.path.dirname(npm) + os.pathsep + env.get("PATH", "")}   # so npm finds node
    env.pop("ELECTRON_RUN_AS_NODE", None)   # set in VS Code's terminal; it would start Electron as plain Node
    process = subprocess.Popen([npm, "start"], cwd=ROOT, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            return process.wait(timeout=10)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            process.terminate()
            return 0


def start_jervis(env: dict) -> int:
    """Run app.py and wait. Ctrl+C reaches Jervis too, so just wait for it to finish instead of showing an error."""
    process = subprocess.Popen([VENV_PYTHON, os.path.join(ROOT, "app.py")], cwd=ROOT, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            return process.wait(timeout=8)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            process.terminate()
            return 0


if __name__ == "__main__":
    say(f"Jervis launcher {VERSION}")
    move_to_plain_folder()
    ensure_env_file()
    ensure_python_environment()
    if "--local-ai" in sys.argv:
        args = [a for a in sys.argv[sys.argv.index("--local-ai") + 1:] if not a.startswith("-")]
        setup_local_ai(args[0] if args else "llama3.2")
    if "--local-images" in sys.argv:
        setup_local_images()
    npm = ensure_window_packages()
    child_env = {**os.environ, "JERVIS_SHOW_WINDOW": "1"}  # open the window straight away
    if npm and electron_installed():
        child_env["JERVIS_NPM"] = npm
    else:
        print("\n" + "=" * 70)
        say("Jervis's WINDOW cannot open" + (" (Node.js is not installed)" if not npm else " (its installer failed)")
            + ". Jervis itself still works by voice.")
        say("Fix: " + ("install Node.js (LTS) from https://nodejs.org, then run this again." if not npm
                       else "run this again; if it keeps failing, turn off antivirus for a minute while it downloads."))
        print("=" * 70 + "\n", flush=True)
        child_env.pop("JERVIS_SHOW_WINDOW")
        child_env["JERVIS_NO_WINDOW"] = "1"  # don't keep retrying a window that can't start
    say("Starting Jervis. Say 'Hey Jervis' to wake him up. Press Ctrl+C here to quit.")
    if child_env.get("JERVIS_NPM"):
        sys.exit(start_window(npm, child_env))   # the window starts the backend and restarts it when needed
    sys.exit(start_jervis(child_env))            # no window possible: voice only, as before
