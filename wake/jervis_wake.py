"""Jervis Wake: a small background listener that opens Jervis when you say "Hey Jervis", "Wake up Jervis" or
"Hello Jervis", even with Jervis and VS Code closed.

How it stays light and private
- Speech is recognized on this Mac by Vosk in grammar mode: the recognizer can only produce the wake phrases (or
  "unknown"), so it never turns a conversation into text. Nothing is recorded, saved or sent anywhere.
- A simple loudness gate feeds the recognizer only while someone is talking; in a quiet room it does almost nothing.
- While Jervis is running (the version started from this project, or the installed app), this listener closes the
  microphone and waits: Jervis hears his own wake phrases then.

How it gets the microphone
macOS gives the microphone to apps, not to scripts. This file runs inside "Jervis Wake.app" (see install.sh), whose
Info.plist says why it needs the microphone, so macOS can ask once and remember. Jervis, started from here, inherits
that permission, so he can listen too without VS Code.

Started at sign-in by the LaunchAgent io.github.arielzaha.jervis-wake (see install.sh). Log: ~/Library/Logs/JervisWake.
"""
import collections
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SUPPORT = os.path.join(HOME, "Library", "Application Support", "JervisWake")
LOG_DIR = os.path.join(HOME, "Library", "Logs", "JervisWake")
CONFIG = os.path.join(SUPPORT, "config.json")
MODEL = os.path.join(SUPPORT, "model")

RATE = 16000
BLOCK = 4000                     # 0.25 s of audio per read
PHRASES = [f"{greeting} {name}" for greeting in ("hey", "hello", "wake up") for name in ("jervis", "jarvis")]
GRAMMAR = json.dumps(PHRASES + ["hey", "hello", "wake up", "[unk]"])   # lone words let other speech land somewhere else
TALK_HOLD = 1.5                  # seconds the recognizer keeps listening after the sound drops
PRE_ROLL = 3                     # blocks kept from just before the sound started, so the first word isn't cut
SILENT_MIC_WARNING = 20          # seconds of perfect digital silence: macOS is giving us no microphone
CHECK_JERVIS_EVERY = 2.0         # seconds
AFTER_LAUNCH_GRACE = 45          # seconds to wait for Jervis to come up before listening again

log = logging.getLogger("jervis-wake")


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(LOG_DIR, "wake.log"), maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        config = json.load(f)
    project = config["project"]
    config["electron"] = os.path.join(project, "node_modules", "electron", "dist", "Electron.app", "Contents",
                                      "MacOS", "Electron")
    return config


# ---------- is Jervis running? ----------
def jervis_running(config: dict) -> bool:
    """The Jervis window started from the project, its engine (app.py), or the installed Jervis app."""
    patterns = [config["electron"], os.path.join(config["project"], "app.py"), "/Jervis.app/Contents/MacOS/Jervis"]
    for pattern in patterns:
        try:
            if subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=3).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    return False


