"""Jarvis Wake: a small background listener that opens Jarvis when you say "Hey Jarvis", "Wake up Jarvis" or
"Hello Jarvis", even with Jarvis and VS Code closed — or when you open the Jarvis app on your paired phone.

How it stays light and private
- Speech is recognized on this Mac by Vosk in grammar mode: the recognizer can only produce the wake phrases (or
  "unknown"), so it never turns a conversation into text. Nothing is recorded, saved or sent anywhere.
- A simple loudness gate feeds the recognizer only while someone is talking; in a quiet room it does almost nothing.
- While Jarvis is running (the version started from this project, or the installed app), this listener closes the
  microphone and waits: Jarvis hears his own wake phrases then.

How it gets the microphone
macOS gives the microphone to apps, not to scripts. This file runs inside "Jarvis Wake.app" (see install.sh), whose
Info.plist says why it needs the microphone, so macOS can ask once and remember. Jarvis, started from here, inherits
that permission, so he can listen too without VS Code.

Opening Jarvis from the phone (PhoneDoor)
While Jarvis is closed, this answers on Jarvis's own phone address (the same port, so the phone's installed app
needs nothing new): it serves the phone app's page, and when a phone that's genuinely paired with this Mac connects
(its device token checked against Jarvis's own paired-device list, the same check Jarvis makes), it starts Jarvis
and steps aside. Jarvis takes over the port a few seconds later and the phone reconnects to him on its own. An
unpaired phone, or anything not on the local network, can't start anything. While Jarvis runs, the port is his.

Started at sign-in by the LaunchAgent io.github.arielzaha.jervis-wake (see install.sh). Log: ~/Library/Logs/JarvisWake.
"""
import asyncio
import collections
import hashlib
import hmac
import ipaddress
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

HOME = os.path.expanduser("~")
SUPPORT = os.path.join(HOME, "Library", "Application Support", "JarvisWake")
LOG_DIR = os.path.join(HOME, "Library", "Logs", "JarvisWake")
CONFIG = os.path.join(SUPPORT, "config.json")
MODEL = os.path.join(SUPPORT, "model")

RATE = 16000
BLOCK = 4000                     # 0.25 s of audio per read
PHRASES = [f"{greeting} {name}" for greeting in ("hey", "hello", "wake up") for name in ("jarvis", "jervis")]
GRAMMAR = json.dumps(PHRASES + ["hey", "hello", "wake up", "[unk]"])   # lone words let other speech land somewhere else
TALK_HOLD = 1.5                  # seconds the recognizer keeps listening after the sound drops
PRE_ROLL = 3                     # blocks kept from just before the sound started, so the first word isn't cut
SILENT_MIC_WARNING = 20          # seconds of perfect digital silence: macOS is giving us no microphone
CHECK_JARVIS_EVERY = 2.0         # seconds
AFTER_LAUNCH_GRACE = 45          # seconds to wait for Jarvis to come up before listening again
PHONE_PORT = int(os.environ.get("JARVIS_PHONE_PORT") or 8766)   # Jarvis's own phone port (app.py's PHONE_WS_PORT)

log = logging.getLogger("jarvis-wake")


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


# ---------- is Jarvis running? ----------
def jarvis_running(config: dict) -> bool:
    """The Jarvis window started from the project, its engine (app.py), or the installed Jarvis app."""
    patterns = [config["electron"], os.path.join(config["project"], "app.py"), "/Jarvis.app/Contents/MacOS/Jarvis",
                "/Jervis.app/Contents/MacOS/Jervis"]   # an installed copy from before the rename
    for pattern in patterns:
        try:
            if subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=3).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    return False


_launch_lock = threading.Lock()
_last_launch = [0.0]


def claim_launch(config: dict) -> bool:
    """True if it's this caller's turn to start Jarvis: not already running, and no launch (by voice or by phone)
    in the last AFTER_LAUNCH_GRACE seconds — the phone retrying, or both at once, must never start two Jarvises."""
    with _launch_lock:
        if time.time() - _last_launch[0] < AFTER_LAUNCH_GRACE or jarvis_running(config):
            return False
        _last_launch[0] = time.time()
        return True


def launch_jarvis_once(config: dict, voice: bool) -> bool:
    return launch_jarvis(config, voice=voice) if claim_launch(config) else True


def recently_launched() -> bool:
    return time.time() - _last_launch[0] < AFTER_LAUNCH_GRACE


