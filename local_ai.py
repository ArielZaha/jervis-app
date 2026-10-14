"""The AI that runs on this computer: finding it, installing it on first run, starting it, and keeping it running.

Jarvis's local AI is Ollama (see local_llm.py for how questions are asked). A normal user never installs it by hand:

  1. An Ollama the user already runs is reused, with the models it already has.
  2. An Ollama that is installed but not running is started quietly.
  3. Otherwise Jarvis downloads Ollama's official standalone build (pinned version, checked against its published
     SHA-256) into his own data folder and runs a private copy on its own port, so it never clashes with anything.

Then the models are downloaded with progress (a text model, and a small vision model that lets Jarvis see pictures and
the screen), checked with a real question, and Jarvis reports "ready". Every step reports human-readable progress to
the window; a failure says what went wrong and what to do, and can be retried. The engine is watched and restarted
if it crashes, and stopped when Jarvis quits.
"""
import atexit
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile

import psutil
import requests

import local_llm
import paths

OLLAMA_VERSION = "v0.34.4"
# The official standalone builds, with the size and SHA-256 GitHub publishes for them.
ASSETS = {
    ("Windows", "amd64"): ("ollama-windows-amd64.zip", 1461155106,
                           "535193f38f3344e5b08f5d1c171c31ce11aa17f0124ff69ae26d8ec7fe06fa62"),
    ("Windows", "arm64"): ("ollama-windows-arm64.zip", 208009666,
                           "b49aa49306da9bae5b7498f320f76bd2a13739c3105bcb6e115a26f0dfd10d67"),
    ("Darwin", "any"): ("ollama-darwin.tgz", 160042307,
                        "e9c8fddaab5f48f47f2c4ae3d23d0732f5182417125353faeed2188e34a22799"),
}
DOWNLOAD_URL = "https://github.com/ollama/ollama/releases/download/{version}/{name}"
USER_OLLAMA_URL = "http://127.0.0.1:11434"
MANAGED_PORT = 11435            # Jarvis's own copy: never the port an Ollama the user runs is on
APPROX_MODEL_BYTES = {"llama3.2": 2_019_393_189, "qwen2.5vl:3b": 3_200_000_000, "qwen2.5:7b": 4_683_087_332}
# The vision model needs room next to the text model and everything else the user has open: on an 8 GB computer
# it makes the whole machine swap (measured: a screenshot took over 5 minutes on an 8 GB M3). 16 GB is comfortable.
MIN_RAM_FOR_VISION = 15 * 1024 ** 3   # "16 GB" machines report a little less
_IS_WIN = platform.system() == "Windows"
_NO_WINDOW = 0x08000000 if _IS_WIN else 0


MANAGER = None   # the one LocalAI the backend runs, so a feature can ask for the vision model when it first needs it


def has_nvidia_gpu() -> bool:
    """Whether this Windows PC has an NVIDIA driver (it installs nvcuda.dll). Without one, the engine's CUDA libraries
    (1.8 GB of its 1.9 GB) can never be used, so they aren't unpacked."""
    return os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvcuda.dll"))


def _gpu_only(name: str) -> bool:
    return bool(re.match(r"(?:^|.*/)lib/ollama/(?:cuda|rocm)[^/]*/", name.replace("\\", "/")))


class SetupError(Exception):
    """A step failed. `message` is for the user; `hint` says what they can do."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


def _mb(n: float) -> str:
    return f"{n / 1024 ** 2:,.0f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:,.1f} GB"


def _probe(url: str, timeout: float = 2.0):
    """Ollama's version if an Ollama answers at `url`, else None."""
    try:
        response = requests.get(f"{url}/api/version", timeout=timeout)
        if response.ok:
            return response.json().get("version") or "unknown"
    except (requests.RequestException, ValueError):
        pass
    return None


def _machine() -> str:
    arch = platform.machine().lower()
    return "arm64" if arch in ("arm64", "aarch64") else "amd64"