def launch_jervis(config: dict) -> bool:
    """Start the normal Jervis window (it starts app.py from the project's venv itself) and tell it to greet."""
    electron, project = config["electron"], config["project"]
    if not os.path.exists(electron):
        log.error("Jervis's window isn't installed at %s. Run `npm install` in %s once.", electron, project)
        return False
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)          # set in VS Code terminals; Electron would start as plain Node
    env["JERVIS_WOKEN_BY_VOICE"] = "1"             # Jervis says "I'm awake, how can I help you?" once it's up
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        out = open(os.path.join(LOG_DIR, "jervis-window.log"), "a", encoding="utf-8")
        subprocess.Popen([electron, project], cwd=project, env=env, stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.error("Couldn't start Jervis: %s", e)
        return False


# ---------- listening ----------
def heard_wake_phrase(text: str) -> bool:
    words = " " + " ".join(text.replace("[unk]", " ").split()) + " "
    return any(f" {phrase} " in words for phrase in PHRASES)


class Listener:
    def __init__(self, config: dict):
        import vosk
        vosk.SetLogLevel(-1)
        self.config = config
        self.model = vosk.Model(MODEL)
        self.vosk = vosk
        self.recognizer = None
        self.noise = 150.0            # running estimate of the room's loudness
        self.warned_silent = False

    def new_recognizer(self):
        self.recognizer = self.vosk.KaldiRecognizer(self.model, RATE, GRAMMAR)

    def run(self) -> None:
        import numpy as np
        import sounddevice as sd
        while True:
            if jervis_running(self.config):
                time.sleep(3)          # Jervis listens for himself; the microphone stays closed here
                continue
            try:
                woken = self.listen_until_woken(sd, np)
            except sd.PortAudioError as e:
                log.warning("Microphone unavailable (%s); trying again in 5 s.", e)
                time.sleep(5)
                continue
            if not woken:
                continue               # Jervis was opened some other way
            log.info("Wake phrase heard: starting Jervis.")
            if launch_jervis(self.config):
                deadline = time.time() + AFTER_LAUNCH_GRACE
                while time.time() < deadline and not jervis_running(self.config):
                    time.sleep(1)

    def listen_until_woken(self, sd, np) -> bool:
        """True when a wake phrase was heard; False when Jervis was started some other way. Either way the
        microphone is closed when this returns."""
        self.new_recognizer()
        pre_roll = collections.deque(maxlen=PRE_ROLL)
        talking_until = 0.0
        silent_since = time.time()
        last_check = time.time()
        with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16") as stream:
            log.info("Listening for “Hey Jervis”, “Wake up Jervis” or “Hello Jervis”.")
            while True:
                data, _overflowed = stream.read(BLOCK)
                block = bytes(data)
                samples = np.frombuffer(block, dtype=np.int16)
                level = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0
                now = time.time()

                # macOS hands out pure zeros when the app isn't allowed to use the microphone
                if level > 0:
                    silent_since = now
                elif now - silent_since > SILENT_MIC_WARNING and not self.warned_silent:
                    self.warned_silent = True
                    log.warning("The microphone gives only silence. Allow “Jervis Wake” in System Settings, "
                                "Privacy & Security, Microphone.")

                if level > max(3.0 * self.noise, 300.0):
                    if now > talking_until:            # speech is starting: include what came just before
                        for earlier in pre_roll:
                            self.recognizer.AcceptWaveform(earlier)
                    talking_until = now + TALK_HOLD
                else:
                    self.noise = 0.95 * self.noise + 0.05 * level if level < 3.0 * self.noise else self.noise

                if now <= talking_until:
                    if self.recognizer.AcceptWaveform(block):
                        if heard_wake_phrase(json.loads(self.recognizer.Result()).get("text", "")):
                            return True
                elif talking_until:                    # the sound just ended: finish that bit of speech
                    talking_until = 0.0
                    text = json.loads(self.recognizer.FinalResult()).get("text", "")
                    self.new_recognizer()
                    if heard_wake_phrase(text):
                        return True
                pre_roll.append(block)

                if now - last_check > CHECK_JERVIS_EVERY:
                    last_check = now
                    if jervis_running(self.config):
                        return False


def check() -> int:
    """`jervis_wake.py --check`: everything loads (packages, speech model, settings), without opening the microphone."""
    import numpy  # noqa: F401
    import sounddevice  # noqa: F401
    import vosk
    vosk.SetLogLevel(-1)
    config = load_config()
    vosk.KaldiRecognizer(vosk.Model(MODEL), RATE, GRAMMAR)
    ready = os.path.exists(config["electron"])
    print(f"Jervis Wake: ready. Jervis: {config['project']} (window {'found' if ready else 'MISSING'}).")
    return 0 if ready else 1


def main() -> None:
    if "--check" in sys.argv:
        sys.exit(check())
    setup_logging()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        config = load_config()
    except (OSError, KeyError, ValueError) as e:
        log.error("Can't read %s (%s). Run wake/install.sh again.", CONFIG, e)
        time.sleep(60)
        sys.exit(1)
    log.info("Jervis Wake started (Jervis: %s).", config["project"])
    listener = Listener(config)
    while True:
        try:
            listener.run()
        except Exception:                      # never die for good: log, breathe, start over
            log.exception("Unexpected problem; restarting the listener in 5 s.")
            time.sleep(5)


if __name__ == "__main__":
    main()