def launch_jarvis(config: dict, voice: bool = True) -> bool:
    """Start the normal Jarvis window (it starts app.py from the project's venv itself); woken by voice, it greets."""
    electron, project = config["electron"], config["project"]
    if not os.path.exists(electron):
        log.error("Jarvis's window isn't installed at %s. Run `npm install` in %s once.", electron, project)
        return False
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)          # set in VS Code terminals; Electron would start as plain Node
    if voice:
        env["JARVIS_WOKEN_BY_VOICE"] = "1"         # Jarvis says "I'm awake, how can I help you?" once it's up
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    try:
        out = open(os.path.join(LOG_DIR, "jarvis-window.log"), "a", encoding="utf-8")
        subprocess.Popen([electron, project], cwd=project, env=env, stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.error("Couldn't start Jarvis: %s", e)
        return False


# ---------- opening Jarvis from the paired phone ----------
def _project_file(config: dict, name: str) -> str:
    return os.path.join(config["project"], name)


def phone_control_on(config: dict) -> bool:
    """Jarvis only serves phones when "Let your phone control this computer" is on; neither does this."""
    try:
        with open(_project_file(config, "settings.json"), encoding="utf-8") as f:
            values = json.load(f).get("values", {})
    except (OSError, ValueError):
        return False
    # (the old name's key too, until Jarvis next starts and moves settings over: see settings.py)
    value = values.get("JARVIS_PHONE_CONTROL", values.get("JE" + "RVIS_PHONE_CONTROL", "off"))
    return str(value).strip().lower() not in ("", "off")


def phone_is_paired(config: dict, device_id: str, token: str) -> bool:
    """The same check Jarvis makes (phone_control.DeviceRegistry.authenticate): only a hash of each device's token
    is stored, read fresh every time so a phone unpaired in Jarvis is refused here too."""
    try:
        with open(_project_file(config, "phone_devices.json"), encoding="utf-8") as f:
            device = json.load(f).get("devices", {}).get(device_id or "")
    except (OSError, ValueError, AttributeError):
        return False
    if not device or not token:
        return False
    return hmac.compare_digest(device.get("token_hash", ""), hashlib.sha256(token.encode("utf-8")).hexdigest())


def _private(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


_STATIC = {   # path -> (file in the project, content type, cache) — a fixed list, never a path from the request
    "/": ("phone_client.html", "text/html; charset=utf-8", "no-store"),
    "/index.html": ("phone_client.html", "text/html; charset=utf-8", "no-store"),
    "/sw.js": ("phone_sw.js", "text/javascript; charset=utf-8", "no-store"),
    "/manifest.webmanifest": ("phone_manifest.webmanifest", "application/manifest+json", "no-cache"),
    "/agent.js": ("phone_agent.js", "text/javascript; charset=utf-8", "no-cache"),
    "/apple-touch-icon.png": ("phone_icons/apple-touch-icon.png", "image/png", "public, max-age=86400"),
    "/favicon.ico": ("phone_icons/favicon-64.png", "image/png", "public, max-age=86400"),
}
for _icon in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "favicon-64.png"):
    _STATIC[f"/icons/{_icon}"] = (f"phone_icons/{_icon}", "image/png", "public, max-age=86400")
# The phone app's graphs, globe and planets (phone_visuals.py keeps the same list; a test checks they agree)
VISUAL_SCRIPTS = ("sphere_gl.js", "graph.js", "earth.js", "planet.js", "vendor/jsqr/jsQR.js")
VISUAL_FONTS = ("vendor/fonts/orbitron-latin.woff2",)
VISUAL_IMAGES = (
    "vendor/earth/blue_marble_5400.jpg", "vendor/earth/clouds_2048.jpg", "vendor/earth/night_lights_3600.jpg",
    "vendor/earth/earth_atmos_2048.jpg",
    "vendor/planets/2k_sun.jpg", "vendor/planets/2k_mercury.jpg", "vendor/planets/2k_venus_surface.jpg",
    "vendor/planets/2k_mars.jpg", "vendor/planets/2k_jupiter.jpg", "vendor/planets/2k_saturn.jpg",
    "vendor/planets/2k_saturn_ring_alpha.png", "vendor/planets/2k_uranus.jpg", "vendor/planets/2k_neptune.jpg",
    "vendor/planets/2k_moon.jpg",
)
for _name in VISUAL_SCRIPTS:
    _STATIC[f"/{_name}"] = (_name, "text/javascript; charset=utf-8", "no-cache")
for _name in VISUAL_IMAGES:
    _STATIC[f"/{_name}"] = (_name, "image/png" if _name.endswith(".png") else "image/jpeg", "public, max-age=604800")
for _name in VISUAL_FONTS:
    _STATIC[f"/{_name}"] = (_name, "font/woff2", "public, max-age=604800")


class PhoneDoor:
    """Jarvis's phone port, held only while Jarvis is closed — see the module docstring."""

    def __init__(self, config: dict):
        self.config = config
        self._thread = None
        self._loop = None
        self._server = None

    @property
    def open(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.open:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True, name="phone-door")
        self._thread.start()
        ready.wait(5)

    def stop(self) -> None:
        if not self.open:
            return
        if self._loop is not None and self._server is not None:
            self._loop.call_soon_threadsafe(self._server.close)
        self._thread.join(5)
        self._thread = None

    def _run(self, ready: threading.Event) -> None:
        import websockets
        self._loop = loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def serve():
            try:
                self._server = await websockets.serve(self._handle, "0.0.0.0", PHONE_PORT,
                                                      process_request=self._page, ping_interval=None)
            except OSError as e:
                log.info("Phone door: port %s is busy (%s); not opening it.", PHONE_PORT, e)
                return
            finally:
                ready.set()
            log.info("Phone door open on port %s: opening the Jarvis app on your phone starts Jarvis.", PHONE_PORT)
            await self._server.wait_closed()
            log.info("Phone door closed.")

        try:
            loop.run_until_complete(serve())
        finally:
            self._server = None
            loop.close()

    def _page(self, connection, request):
        """Plain page loads (the phone app's own files); a WebSocket handshake goes on to _handle."""
        if request.headers.get("Upgrade"):
            return None
        remote = getattr(connection, "remote_address", None)
        if not _private(remote[0] if remote else ""):
            return connection.respond(403, "Not allowed.")
        entry = _STATIC.get(urlsplit(request.path).path)
        if entry is None:
            return connection.respond(404, "Not found.")
        name, content_type, cache = entry
        try:
            with open(_project_file(self.config, name), "rb") as f:
                body = f.read()
        except OSError:
            return connection.respond(404, "Not found.")
        if name == "phone_client.html":   # the same substitutions Jarvis's own server makes (phone_control.py)
            body = (body.decode("utf-8").replace("__VAPID_PUBLIC_KEY__", "").replace("__COMPUTER_ID__", "")
                    .replace("__LOCAL_ADDRESS__", "").replace("__SERVED_BY_RELAY__", "0")
                    .replace("__ACTIVE_PAIR_CODE__", "").encode("utf-8"))
        from websockets.datastructures import Headers
        from websockets.http11 import Response
        headers = Headers()
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))
        headers["Cache-Control"] = cache
        return Response(200, "OK", headers, body)

    async def _handle(self, websocket) -> None:
        remote = getattr(websocket, "remote_address", None)
        if not _private(remote[0] if remote else ""):
            await websocket.close(1008, "not allowed")
            return
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            kind = data.get("type")
            if kind == "hello":
                await websocket.send(json.dumps({"type": "hello_ok"}))
            elif kind in ("auto_attach", "session_attach"):
                if not phone_is_paired(self.config, str(data.get("deviceId") or ""), str(data.get("token") or "")):
                    log.info("Phone door: a phone that isn't paired with this Mac tried to open Jarvis; ignored.")
                    # Never "unpaired": this isn't Jarvis, and a phone must not drop its pairing on our say-so.
                    await websocket.send(json.dumps({"type": "wake_refused",
                                                     "message": "Jarvis isn't open on your computer."}))
                    await websocket.close()
                    return
                if data.get("wake") is False:
                    # The app reconnecting by itself (e.g. Jarvis was just quit while it sat open): quitting Jarvis
                    # should stick. Only opening the app, or tapping "Open Jarvis" in it, starts him.
                    await websocket.send(json.dumps({"type": "jarvis_closed"}))
                    await websocket.close()
                    return
                log.info("Phone door: your paired phone opened the app; starting Jarvis.")
                claimed = claim_launch(self.config)   # before closing, so the keeper doesn't reopen the port meanwhile
                await websocket.send(json.dumps({"type": "waking"}))
                await websocket.close()
                self._server.close()   # step aside now, so Jarvis can take the port the moment he's ready
                if claimed:
                    threading.Thread(target=launch_jarvis, args=(self.config, False), daemon=True).start()
                return
            elif kind == "pair":
                await websocket.send(json.dumps({"type": "pair_error", "message":
                    "Jarvis isn't open on your computer. Open it, then say “Connect my phone” again."}))