def system_ollama():
    """An Ollama program installed on this computer (not Jarvis's own copy), or None."""
    found = shutil.which("ollama")
    if found:
        return found
    if _IS_WIN:
        candidates = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
                      os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe")]
    else:
        candidates = ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
                      "/Applications/Ollama.app/Contents/Resources/ollama"]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def wants_vision() -> bool:
    """Whether to use the local vision model: Settings can force it on or off; otherwise only with 16 GB or more."""
    choice = (os.getenv("JARVIS_LOCAL_VISION") or "auto").strip().lower()
    if choice in ("on", "off"):
        return choice == "on"
    return psutil.virtual_memory().total >= MIN_RAM_FOR_VISION


class LocalAI:
    STEPS = [("engine", "AI engine"), ("models", "AI models"), ("speech", "Speech recognition"), ("check", "Final check")]

    def __init__(self, report=None):
        self.report = report or (lambda state: None)
        self.url = None
        self.process = None          # an Ollama this backend started (and so must stop)
        self.managed_binary = None
        self.models_dir = None
        self.text_model = os.getenv("OLLAMA_MODEL") or local_llm.DEFAULT_MODEL
        self.vision_model = os.getenv("OLLAMA_VISION_MODEL") or "qwen2.5vl:3b"
        self.use_vision = True
        self.vision_fetching = False
        self.ready = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._stop = threading.Event()
        self.state = {"active": False, "done": False, "error": None, "hint": None, "summary": "",
                      "steps": [{"id": sid, "label": label, "state": "pending", "detail": "", "progress": None}
                                for sid, label in self.STEPS]}
        global MANAGER
        MANAGER = self

    # ---------- progress reporting ----------
    def _step(self, sid: str, state: str = None, detail: str = None, progress=None) -> None:
        for step in self.state["steps"]:
            if step["id"] == sid:
                if state is not None:
                    step["state"] = state
                if detail is not None:
                    step["detail"] = detail
                step["progress"] = progress
        self._publish()

    def _publish(self) -> None:
        try:
            self.report(json.loads(json.dumps(self.state)))
        except Exception as e:   # the window being gone must never break the setup
            print(f"Could not report setup progress: {e}", flush=True)

    # ---------- the whole setup ----------
    def start_background(self) -> None:
        """Run ensure_ready() on its own thread (safe to call again, e.g. for a retry)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._run, daemon=True, name="local-ai-setup").start()

    def _run(self) -> None:
        try:
            self.ensure_ready()
        finally:
            with self._lock:
                self._running = False

    def ensure_ready(self) -> bool:
        self.state.update(active=True, done=False, error=None, hint=None,
                          summary="Getting Jarvis’s AI ready. This happens once.")
        for step in self.state["steps"]:
            if step["state"] != "done":
                step.update(state="pending", detail="", progress=None)
        self._publish()
        current = "engine"
        try:
            current = "engine"
            self._ensure_engine()
            current = "models"
            self._ensure_models()
            current = "speech"
            self._ensure_speech()
            current = "check"
            self._final_check()
        except SetupError as e:
            self._step(current, "error", e.message)
            self.state.update(active=False, error=e.message, hint=e.hint,
                              summary="Jarvis’s AI isn’t ready yet. Everything that doesn’t need the AI already works.")
            self._publish()
            print(f"Local AI setup stopped at '{current}': {e.message} {e.hint}", flush=True)
            return False
        except Exception as e:   # anything unexpected: still a clear message, and the details in the log
            import traceback
            traceback.print_exc()
            self._step(current, "error", f"Unexpected problem: {e}")
            self.state.update(active=False, error=f"Something unexpected went wrong ({type(e).__name__}).",
                              hint="Try again. If it keeps happening, the details are in the log (Settings, Diagnostics).",
                              summary="Jarvis’s AI isn’t ready yet.")
            self._publish()
            return False
        self.state.update(active=False, done=True, error=None, hint=None, summary="Jarvis’s AI is ready.")
        self._publish()
        self.ready.set()
        print(f"Local AI ready: {self.text_model}" + (f" + {self.vision_model}" if self.use_vision else "")
              + f" at {self.url}", flush=True)
        return True

    # ---------- 1. the engine ----------
    def _ensure_engine(self) -> None:
        self._step("engine", "active", "Looking for an AI engine on this computer…")
        configured = os.getenv("OLLAMA_URL", "").rstrip("/")
        for url, label in ((configured, "the configured"), (USER_OLLAMA_URL, "your"),
                           (f"http://127.0.0.1:{MANAGED_PORT}", "Jarvis’s")):
            if url and _probe(url):
                self._use(url)
                self._step("engine", "done", f"Using {label} Ollama.")
                return
        binary = system_ollama()
        if binary:
            self._step("engine", "active", "Starting the AI engine that’s installed on this computer…")
            self._start_serve(binary, models_dir=None)
            self._step("engine", "done", "Started Ollama (already installed).")
            return
        binary = self._managed_binary() or self._download_engine()
        self._step("engine", "active", "Starting the AI engine…")
        ollama_models = os.path.join(paths.models_dir(), "ollama")
        os.makedirs(ollama_models, exist_ok=True)
        self._start_serve(binary, models_dir=ollama_models)
        self._step("engine", "done", "AI engine running.")

    def _use(self, url: str) -> None:
        self.url = url
        local_llm.set_url(url)

    def _runtime_dir(self) -> str:
        return os.path.join(paths.DATA_DIR, "runtime", f"ollama-{OLLAMA_VERSION}")

    def _managed_binary(self):
        root = self._runtime_dir()
        name = "ollama.exe" if _IS_WIN else "ollama"
        for folder, _dirs, files in os.walk(root) if os.path.isdir(root) else ():
            if name in files:
                return os.path.join(folder, name)
        return None

    def _asset(self):
        system = platform.system()
        key = (system, "any") if system == "Darwin" else (system, _machine())
        if key not in ASSETS:
            raise SetupError("Jarvis can’t install the AI engine on this kind of computer by himself.",
                             "Install Ollama from ollama.com, then press Try again.")
        return ASSETS[key]

    def _check_disk(self, need: int) -> None:
        free = shutil.disk_usage(paths.DATA_DIR).free
        if free < need:
            raise SetupError(f"Not enough free disk space: Jarvis needs about {_mb(need)} and there’s {_mb(free)}.",
                             "Free up some space, then press Try again.")

    def _download_engine(self) -> str:
        name, size, sha256 = self._asset()
        self._check_disk(size * 2 + self._models_bytes())   # the archive and its unpacked copy, then the model
        folder = paths.data_dir("runtime")
        archive = os.path.join(folder, name)
        partial = archive + ".part"
        url = DOWNLOAD_URL.format(version=OLLAMA_VERSION, name=name)
        if not (os.path.exists(archive) and os.path.getsize(archive) == size):
            self._download(url, partial, size, "engine", "Downloading the AI engine")
            os.replace(partial, archive)
        self._step("engine", "active", "Checking the download…", None)
        digest = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            os.remove(archive)
            raise SetupError("The AI engine download was damaged (its checksum didn’t match), so it was deleted.",
                             "Press Try again to download it again.")
        self._step("engine", "active", "Unpacking the AI engine…", None)
        target = self._runtime_dir()
        tmp_target = target + ".unpacking"
        shutil.rmtree(tmp_target, ignore_errors=True)
        try:
            if name.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    keep = z.namelist() if has_nvidia_gpu() else [m for m in z.namelist() if not _gpu_only(m)]
                    z.extractall(tmp_target, members=keep)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(tmp_target, filter="data")
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
            shutil.rmtree(tmp_target, ignore_errors=True)
            raise SetupError(f"The AI engine couldn’t be unpacked ({e}).", "Check the disk has space, then Try again.")
        shutil.rmtree(target, ignore_errors=True)
        os.replace(tmp_target, target)
        os.remove(archive)
        for old in os.listdir(folder):   # an engine left by an earlier Jarvis version: superseded, never used again
            if old.startswith("ollama-") and os.path.join(folder, old) != target and os.path.isdir(os.path.join(folder, old)):
                shutil.rmtree(os.path.join(folder, old), ignore_errors=True)
        binary = self._managed_binary()
        if not binary:
            raise SetupError("The AI engine download didn’t contain the expected program.", "Press Try again.")
        if not _IS_WIN:
            os.chmod(binary, 0o755)
        return binary

    def _download(self, url: str, partial: str, size: int, step: str, label: str) -> None:
        """Download with resume: a dropped connection or a restart continues where it stopped."""
        for attempt in range(4):
            done = os.path.getsize(partial) if os.path.exists(partial) else 0
            headers = {"Range": f"bytes={done}-"} if done else {}
            try:
                with requests.get(url, headers=headers, stream=True, timeout=(15, 60)) as response:
                    if done and response.status_code != 206:
                        done = 0   # the server ignored the resume request: start over
                    response.raise_for_status()
                    with open(partial, "ab" if done else "wb") as f:
                        last = 0.0
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if self._stop.is_set():
                                raise SetupError("Setup was stopped.", "Press Try again to continue.")
                            f.write(chunk)
                            done += len(chunk)
                            if time.time() - last > 0.5:
                                last = time.time()
                                self._step(step, "active", f"{label}… {_mb(done)} of {_mb(size)}", done / size)
                if done >= size:
                    return
            except requests.RequestException as e:
                print(f"Download interrupted ({e}); retrying.", flush=True)
                time.sleep(3 * (attempt + 1))
        raise SetupError("The download keeps failing. The internet connection may have dropped.",
                         "Check your connection, then press Try again (it continues where it stopped).")

    def _start_serve(self, binary: str, models_dir) -> None:
        port = MANAGED_PORT
        url = f"http://127.0.0.1:{port}"
        if _probe(url):   # a copy Jarvis started earlier is still running (e.g. after a crash): reuse it
            self._use(url)
            return
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_KEEP_ALIVE": "30m"}
        if models_dir:
            env["OLLAMA_MODELS"] = models_dir
        log = open(os.path.join(paths.logs_dir(), "ollama.log"), "a", encoding="utf-8")
        try:
            self.process = subprocess.Popen([binary, "serve"], env=env, stdout=log, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        except OSError as e:
            raise SetupError(f"The AI engine couldn’t start ({e}).", "Press Try again. If it persists, restart the computer.")
        self.managed_binary, self.models_dir = binary, models_dir
        _register_cleanup(self)
        for _ in range(120):
            if _probe(url):
                self._use(url)
                threading.Thread(target=self._watchdog, daemon=True, name="ollama-watchdog").start()
                return
            if self.process.poll() is not None:
                break
            time.sleep(0.5)
        raise SetupError("The AI engine started but didn’t respond.",
                         "Press Try again. The details are in logs/ollama.log.")

    def _watchdog(self) -> None:
        """If the engine Jarvis started stops, start it again (a few times), so the AI comes back by itself."""
        restarts = 0
        while not self._stop.is_set():
            time.sleep(5)
            if self.process is None or self.process.poll() is None:
                continue
            if restarts >= 3:
                print("The AI engine keeps stopping; not restarting it again.", flush=True)
                self.state.update(error="The AI engine keeps stopping.", done=False,
                                  hint="Press Try again, or restart Jarvis. The details are in logs/ollama.log.")
                self._publish()
                return
            restarts += 1
            print(f"The AI engine stopped (code {self.process.returncode}); restarting it.", flush=True)
            try:
                self._start_serve(self.managed_binary, self.models_dir)
            except SetupError as e:
                print(f"Could not restart the AI engine: {e.message}", flush=True)

    # ---------- 2. the models ----------
    def _models_bytes(self) -> int:
        return int(APPROX_MODEL_BYTES.get(self.text_model, 2.5e9) * 1.1)   # the vision model comes later, when needed

    def _installed(self) -> list:
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            response.raise_for_status()
            return [m.get("name", "") for m in response.json().get("models", [])]
        except (requests.RequestException, ValueError):
            return []

    @staticmethod
    def _has(installed: list, wanted: str) -> bool:
        base = wanted if ":" in wanted else f"{wanted}:latest"
        return any(name == wanted or name == base for name in installed)

    def _ensure_models(self) -> None:
        """Only the text model is downloaded at setup. The vision model (3 GB) waits until something first needs to
        see a picture or the screen (fetch_vision): most people never do, and it was most of the first download."""
        self.use_vision = wants_vision()
        if self._has(self._installed(), self.text_model):
            self._step("models", "done", "Model ready.")
            return
        self._check_disk(int(APPROX_MODEL_BYTES.get(self.text_model, 2.5e9) * 1.1))
        self._pull(self.text_model, f"Downloading the AI model ({self.text_model})")
        self._step("models", "done", "Model ready.")

    def vision_installed(self) -> bool:
        return bool(self.url) and self._has(self._installed(), self.vision_model)

    def fetch_vision(self) -> str:
        """Download the vision model in the background, the first time it's needed. What to tell the user:
        "started", "fetching" (already on its way), "installed", "not_wanted" (this computer is set not to) or
        "not_ready" (the local AI itself isn't running)."""
        if not wants_vision():
            return "not_wanted"
        if not self.url or not self.ready.is_set():
            return "not_ready"
        with self._lock:
            if self.vision_fetching:
                return "fetching"
            if self.vision_installed():
                return "installed"
            self.vision_fetching = True

        def work():
            try:
                self._check_disk(int(APPROX_MODEL_BYTES.get(self.vision_model, 2.5e9) * 1.1))
                self._pull(self.vision_model, f"Downloading the vision model ({self.vision_model})")
                self._step("models", "done", "Models ready, including vision.")
            except SetupError as e:
                print(f"The vision model couldn't be downloaded: {e.message}", flush=True)
            except Exception as e:
                print(f"The vision model couldn't be downloaded: {e!r}", flush=True)
            finally:
                self.vision_fetching = False
        threading.Thread(target=work, daemon=True, name="vision-model").start()
        return "started"

    def _pull(self, model: str, label: str) -> None:
        for attempt in range(3):
            totals, completed = {}, {}
            try:
                with requests.post(f"{self.url}/api/pull", json={"model": model, "stream": True},
                                   stream=True, timeout=(15, 300)) as response:
                    response.raise_for_status()
                    last = 0.0
                    for line in response.iter_lines():
                        if self._stop.is_set():
                            raise SetupError("Setup was stopped.", "Press Try again to continue.")
                        if not line:
                            continue
                        event = json.loads(line)
                        if event.get("error"):
                            raise SetupError(f"The model {model} couldn’t be downloaded: {event['error']}",
                                             "Check the internet connection, then press Try again.")
                        digest = event.get("digest")
                        if digest and event.get("total"):
                            totals[digest] = event["total"]
                            completed[digest] = event.get("completed", 0)
                        if time.time() - last > 0.5:
                            last = time.time()
                            total = sum(totals.values())
                            got = sum(completed.values())
                            detail = f"{label}… {_mb(got)} of {_mb(total)}" if total else f"{label}…"
                            self._step("models", "active", detail, (got / total) if total else None)
                        if event.get("status") == "success":
                            return
            except SetupError:
                raise
            except (requests.RequestException, ValueError) as e:
                print(f"Model download interrupted ({e}); retrying.", flush=True)
                time.sleep(3 * (attempt + 1))
        raise SetupError(f"The model {model} keeps failing to download.",
                         "Check your connection, then press Try again (it continues where it stopped).")

    # ---------- 3. speech recognition ----------
    def _ensure_speech(self) -> None:
        try:
            import stt_local
        except ImportError:
            stt_local = None
        if stt_local is None or not stt_local.available():
            self._step("speech", "skipped", "Using online speech recognition.")
            return
        self._step("speech", "active", "Downloading the speech model…")
        try:
            stt_local.ensure_model(lambda detail, fraction: self._step("speech", "active", detail, fraction))
        except Exception as e:
            print(f"Local speech recognition unavailable: {e}", flush=True)
            self._step("speech", "skipped", "Using online speech recognition for now.")
            return
        self._step("speech", "done", "Speech recognition ready (works offline).")

    # ---------- 4. a real question ----------
    def _final_check(self) -> None:
        self._step("check", "active", "Asking the AI a test question (the first answer takes longest)…")
        try:
            response = requests.post(f"{self.url}/api/chat", json={
                "model": self.text_model, "stream": False, "keep_alive": "30m",
                "messages": [{"role": "user", "content": "Reply with just the word: ready"}],
                "options": {"num_predict": 8}}, timeout=300)
            response.raise_for_status()
            answer = (response.json().get("message") or {}).get("content", "").strip()
        except (requests.RequestException, ValueError) as e:
            raise SetupError(f"The AI didn’t answer its test question ({type(e).__name__}).",
                             "Press Try again. A computer with little free memory may need other apps closed.")
        if not answer:
            raise SetupError("The AI answered with nothing.", "Press Try again.")
        self._step("check", "done", "The AI answered.")

    def stop(self) -> None:
        self._stop.set()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.process.kill()
                except OSError:
                    pass


# ---------- letting go of the local AI (the user chose the online AI only) ----------
_ENGINE_NAMES = ("ollama", "ollama.exe", "ollama app", "ollama app.exe")   # the server, and the menu-bar / tray app


def _local_urls() -> list:
    """Where an Ollama on this computer may be answering: the user's own, Jarvis's copy, and a configured one (only if
    it is on this computer: an Ollama on another machine is not ours to unload)."""
    configured = os.getenv("OLLAMA_URL", "").rstrip("/")
    here = configured if configured.split("//")[-1].split(":")[0] in ("127.0.0.1", "localhost") else ""
    return list(dict.fromkeys(u for u in (here, USER_OLLAMA_URL, f"http://127.0.0.1:{MANAGED_PORT}") if u))


def _unload_models(url: str) -> int:
    """Ask the Ollama at `url` to drop every model it holds in memory. Returns how many bytes they took."""
    try:
        loaded = requests.get(f"{url}/api/ps", timeout=3).json().get("models") or []
    except (requests.RequestException, ValueError, AttributeError):
        return 0
    freed = 0
    for model in loaded:
        try:
            requests.post(f"{url}/api/generate", json={"model": model.get("name"), "keep_alive": 0}, timeout=20)
            freed += int(model.get("size") or 0)
        except (requests.RequestException, ValueError, TypeError):
            pass
    return freed


def _engine_processes() -> list:
    """Every Ollama program this user is running: the app, its server, and the model runners under them."""
    try:
        me = psutil.Process().username()
    except psutil.Error:
        me = None
    found = {}
    for proc in psutil.process_iter(["name", "username"]):
        try:
            if (proc.info["name"] or "").lower() not in _ENGINE_NAMES or proc.pid == os.getpid():
                continue
            if me and proc.info["username"] and proc.info["username"] != me:
                continue   # someone else's
            found[proc.pid] = proc
            for child in proc.children(recursive=True):
                found[child.pid] = child
        except psutil.Error:
            continue
    return list(found.values())


def release() -> dict:
    """Free the memory the local AI holds, for when only the online AI is used: unload its models, then close the
    Ollama programs. Unloading alone already gives the memory back, so this still helps where a program can't be closed
    or the system starts it again. Returns {"freed": bytes of models unloaded, "stopped": programs closed, "left":
    programs still running}. Choosing the local AI again later starts it the usual way (LocalAI above)."""
    freed = sum(_unload_models(url) for url in _local_urls())
    stopped = _close(_engine_processes())
    time.sleep(1.5)   # an app that reopens itself (after its own update, say), or a system service, does it right away
    again = _engine_processes()
    if again:
        freed += sum(_unload_models(url) for url in _local_urls())
        _close(again)   # once more; if the system insists on running it, it now holds no model at least
        time.sleep(1.5)
    return {"freed": freed, "stopped": stopped, "left": len(_engine_processes())}


def _close(processes: list) -> int:
    """Ask each program to quit, force the ones that don't. Returns how many are gone."""
    for proc in processes:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=6)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    return len(processes) - len(alive)


def release_summary(result: dict) -> str:
    if not result["stopped"] and not result["freed"]:
        return "The AI on this computer wasn't running, so there was nothing to close."
    text = "Closed the AI on this computer (Ollama)"
    text += f" and freed about {_mb(result['freed'])} of memory." if result["freed"] else "; it had no model in memory."
    if result["left"]:
        text += " This computer started Ollama again by itself; it holds no model now, so it uses very little memory."
    return text


_cleanup_registered = []


def _register_cleanup(instance: LocalAI) -> None:
    """Stop the engine Jarvis started when Jarvis stops. app.py turns SIGTERM (how the window stops the backend) into
    a normal exit, so this runs then too; on Windows the window ends the whole process tree instead."""
    if _cleanup_registered:
        return
    _cleanup_registered.append(instance)
    atexit.register(instance.stop)