def keep_phone_door(config: dict) -> None:
    """Holds Jarvis's phone port exactly while Jarvis isn't running (and isn't just starting up)."""
    door = PhoneDoor(config)
    while True:
        try:
            if jarvis_running(config) or recently_launched() or not phone_control_on(config):
                door.stop()
            else:
                door.start()
        except Exception:
            log.exception("Phone door problem; trying again shortly.")
        time.sleep(CHECK_JARVIS_EVERY)


# ---------- the same, away from home: through the relay ----------
# The phone's always-on app talks to Jarvis through a relay (relay/server.py), which only passes messages between "a
# computer" and "a phone". While Jarvis is closed, this signs in there as this computer, so a paired phone can still
# open Jarvis. The phone proves itself exactly as it does to Jarvis (phone_session.verify_attach_proof): an envelope
# only that phone's own key could have sealed, naming itself and a recent time. Nothing else is ever answered.
DEFAULT_RELAY = "wss://jervis-relay.onrender.com/"   # settings.py's default for JARVIS_RELAY_URL
ATTACH_PROOF_WINDOW = 10 * 60                        # phone_session.ATTACH_PROOF_WINDOW


def relay_address(config: dict) -> str:
    """Jarvis's relay address (Settings, Computer control): the default unless the user changed or cleared it."""
    try:
        with open(_project_file(config, "settings.json"), encoding="utf-8") as f:
            values = json.load(f).get("values", {})
    except (OSError, ValueError):
        values = {}
    value = values.get("JARVIS_RELAY_URL", values.get("JE" + "RVIS_RELAY_URL"))
    return DEFAULT_RELAY if value is None else str(value).strip()


def computer_id(config: dict) -> str:
    try:
        with open(_project_file(config, "relay_identity.json"), encoding="utf-8") as f:
            return str(json.load(f).get("computerId") or "")
    except (OSError, ValueError):
        return ""


def proof_is_from_paired_phone(config: dict, device_id: str, proof) -> bool:
    """True only for an attach proof sealed with that paired device's own key, minutes old at most."""
    try:
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with open(_project_file(config, "phone_devices.json"), encoding="utf-8") as f:
            device = json.load(f).get("devices", {}).get(device_id or "")
        if not device or not isinstance(proof, dict):
            return False
        pad = lambda t: t + "=" * (-len(t) % 4)
        key = base64.urlsafe_b64decode(pad(device["key_b64"]))
        plain = AESGCM(key).decrypt(base64.urlsafe_b64decode(pad(str(proof["n"]))),
                                    base64.urlsafe_b64decode(pad(str(proof["ct"]))), None)
        message = json.loads(plain.decode("utf-8"))
        return (message.get("type") == "attach" and message.get("deviceId") == device_id
                and abs(time.time() - float(message.get("ts")) / 1000) <= ATTACH_PROOF_WINDOW)
    except Exception:   # a wrong key, a tampered or malformed proof, a missing file: all simply "no"
        return False


async def _relay_door(config: dict, url: str, ident: str, should_hold) -> None:
    import websockets
    async with websockets.connect(url, open_timeout=60, ping_interval=20, ping_timeout=30) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "computer", "computerId": ident}))
        log.info("Relay door open: your phone can open Jarvis from anywhere.")
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=CHECK_JARVIS_EVERY)
            except asyncio.TimeoutError:
                if not should_hold():
                    return   # Jarvis is up (or phone control was switched off): the relay is his now
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            kind = data.get("type")
            if kind == "get_page_context":   # the relay serving the app's page: nothing to add while Jarvis is closed
                await ws.send(json.dumps({"type": "page_context", "requestId": data.get("requestId"),
                                          "vapidKey": "", "localAddress": ""}))
                continue
            payload = data.get("payload") if kind == "frame" else None
            if not isinstance(payload, dict):
                continue
            reply = lambda message: ws.send(json.dumps({"type": "frame", "connId": data.get("connId"), "payload": message}))
            if payload.get("type") == "pair_secure":
                # A phone scanning a pairing code: only Jarvis himself pairs, and he's closed (so the code is an old
                # one). Said plainly, so the app can tell the user at once instead of waiting for an answer.
                await reply({"type": "jarvis_closed"})
                continue
            if payload.get("type") not in ("auto_attach", "session_attach"):
                continue
            if not proof_is_from_paired_phone(config, str(payload.get("deviceId") or ""), payload.get("proof")):
                log.info("Relay door: something that isn't a paired phone tried to open Jarvis; ignored.")
                await reply({"type": "wake_refused", "message": "Jarvis isn't open on your computer."})
                continue
            if payload.get("wake") is not True:
                # Only an app that was just opened on "On my computer" (or its "Open Jarvis" button) asks to wake:
                # a background reconnect, or the phone's own Jarvis, must never open Jarvis here.
                await reply({"type": "jarvis_closed"})
                continue
            log.info("Relay door: your paired phone asked for Jarvis; starting Jarvis.")
            claimed = claim_launch(config)
            await reply({"type": "waking"})
            if claimed:
                threading.Thread(target=launch_jarvis, args=(config, False), daemon=True).start()
            return   # step aside: Jarvis signs in to the relay himself once he's up


def keep_relay_door(config: dict, stop: threading.Event = None) -> None:
    """Holds this computer's place on the relay exactly while Jarvis isn't running, as keep_phone_door does the port.
    stop: set it to end the keeper (the tests do; Jarvis Wake itself runs it for as long as it lives)."""
    stopped = lambda: stop is not None and stop.is_set()
    should_hold = lambda: not (stopped() or jarvis_running(config) or recently_launched() or not phone_control_on(config))
    try:
        import cryptography  # noqa: F401   (without it a phone can't be verified: no relay door, the Wi-Fi one still works)
        import websockets    # noqa: F401
    except ImportError:
        log.info("Relay door unavailable (run wake/install.sh once to add it); the Wi-Fi phone door still works.")
        return
    while not stopped():
        try:
            url, ident = relay_address(config), computer_id(config)
            if url and ident and should_hold():
                asyncio.run(_relay_door(config, url, ident, should_hold))
                log.info("Relay door closed.")
        except Exception as e:   # the relay asleep or unreachable, no internet: quietly try again
            log.debug("Relay door: %r", e)
        time.sleep(CHECK_JARVIS_EVERY * 2)


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
            if jarvis_running(self.config):
                time.sleep(3)          # Jarvis listens for himself; the microphone stays closed here
                continue
            try:
                woken = self.listen_until_woken(sd, np)
            except sd.PortAudioError as e:
                log.warning("Microphone unavailable (%s); trying again in 5 s.", e)
                time.sleep(5)
                continue
            if not woken:
                continue               # Jarvis was opened some other way
            log.info("Wake phrase heard: starting Jarvis.")
            if launch_jarvis_once(self.config, voice=True):
                deadline = time.time() + AFTER_LAUNCH_GRACE
                while time.time() < deadline and not jarvis_running(self.config):
                    time.sleep(1)

    def listen_until_woken(self, sd, np) -> bool:
        """True when a wake phrase was heard; False when Jarvis was started some other way. Either way the
        microphone is closed when this returns."""
        self.new_recognizer()
        pre_roll = collections.deque(maxlen=PRE_ROLL)
        talking_until = 0.0
        silent_since = time.time()
        last_check = time.time()
        with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16") as stream:
            log.info("Listening for “Hey Jarvis”, “Wake up Jarvis” or “Hello Jarvis”.")
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
                    log.warning("The microphone gives only silence. Allow “Jarvis Wake” in System Settings, "
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

                if now - last_check > CHECK_JARVIS_EVERY:
                    last_check = now
                    if jarvis_running(self.config):
                        return False


def check() -> int:
    """`jarvis_wake.py --check`: everything loads (packages, speech model, settings), without opening the microphone."""
    import numpy  # noqa: F401
    import sounddevice  # noqa: F401
    import vosk
    import websockets  # noqa: F401   (the phone door)
    vosk.SetLogLevel(-1)
    config = load_config()
    vosk.KaldiRecognizer(vosk.Model(MODEL), RATE, GRAMMAR)
    ready = os.path.exists(config["electron"])
    print(f"Jarvis Wake: ready. Jarvis: {config['project']} (window {'found' if ready else 'MISSING'}).")
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
    log.info("Jarvis Wake started (Jarvis: %s).", config["project"])
    threading.Thread(target=keep_phone_door, args=(config,), daemon=True, name="phone-door-keeper").start()
    threading.Thread(target=keep_relay_door, args=(config,), daemon=True, name="relay-door-keeper").start()
    listener = Listener(config)
    while True:
        try:
            listener.run()
        except Exception:                      # never die for good: log, breathe, start over
            log.exception("Unexpected problem; restarting the listener in 5 s.")
            time.sleep(5)


if __name__ == "__main__":
    main()
