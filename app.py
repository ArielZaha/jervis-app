import asyncio
import json
import os

import osal  # first: installs the macOS safeguard so no launch ever forks this multi-threaded process

try:  # running app.py by hand skips the first-run setup; say what to do instead of a wall of errors
    import dotenv, groq, psutil, requests, speech_recognition, spotipy, websockets  # noqa: F401
except ImportError as _missing:
    raise SystemExit(
        f"\nJervis is missing a Python package ({_missing.name}). Don't run app.py directly.\n"
        "  Windows: double-click start_jervis.bat (or run:  py -3 run.py)\n"
        "  Mac:     python3 run.py\n"
        "The first run installs everything Jervis needs.\n")
import paths  # noqa: E402  where Jervis reads his files and where he writes (see paths.py)
import logbook  # noqa: E402
import settings  # noqa: E402
logbook.install()   # before anything prints, so startup problems end up in logs/jervis.log too
settings.load()     # before any module reads its configuration from the environment
import platform
import re
import shutil
import subprocess
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import quote
import hmac
import signal
import sys
import urllib.parse

import speech_recognition as sr
try:
    import pyttsx3  # only used as a last-resort voice on systems without say / PowerShell / espeak
except ImportError:
    pyttsx3 = None
import spotipy
import websockets
import psutil
import requests
from spotipy.oauth2 import SpotifyOAuth
from groq import Groq
from dotenv import load_dotenv

from app_launcher import _site_for, open_application, parse_open_request, resolve_app
from youtube_browser import close_tabs, control_playback, open_in_site_tab, open_youtube, youtube_is_playing
import netflix
import stremio
from volume import change_volume
import documents
import google_accounts
import local_llm
import local_ai
import stt_local
import osal
import calendar_api
import calendar_time
import classroom
import earth
import equations
import functions
import graphs
import images
import planets
import whatsapp
import queue
from timers import TimerManager, format_duration, parse_timer_command
from speech_fixes import fix_names
from timeparse import format_time, parse_start_time

APP_DIR = paths.RESOURCE_DIR  # Jervis's own files; everything he writes goes to paths.DATA_DIR instead
load_dotenv(os.path.join(APP_DIR, ".env"))  # settings.load() already applied .env; this only keeps old setups identical

GROQ_MODEL = "openai/gpt-oss-20b"
STT_MODEL = "whisper-large-v3-turbo"
# Which AI answers: "auto" = the online AI (Groq) and, if it can't be reached, the local one (Ollama); "groq" or "ollama" force one.
LLM_BACKEND = (os.getenv("LLM_BACKEND") or "auto").strip().lower()
groq_down_until = 0.0  # while Groq is known to be unreachable, skip straight to the local AI instead of waiting for timeouts
GROQ_KEY = (os.getenv("GROQ_API_KEY") or "").strip().strip("\"'")  # tolerate spaces or quotes pasted around the key
groq_client = Groq(api_key=GROQ_KEY or "missing-key")
if LLM_BACKEND == "local":
    LLM_BACKEND = "ollama"
if not GROQ_KEY and LLM_BACKEND in ("auto", "groq"):
    LLM_BACKEND = "ollama"   # no online AI key: the AI on this computer is the AI (no account or key needed)

# How this backend was started. The installed app (and `npm start`) runs it as a child of the window, which picks a
# free port and a secret for the window connection, and restarts the backend when it exits with RESTART_EXIT_CODE.
SUPERVISED = os.getenv("JERVIS_SUPERVISED") == "1"
WS_HOST = "127.0.0.1"
WS_PORT = int(os.getenv("JERVIS_WS_PORT") or 8765)
WS_TOKEN = os.getenv("JERVIS_WS_TOKEN") or ""
RESTART_EXIT_CODE = 75
PORT_BUSY_EXIT_CODE = 76
AUDIO_OFF = os.getenv("JERVIS_AUDIO", "on").strip().lower() == "off"   # tests: typed input only, replies printed

sp = None
try:
    if os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_SECRET"):
        sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=os.getenv("SPOTIFY_CLIENT_ID"),
                client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
                redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
                scope="user-modify-playback-state user-read-playback-state",
                cache_handler=spotipy.cache_handler.CacheFileHandler(cache_path=paths.data(".cache")),
            )
        )
except Exception as e:
    print(f"Spotify Init Warning: {e}")

# Voice capture settings tuned for normal room noise and conversational volume.
# The noise floor is calibrated once at startup (and recalibrated every few minutes while asleep, see listen()).
# Dynamic re-adjustment is OFF: it recalculates the threshold on every recognizer.listen() call, and listening in
# short slices (see listen_or_typed) so that typing is noticed quickly means many calls a second, which used to make
# the threshold decay toward zero within seconds in a quiet room, and then Jervis genuinely couldn't hear anyone.
recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = False
recognizer.pause_threshold = 1.0
recognizer.phrase_threshold = 0.3
recognizer.non_speaking_duration = 0.5
MIN_ENERGY_THRESHOLD = 30   # a floor just to guard against a bad (near-zero) calibration; well below a normal room's own reading
RECALIBRATE_EVERY = 180     # seconds; keeps up with a room that slowly gets noisier or quieter without the decay bug
MIN_PHRASE_SECONDS = 0.4
POST_SPEECH_PAUSE = 0.4  # Lets the speaker's tail fade so Jervis doesn't hear itself.
mic_calibrated = False
last_calibrated_at = 0.0
# The window's "stop and listen" button (or Space) sets this to cut Jervis off mid-sentence.
interrupt_speech = threading.Event()

tts_engine = None  # created on first use, and only when the operating system has no better voice


def get_tts_engine():
    global tts_engine
    if tts_engine is None and pyttsx3 is not None:
        tts_engine = pyttsx3.init()
    return tts_engine

TRANSCRIPTS_DIR = paths.transcripts_dir()
session_file = os.path.join(
    TRANSCRIPTS_DIR, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
)

connected_clients = set()
ws_loop = None
ws_loop_ready = threading.Event()
mic_muted = threading.Event()

# Wake-word state: Jervis stays passively listening (only checking for the
# wake phrase) until woken, then behaves exactly as before until a shutdown
# phrase puts it back to sleep instead of exiting the process.
WAKE_PHRASES = ["hi", "hello", "wake up jervis", "wake up jarvis", "hey jervis", "ok jervis", "okay jervis"]
awake = False
ui_launched = False
youtube_active = False  # True once Jervis started a YouTube video; routes pause/resume there.
netflix_active = False  # Same for a Netflix show.
DEFAULT_MEDIA_APP = "stremio"  # Where "play the show X" goes before any media app has been used.
stremio_active = False  # Same for a Stremio title (controlled with key presses).
last_media_app = None  # "stremio" or "netflix": the one used most recently, for "play the show X".


def is_wake_command(text: str) -> bool:
    # Whole-word match: a plain substring test made "hi" fire on "this", "thinking", etc.
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    return any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in WAKE_PHRASES)


_EXPLICIT_WAKE = re.compile(r"(?:(?:hey|hi|hello|ok|okay|wake up|wake)\s+)?(?:jervis|jarvis)(?:\s+(?:wake up|are you there|you there))?|wake up|are you there")


def is_explicit_wake(text: str) -> bool:
    """Just "Hey Jervis" / "Wake up Jervis" said on its own (also while he is already awake): the window goes full screen."""
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    return bool(_EXPLICIT_WAKE.fullmatch(normalized))


ui_process = None
ui_failures = 0  # times the window died right after starting; after two Jervis stops retrying until restarted


def find_npm():
    """Where npm lives. run.py passes the path it found (a freshly installed Node.js is not on PATH yet)."""
    found = os.getenv("JERVIS_NPM") or shutil.which("npm.cmd" if platform.system() == "Windows" else "npm") or shutil.which("npm")
    if found:
        return found
    for folder in ("/opt/homebrew/bin", "/usr/local/bin"):  # where Homebrew puts it, which a background launch does not have on PATH
        candidate = os.path.join(folder, "npm")
        if os.path.exists(candidate):
            return candidate
    return None


def _watch_window_start(process) -> None:
    """If the window dies right after starting, say why in the console instead of failing silently."""
    time.sleep(10)
    global ui_failures
    code = process.poll()
    if code not in (None, 0):
        ui_failures += 1
        print(f"\nThe Jervis window closed right after starting (code {code}).\n"
              "  - Is Node.js installed?  Open a new terminal and run:  node --version\n"
              "  - Try once by hand in the Jervis folder:  npm install   then   npm start\n", flush=True)


fullscreen_pending = False  # a wake-up asked for a full-screen window that has not connected yet


def show_fullscreen():
    """Open the window (if needed) and make it full screen. Used when Jervis is woken up."""
    global fullscreen_pending
    if connected_clients:
        send_ui_update_once({"type": "fullscreen"})
    else:
        fullscreen_pending = True   # sent as soon as the window connects
        launch_ui()


def launch_ui():
    """Open the Electron window (again, if it was closed). Does nothing while it is running.

    When the window started this backend (SUPERVISED), the window already exists and owns it: nothing to launch.
    Otherwise (a backend started by the wake listener or by run.py without the window), the window is started and
    told to attach to this backend instead of starting a second one."""
    global ui_launched, ui_process
    if SUPERVISED:
        return
    if connected_clients or (ui_process is not None and ui_process.poll() is None):
        return
    if ui_failures >= 2 or os.getenv("JERVIS_NO_WINDOW") == "1":
        return
    npm = find_npm()
    if not npm:
        print("\nThe Jervis window can't open because Node.js is not installed.\n"
              "  Install it from https://nodejs.org (the LTS version), then start Jervis again.\n", flush=True)
        return
    try:
        env = {**os.environ, "PATH": os.path.dirname(npm) + os.pathsep + os.environ.get("PATH", ""),  # so npm finds node
               "JERVIS_ATTACH_PORT": str(WS_PORT), "JERVIS_WS_TOKEN": WS_TOKEN}
        env.pop("ELECTRON_RUN_AS_NODE", None)   # set in VS Code's terminal; it would start Electron as plain Node
        print("Opening the Jervis window...", flush=True)
        ui_process = subprocess.Popen([npm, "start"], cwd=APP_DIR, env=env)
        ui_launched = True
        threading.Thread(target=_watch_window_start, args=(ui_process,), daemon=True).start()
    except Exception as e:
        print(f"Could not launch the Jervis window: {e}", flush=True)


async def _send_payload_async(payload_dict):
    if not connected_clients:
        return
    payload = json.dumps(payload_dict)
    for ws in list(connected_clients):
        try:
            await ws.send(payload)
        except Exception:
            connected_clients.discard(ws)


class PrivateReply(str):
    """A reply that contains someone's private messages (WhatsApp). It is spoken and shown, but never written to the
    transcript file and never added to what the online AI remembers."""


class SpokenReply(str):
    """A reply that carries its own spoken version (used when one message asked for several things)."""
    spoken = ""


class ImageCaption(str):
    """Text typed alongside an uploaded image: already shown to the window together with the image (see
    handle_client), so the main loop must not broadcast it again as a second, plain bubble."""


PRIVATE_PLACEHOLDER = "[private WhatsApp messages: shown and read aloud only]"


def broadcast(sender, text="", image=None, image_kind=None):
    """Show (and, unless private, log) a chat message. `image` is a data: URL, for a picture the user attached or
    Jervis made/edited; `text` may be empty when a message is only a picture."""
    private = isinstance(text, PrivateReply)
    text = str(text).strip() if text else ""
    if not text and not image:
        return
    if os.getenv("JERVIS_KEEP_TRANSCRIPTS", "on") != "off":   # the user can switch conversation logs off in Settings
        try:
            with open(session_file, "a", encoding="utf-8") as f:
                label = "You" if sender == "user" else "Jervis"
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {label}: {PRIVATE_PLACEHOLDER if private else (text or '[image]')}\n")
        except OSError as e:
            print(f"Could not write the conversation log: {e}", flush=True)
    if ws_loop:
        payload = {"sender": sender, "text": text}
        if image:
            payload["image"] = image
            if image_kind:
                payload["imageKind"] = image_kind
        asyncio.run_coroutine_threadsafe(_send_payload_async(payload), ws_loop)


def send_status(status):
    if ws_loop:
        asyncio.run_coroutine_threadsafe(
            _send_payload_async({"status": status}), ws_loop
        )


latest_ui_updates = {}  # last payload per type, replayed to windows that connect later


def send_ui_update_once(payload: dict) -> None:
    """Send a one-off message to the window (not replayed to windows that connect later)."""
    if ws_loop:
        asyncio.run_coroutine_threadsafe(_send_payload_async(payload), ws_loop)


def send_ui_update(data_type, data):
    latest_ui_updates[data_type] = {"type": data_type, "data": data}
    if ws_loop:
        asyncio.run_coroutine_threadsafe(
            _send_payload_async({"type": data_type, "data": data}), ws_loop
        )


pending_alerts = []  # timer alerts that fired while no window was open; shown when it connects
alerts_open = 0  # how many alert cards the window is showing


def _connection_allowed(websocket) -> bool:
    """Only Jervis's own window may connect. A web page open in a browser can also reach 127.0.0.1, so browser origins
    are refused, and when the window gave this backend a secret (JERVIS_WS_TOKEN) the connection must present it."""
    request = getattr(websocket, "request", None)
    headers = getattr(request, "headers", None) or {}
    origin = (headers.get("Origin") or "").lower()
    allowed = [o.strip().lower() for o in os.getenv("JERVIS_ALLOW_ORIGINS", "").split(",") if o.strip()]  # UI tests only
    if origin.startswith(("http://", "https://")) and origin not in allowed:
        return False
    if WS_TOKEN:
        query = urllib.parse.urlparse(getattr(request, "path", "") or "").query
        presented = urllib.parse.parse_qs(query).get("token", [""])[0]
        return hmac.compare_digest(presented, WS_TOKEN)
    return True


def list_microphones() -> list:
    """Names of the input devices, for the Settings screen (the same order PyAudio numbers them in)."""
    names = []
    try:
        import pyaudio
        audio = pyaudio.PyAudio()
        try:
            for i in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(i)
                if int(info.get("maxInputChannels", 0)) > 0 and info.get("name") not in names:
                    names.append(info.get("name"))
        finally:
            audio.terminate()
    except Exception as e:
        print(f"Could not list microphones: {e}", flush=True)
    return names


# Listing microphones and voices takes seconds (the audio system and the OS voice list are slow to ask), so they are
# gathered in the background and cached: Settings opens instantly, and refreshed lists arrive a moment later.
_devices = {"microphones": None, "voices": None}
_devices_lock = threading.Lock()


def refresh_devices() -> None:
    if not _devices_lock.acquire(blocking=False):
        return   # already refreshing
    try:
        _devices["microphones"] = list_microphones()
        _devices["voices"] = osal.list_voices()
        send_ui_update_once({"type": "settings_devices", "microphones": _devices["microphones"],
                             "voices": _devices["voices"]})
    except Exception as e:
        print(f"Could not list microphones and voices: {e}", flush=True)
    finally:
        _devices_lock.release()


def settings_payload() -> dict:
    threading.Thread(target=refresh_devices, daemon=True).start()   # a microphone may have been plugged in since
    return {"type": "settings", **settings.public_view(), "microphones": _devices["microphones"] or [],
            "voices": _devices["voices"] or [], "devicesLoading": _devices["microphones"] is None,
            "platform": osal.SYSTEM, "dataDir": paths.DATA_DIR, "logFile": logbook.log_path(), "backend": LLM_BACKEND}


def request_restart(reason: str) -> None:
    """Restart the backend to apply settings that are read once at startup."""
    print(f"Restarting to apply new settings ({reason}).", flush=True)

    def restart():
        time.sleep(0.8)   # let the window receive the reply first
        if SUPERVISED:
            os._exit(RESTART_EXIT_CODE)   # the window starts a fresh backend
        args = sys.argv[1:] if paths.FROZEN else sys.argv
        os.execv(sys.executable, [sys.executable, *args])
    threading.Thread(target=restart, daemon=True).start()


settings_changed = threading.Event()   # wakes loops that depend on a setting (the weather city)
# The AI on this computer: found or installed on first run, with progress shown in the window (see local_ai.py).
local_ai_manager = local_ai.LocalAI(report=lambda state: send_ui_update("setup", state))


async def handle_client(websocket):
    global alerts_open, fullscreen_pending
    if not _connection_allowed(websocket):
        print("Refused a connection that did not come from Jervis's window.", flush=True)
        await websocket.close(1008, "not allowed")
        return
    connected_clients.add(websocket)
    print(f"Window connected ({len(connected_clients)} open).", flush=True)
    try:
        for payload in list(latest_ui_updates.values()) + pending_alerts:
            await websocket.send(json.dumps(payload))
        alerts_open += len(pending_alerts)
        pending_alerts.clear()
        if fullscreen_pending:
            fullscreen_pending = False
            await websocket.send(json.dumps({"type": "fullscreen"}))
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue
            if data.get("type") == "mute":
                mic_muted.set()
            elif data.get("type") == "unmute":
                mic_muted.clear()
            elif data.get("type") == "interrupt":
                interrupt_speech.set()
                if tts_engine is not None:  # the fallback voice can't be stopped from outside, so ask it to
                    try:
                        tts_engine.stop()
                    except Exception:
                        pass
            elif data.get("type") == "text":  # something typed in the window instead of spoken
                typed = " ".join(str(data.get("text", "")).split())[:500]
                if typed:
                    typed_inputs.put(typed)
                    interrupt_speech.set()  # if Jervis is talking, stop so he can answer this
            elif data.get("type") == "image":  # a picture attached in the window, with an optional caption/instruction
                name = str(data.get("name", ""))[:120]
                caption = " ".join(str(data.get("text", "")).split())[:500]
                try:
                    info = images.ingest_upload(str(data.get("data", "")), name)
                except images.ImageError as e:
                    broadcast("ai", f"I couldn't use that image: {e}")
                else:
                    broadcast("user", caption, image=images.display_data_url(info["path"]), image_kind="upload")
                    if caption:
                        typed_inputs.put(ImageCaption(caption))
                        interrupt_speech.set()
                    else:
                        announcements.put("Got it — what would you like me to do with this image? I can describe "
                                           "it, read any text in it, compare it with another, or edit it if you tell "
                                           "me how.")
            elif data.get("type") == "setup_retry":
                local_ai_manager.start_background()
            elif data.get("type") == "get_settings":
                try:
                    payload = settings_payload()
                except Exception as e:
                    print(f"Could not build the settings screen: {e}", flush=True)
                    payload = {"type": "settings_error", "message": f"Settings couldn't be loaded ({e})."}
                await websocket.send(json.dumps(payload))
            elif data.get("type") == "set_settings":
                try:
                    result = settings.update(data.get("values") or {})
                except ValueError as e:
                    await websocket.send(json.dumps({"type": "settings_error", "message": str(e)}))
                except OSError as e:
                    await websocket.send(json.dumps({"type": "settings_error",
                                                     "message": f"The settings file couldn't be saved: {e}"}))
                else:
                    global mic_calibrated
                    if "JERVIS_MIC" in result["saved"]:
                        mic_calibrated = False   # a different microphone has a different noise level
                    settings_changed.set()
                    await websocket.send(json.dumps({"type": "settings_saved", **result}))
                    if result["restart"]:
                        request_restart(", ".join(result["saved"]))
            elif data.get("type") == "alert_dismissed":
                alerts_open = max(0, alerts_open - int(data.get("count", 1) or 1))
            elif data.get("type") == "snooze":
                seconds = max(1, min(int(data.get("seconds", 300)), 24 * 3600))
                timer_manager.add(seconds, str(data.get("label", ""))[:80], "timer")
    finally:
        connected_clients.discard(websocket)


def run_ws_server():
    global ws_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ws_loop = loop

    async def main():
        # The default 1 MiB frame limit is fine for ordinary chat/status messages, but an attached image (base64
        # inflates it ~33%, plus the data: URL prefix and JSON envelope) needs real headroom — images.py enforces
        # the actual size policy (MAX_UPLOAD_BYTES) once a message arrives, so this just has to not cut it off first.
        async with websockets.serve(handle_client, WS_HOST, WS_PORT, max_size=40 * 1024 * 1024):
            ws_loop_ready.set()
            await asyncio.Future()

    try:
        loop.run_until_complete(main())
    except OSError as e:
        if e.errno in (48, 98, 10048) or "address already in use" in str(e).lower():   # macOS, Linux, Windows
            if SUPERVISED:
                print(f"Port {WS_PORT} is taken; the window will pick another one.", flush=True)
                os._exit(PORT_BUSY_EXIT_CODE)
            print(f"\nJervis is already running (his window's connection, port {WS_PORT}, is taken).\n"
                  "  Use the copy that is running, or stop it first:  pkill -f app.py   (Windows: close the other Jervis console)\n"
                  "  then start Jervis again.\n", flush=True)
            os._exit(1)
        raise


# Background loops sending data to UI sidebars
def telemetry_loop():
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            battery = psutil.sensors_battery()
            bat_percent = battery.percent if battery else 100

            send_ui_update(
                "system_stats", {"cpu": cpu, "ram": ram, "battery": bat_percent}
            )
        except Exception:
            pass
        time.sleep(2)


WEATHER_CODES = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy showers", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def weather_loop():
    while True:
        delay = 600
        settings_changed.clear()
        try:
            city = os.getenv("WEATHER_CITY", "").strip()
            place = earth.geocode(city) if city else None
            if not place:
                send_ui_update("weather", {"city": "No city set" if not city else f"Can't find {city}",
                                           "temp": "--", "condition": "Choose your city in Settings"})
                settings_changed.wait(timeout=600 if not city else 120)
                continue
            url = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                   "&current=temperature_2m,weather_code").format(lat=place["lat"], lon=place["lon"])
            resp = requests.get(url, timeout=8).json()
            current = resp.get("current") or {}
            if "temperature_2m" in current:
                send_ui_update(
                    "weather",
                    {
                        "city": place["name"],
                        "temp": round(current["temperature_2m"]),
                        "condition": WEATHER_CODES.get(current.get("weather_code"), "Clear sky"),
                    },
                )
            else:
                delay = 30
        except Exception as e:
            print(f"Weather fetch failed: {e}")
            delay = 30  # retry soon instead of waiting 10 minutes with no data
        settings_changed.wait(timeout=delay)   # a new city in Settings refreshes the panel right away


def get_device_id():
    if not sp:
        return None
    try:
        devices = sp.devices()["devices"]
        if not devices:
            return None
        for d in devices:
            if d["is_active"]:
                return d["id"]
        return devices[0]["id"]
    except Exception:
        return None


def ensure_spotify_device(timeout: float = 20.0):
    """Return a Spotify device id, launching the Spotify app and waiting for it if none is available yet."""
    device_id = get_device_id()
    if device_id or not sp:
        return device_id
    try:
        open_application("Spotify")
    except Exception:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        device_id = get_device_id()
        if device_id:
            return device_id
    return None


def quit_application(app_name: str) -> str:
    """Close a named desktop app only when the user explicitly asks to quit it."""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["pkill", "-x", app_name], capture_output=True, text=True
            )
            if result.returncode == 1:
                return f"{app_name} is not currently running."
            result.check_returncode()
        elif platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/IM", f"{app_name}.exe", "/F"],
                check=True, capture_output=True, text=True
            )
        else:
            subprocess.run(["pkill", "-x", app_name], check=True, capture_output=True, text=True)
        return f"Closed {app_name}."
    except Exception as e:
        return f"I couldn't close {app_name}: {e}"


def _find_video_yt_dlp(query: str):
    """Return (video_id, title) via yt-dlp if it is installed, else None."""
    try:
        result = subprocess.run(
            ["yt-dlp", f"ytsearch1:{query}", "--print", "%(id)s\t%(title)s",
             "--skip-download", "--no-warnings"],
            capture_output=True, text=True, timeout=20
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if result.returncode == 0 and result.stdout.strip():
        parts = result.stdout.strip().splitlines()[0].split("\t", 1)
        video_id = parts[0].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id, (parts[1].strip() if len(parts) > 1 else query)
    return None


def _find_video_scrape(query: str):
    """Return (video_id, title) from the YouTube results page (no extra tools needed)."""
    try:
        html = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": query, "sp": "EgIQAQ%3D%3D"},  # filter: videos only
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            cookies={"CONSENT": "YES+1"},
            timeout=8,
        ).text
    except requests.RequestException:
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', html)
    if not m:
        return None
    title = re.search(r'"videoId":"%s".*?"title":\{"runs":\[\{"text":"(.*?)"' % m.group(1), html)
    return m.group(1), (title.group(1) if title else query)


def play_netflix_show(query: str, new_tab: bool = False, season=None, episode=None, **kwargs) -> str:
    """Open a show on Netflix in the existing Netflix tab (a new tab only when asked)."""
    global netflix_active, youtube_active, stremio_active
    query = (query or "").strip()
    if not query:
        return "Tell me which show you want on Netflix."
    found = netflix.find_title(query)
    picked, note = None, ""
    if found and (season or episode):
        picked = netflix.find_episode(found[0], season or 1, episode or 1)
        if not picked:
            note = f" I couldn't find season {season or 1} episode {episode or 1}, so it will continue where you left off."
    if picked:
        url = netflix.watch_url(picked[0])
    else:
        url = netflix.watch_url(found[0]) if found else netflix.search_url(query)
    open_in_site_tab(url, "netflix.com", context=query) if not new_tab else open_youtube(url, True, context=query)
    netflix_active, youtube_active, stremio_active = True, False, False
    remember_media_app("netflix")
    remember_played(found[1] if found else query)
    if picked:
        title = f": {picked[1]}" if picked[1] else ""
        return f"Playing {found[1]} season {season or 1} episode {episode or 1}{title} on Netflix."
    if found:
        return f"Playing {found[1]} on Netflix.{note}"
    return f"I couldn't pin down that title, so I opened a Netflix search for {query}."


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10,
}
_NUM = r"(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")"
_ORDINAL = r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
_SEASON_EPISODE_RE = re.compile(r"\bs(\d{1,2}) ?e(\d{1,3})\b")
# "3 season" would swallow the 3 of "episode 3 season 1", so the number-first form only takes ordinals.
_SEASON_RE = re.compile(rf"\bseason {_NUM}\b|\b{_ORDINAL} season\b|\bs(\d{{1,2}})\b")
_EPISODE_RE = re.compile(rf"\b(?:episode|ep) {_NUM}\b|\b{_ORDINAL} episode\b|\be(\d{{1,3}})\b")


def _to_int(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBER_WORDS[value]


def extract_season_episode(text: str):
    """Pull "season 1 episode 3" / "S1E3" / "third episode" out of text. Returns (rest, season, episode)."""
    season = episode = None
    m = _SEASON_EPISODE_RE.search(text)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        text = text[:m.start()] + " " + text[m.end():]
    m = _SEASON_RE.search(text)
    if m:
        season = _to_int(next(g for g in m.groups() if g))
        text = text[:m.start()] + " " + text[m.end():]
    m = _EPISODE_RE.search(text)
    if m:
        episode = _to_int(next(g for g in m.groups() if g))
        text = text[:m.start()] + " " + text[m.end():]
    return " ".join(text.split()), season, episode


def parse_service_request(text: str, service: str, allow_open: bool = False):
    """Parse "play <show> on <service>" style requests.

    Returns (show, kind, season, episode) or None. `kind` is "movie", "series" or "" when unspecified.
    """
    q = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower()).split())
    if service and not re.search(rf"\b{service}\b", q):
        return None
    service = service or "(?!)"  # no service named: the optional service words can never match
    # "open Stremio and play House": the launch part is done, keep only the request.
    q = re.sub(
        r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you) )*"
        rf"(?:open|launch|start)\s+(?:the\s+)?{service}(?:\s+(?:app|application))?\s+(?:and|then)\s+",
        "", q,
    )
    q = re.sub(r"\s+(?:in|on)\s+(?:a\s+|another\s+)?(?:new|another|separate|second)\s+(?:tab|window)\b", "", q)
    verbs = r"play|start|watch|put on|show me|search(?: for)?|find" + ("|open" if allow_open else "")
    filler = (r"(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?"
              r"(?:(?:please|can you|could you|would you|i want to|i wanna|i would like to|i'd like to|i need to|"
              r"let's|lets|go ahead and|just) )*")
    m = re.match(
        rf"^{filler}(?:{verbs})\s+(?:(?:in|on|with|using|from|at)\s+)?(?:{service}\s+)?"
        rf"(?:(?:the\s+)?(show|series|movie|film)\s+)?(?:{service}\s+)?(?:for\s+)?(.+?)"
        rf"(?:\s+(?:on|in|from|at|with|using)\s+{service})?$",
        q,
    )
    label = ""
    if m:
        label, show = m.group(1) or "", m.group(2)
    else:
        # Service first: "in the app Stremio play House".
        m = re.search(rf"\b{service}\s+(?:{verbs})\s+(?:(?:the\s+)?(show|series|movie|film)\s+)?(.+)$", q)
        if not m:
            return None
        label, show = m.group(1) or "", m.group(2)
    show, season, episode = extract_season_episode(show)
    show = re.sub(r"^(?:(?:and|then)\s+)+", "", show)
    show = re.sub(r"^(?:(?:the|a)\s+)?(?:(?:of|from|in)\s+)+", "", show)  # "the of of house" -> "house"
    show = re.sub(r"(?:\s+(?:on|in|at|from|with|using|to|and|the|a|an))+$", "", show)  # cut-off ends
    if (season or episode) and not label:
        label = "show"
    if show in {"", service, "the", "it"} or re.search(r"\b(browser|chrome|tab|window|website|site|app)$", show):
        return None
    kind = "movie" if label in {"movie", "film"} else "series" if label in {"show", "series"} else ""
    return show, kind, season, episode


_NOT_A_SHOW_REQUEST = re.compile(r"\b(youtube|spotify|song|songs|music|track|video|google|netflix|stremio)\b")


def parse_implicit_media_request(text: str):
    """"Play the show House" with no app named: needs an explicit show/movie/episode word."""
    if _NOT_A_SHOW_REQUEST.search((text or "").lower()):
        return None
    parsed = parse_service_request(text, None)
    if parsed and (parsed[1] or parsed[2] or parsed[3]):
        return parsed
    return None


_CHATTER = re.compile(r"\b(was|were|is|are|watched|yesterday|think|love|loved|hate|hated|great|good|bad ending|because|when|what|why|how)\b")


def parse_episode_request(text: str):
    """"Episode 3, Season 1, Breaking Bad": a show with an episode/season number and no verb or app."""
    q = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower()).split())
    q = re.sub(r"\b(?:(?:on|in|with|using|from|at)\s+)?(?:netflix|stremio)\b", " ", q)  # the app is picked by the caller
    q = " ".join(q.split())
    if _NOT_A_SHOW_REQUEST.search(q) or _CHATTER.search(q):
        return None
    rest, season, episode = extract_season_episode(q)
    if season is None and episode is None:
        return None
    rest = re.sub(
        r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
        r"(?:(?:play|watch|start|put on|show me|open|find)\s+)?(?:the\s+(?=(?:show|series|tv show)\b))?(?:(?:show|series|tv show)\s+)?", "", rest)
    rest = re.sub(r"^(?:(?:the|a)\s+)?(?:(?:of|from|in)\s+)+|(?:\s+(?:of|from|in|on|the|a))+$", "", rest).strip()
    rest = re.sub(r"^(?:the\s+)?(?:show|series)\s+", "", rest)
    if not rest or len(rest.split()) > 6:
        return None
    return rest, "series", season, episode


def remember_media_app(text: str) -> None:
    global last_media_app
    for name in ("stremio", "netflix"):
        if re.search(rf"\b{name}\b", (text or "").lower()):
            last_media_app = name


def play_stremio_title(query: str, kind: str = "", season=None, episode=None, **kwargs) -> str:
    """Open a movie or episode's stream list in the Stremio desktop app."""
    global netflix_active, youtube_active, stremio_active
    query = (query or "").strip()
    if not query:
        return "Tell me what you want to watch in Stremio."
    if not stremio.is_installed():
        return "I couldn't find the Stremio app on this computer."
    found = stremio.find_title(query, kind)
    if not found:
        ok = stremio.open_link(stremio.search_link(query))
        return (f"I couldn't pin down that title, so I searched Stremio for {query}."
                if ok else "I couldn't open Stremio.")
    imdb_id, name, real_kind = found
    if real_kind == "series" and episode and not season:
        season = 1
    if real_kind == "series" and season and not episode:
        episode = 1
    if not stremio.open_link(stremio.deep_link(imdb_id, real_kind, season, episode)):
        return "I couldn't open Stremio."
    netflix_active = youtube_active = False
    stremio_active = True
    remember_media_app("stremio")
    remember_played(name)
    detail = f" season {season} episode {episode}" if real_kind == "series" and season else ""
    return f"Opening {name}{detail} in Stremio."


def play_youtube_video(query: str, new_tab: bool = False, **kwargs) -> str:
    global youtube_active, netflix_active, stremio_active
    netflix_active = stremio_active = False
    query = (query or "").strip()
    if not query:
        return "Tell me which YouTube video you want."

    found = _find_video_yt_dlp(query) or _find_video_scrape(query)
    if found:
        video_id, title = found
        try:
            title = json.loads(f'"{title}"')  # decode \u0026 style escapes from the page
        except ValueError:
            pass
        open_youtube(f"https://www.youtube.com/watch?v={video_id}", new_tab, context=f"{query} {title}")
        youtube_active = True
        return f"Playing {title} on YouTube."

    open_youtube(f"https://www.youtube.com/results?search_query={quote(query)}", new_tab, context=query)
    return f"I couldn't pick a video automatically, so I opened YouTube results for {query}."


# ---------- Trailers: "show me the trailer of this series" ----------
suggested_titles = {"titles": [], "at": 0.0}  # titles from the last recommendation Jervis gave, in order
last_played = {"title": None, "at": 0.0}       # the last show or movie Jervis started
last_trailer = {"title": None, "at": 0.0}      # the last trailer Jervis showed, so "show me it on Netflix" knows what "it" is
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "last": -1}


def extract_titles(reply: str) -> list:
    """Titles a reply names, in order: the ones in **bold** or in quotation marks ("The Queen's Gambit")."""
    found = []
    for m in re.finditer(r"\*\*[\u201c\"]?([^*\n]{2,70}?)[\u201d\"]?\*\*|\u201c([^\u201d\n]{2,70})\u201d|\"([^\"\n]{2,70})\"", reply or ""):
        title = next(g for g in m.groups() if g).strip(" *_\u201c\u201d\".,:;")
        title = re.sub(r"\s*\((?:19|20)\d\d\)$", "", title).strip()  # "Dark (2017)" -> "Dark"
        words = title.split()
        if title and 1 <= len(words) <= 9 and title[0].isupper() or title[:1].isdigit():
            if not title.endswith("?") and title.lower() not in {t.lower() for t in found}:
                found.append(title)
    return found


def note_suggestions(reply: str) -> None:
    titles = extract_titles(reply)
    if titles:
        suggested_titles.update(titles=titles, at=time.time())


def remember_played(title: str) -> None:
    last_played.update(title=title, at=time.time())


_TRAILER_VERBS = r"(?:play|show|watch|see|open|find|put on|pull up|let me see|i want to see|i wanna see|i would like to see|i'd like to see|give me)"
_REFERENCE = re.compile(
    r"^(?:(?:this|that|these|those|the|it)(?: (?:series|show|movie|film|one|title|suggestion|recommendation))?"
    r"|(?:the )?(?:series|show|movie|film|one|title) (?:you|that you|which you) (?:just )?(?:suggested|recommended|mentioned|said)"
    r"|(?:the )?(?:first|second|third|fourth|last|1st|2nd|3rd|4th)(?: one| series| show| movie)?)$")


def parse_trailer_request(text: str):
    """Returns {"title": str or None, "ordinal": int or None} for "show me the trailer of X / this series / the second one"."""
    n = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    on_netflix = bool(re.search(r"\b(?:on|in|from|at|through|with)\s+netflix\b", n))
    # "Show me it on Netflix" right after a trailer: the same show's page on Netflix, where its trailer plays
    if on_netflix and not re.search(r"\btrailers?\b", n) and time.time() - last_trailer["at"] < 15 * 60 and last_trailer["title"] \
            and (follow := re.fullmatch(rf"(?:(?:hey |ok )?(?:jervis|jarvis) )?(?:(?:please|can you|could you) )*(?P<verb>{_TRAILER_VERBS}|put)\s+(?:me\s+)?"
                                        r"(?:it|that|this|the (?:trailer|series|show|movie|one))\s+(?:on|in|from|at|through|with)\s+netflix(?: please)?", n)):
        # after a trailer: "play/watch/put it on Netflix" starts the show, "open it" opens its page, "show me it" = its trailer
        verb = follow.group("verb").strip()
        mode = "show" if verb in ("play", "watch", "put", "put on") else "page" if verb == "open" else "trailer"
        return {"title": last_trailer["title"], "ordinal": None, "service": "netflix", "mode": mode, "hint": n}
    if not re.search(r"\btrailers?\b", n) or re.match(r"^(?:what|who|how|why|when|where|which|is|are|does|do)\b", n):
        return None
    # Peel away everything around the title, whatever the word order: "No, show me the trailer of X on Netflix",
    # "show me on Netflix the trailer for X", "X trailer please".
    n = re.sub(r"^(?:(?:no|nope|yes|yeah|yep|okay|ok|well|so|and|but|hmm|uh|um|oh|now|then|hey|alright|right)\s+)+", "", n)
    n = " ".join(re.sub(r"\b(?:on|in|from|at|through|with|via)\s+(?:netflix|youtube)\b", " ", n).split())  # where: see on_netflix
    n = re.sub(r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|would you|will you|i want to|i wanna|let's|lets) )*", "", n)
    n = re.sub(rf"^{_TRAILER_VERBS}\s+(?:me\s+)?", "", n)
    n = re.sub(r"^(?:the |a |an )?(?:official |new |latest )*", "", n)
    later = re.search(r"\btrailers?\s+(?:of|for|to|from)\s+(.+)$", n)
    if later:
        title = later.group(1)
    else:
        m = re.match(r"^(.+?)\s+(?:official )?trailers?\b.*$", n)
        title = m.group(1) if m else ""
    title = re.sub(r"\s+(?:please|for me|now|again)$", "", title).strip()
    if re.fullmatch(r"(?:season|part|series)\s*\d+", title):  # "the season 3 trailer OF Dark": the show comes after "of"
        title = later.group(1) if later else ""
    title = re.sub(r"^(?:the )?(?:series|show|movie|film|tv show)\s+(?:called |named )?", "", title) if not _REFERENCE.match(title) else title
    if re.search(r"\b(?:show me|play|watch|trailer|netflix|youtube)\b", title):  # left-over command words: not a title
        title = ""
    service = "netflix" if on_netflix else "youtube"
    if not title or title in {"official", "new"} or _REFERENCE.match(title):
        ordinal = next((_ORDINALS[w] for w in title.split() if w in _ORDINALS), None)
        return {"title": None, "ordinal": ordinal, "service": service, "hint": n}
    return {"title": title, "ordinal": None, "service": service, "hint": n}


def resolve_trailer_title(ordinal=None):
    """"this series" means what Jervis just recommended, or else what he just played (whichever is more recent)."""
    now = time.time()
    fresh_suggestion = suggested_titles["titles"] and now - suggested_titles["at"] < 30 * 60
    fresh_played = last_played["title"] and now - last_played["at"] < 30 * 60
    if fresh_suggestion and (not fresh_played or suggested_titles["at"] >= last_played["at"]):
        titles = suggested_titles["titles"]
        index = 0 if ordinal is None else ordinal
        return titles[index] if -len(titles) <= index < len(titles) else titles[0]
    return last_played["title"] if fresh_played else None


def play_netflix_trailer(title: str, hint: str = "", new_tab: bool = False) -> str:
    """Play the show's own trailer in Netflix's player. If Netflix lists none, play it from YouTube and say so."""
    global netflix_active, youtube_active, stremio_active
    lookup = re.sub(r"\s*\b(?:season|part|series)\s*\d+\s*$", "", title, flags=re.I).strip() or title  # "dark season 3" -> "dark"
    found = netflix.find_title(lookup)
    if found and not netflix.resembles(lookup, found[1]):
        found = None  # what came back has nothing to do with what was asked
    trailer = netflix.pick_trailer(netflix.find_trailers(found[0]), hint or title) if found else None
    if not trailer:
        result = play_youtube_video(f"{title} official trailer", new_tab=new_tab)
        remember_played(title)
        name = found[1] if found else title
        return f"Netflix doesn't list a trailer for {name}, so I played it from YouTube. " + (
            result[len("Playing "):] if result.startswith("Playing ") else result)
    url = netflix.watch_url(trailer["id"])
    open_in_site_tab(url, "netflix.com", context=title) if not new_tab else open_youtube(url, True, context=title)
    netflix_active, youtube_active, stremio_active = True, False, False
    remember_media_app("netflix")
    remember_played(found[1])
    return f"Playing the trailer for {found[1]} on Netflix."


def show_on_netflix(title: str, new_tab: bool = False) -> str:
    """Open the show's own page on Netflix: its trailer plays at the top, with the play button next to it."""
    global netflix_active, youtube_active, stremio_active
    found = netflix.find_title(title)
    url = netflix.title_url(found[0]) if found else netflix.search_url(title)
    open_in_site_tab(url, "netflix.com", context=title) if not new_tab else open_youtube(url, True, context=title)
    netflix_active, youtube_active, stremio_active = True, False, False
    remember_media_app("netflix")
    remember_played(found[1] if found else title)
    if found:
        return f"Here's {found[1]} on Netflix. Its trailer plays at the top."
    return f"I couldn't pin down that title, so I searched Netflix for {title}."


def play_trailer(request: dict, new_tab: bool = False) -> str:
    title = request["title"] or resolve_trailer_title(request["ordinal"])
    if not title:
        return "Which show or movie should I find the trailer for? Tell me its name."
    last_trailer.update(title=title, at=time.time())
    if request.get("service") == "netflix":
        mode = request.get("mode", "trailer")
        if mode == "show":
            return play_netflix_show(title, new_tab=new_tab)
        if mode == "page":
            return show_on_netflix(title, new_tab)
        return play_netflix_trailer(title, request.get("hint", ""), new_tab)
    part = re.search(r"\b(?:season|part|series)\s+\d+\b", request.get("hint", ""))
    query = title if (part and part.group(0) in title) else f"{title} {part.group(0) if part else ''}".strip()
    result = play_youtube_video(f"{query} official trailer", new_tab=new_tab)
    remember_played(title)
    if result.startswith("Playing "):
        return f"Here's the trailer for {title}: {result[len('Playing '):]}"
    return result


_VIDEO_VERBS = r"(?:play|start|watch|put on|show me)"


def is_youtube_command(text: str) -> bool:
    normalized = " ".join((text or "").lower().strip().split())
    return bool(
        re.search(r"\bplay\b.*\b(on )?youtube\b", normalized)
        or re.search(r"\byoutube\b.*\bplay\b", normalized)
        or re.search(r"\bopen\b.*\byoutube\b.*\bvideo\b", normalized)
        or re.search(rf"\b{_VIDEO_VERBS}\b.*\bvideo\b", normalized)
        or re.search(rf"\b{_VIDEO_VERBS}\b.*\bon youtube\b", normalized)
    )


def extract_youtube_query(text: str) -> str:
    """Pull the video topic out of phrasings like "Start Pink Floyd the video"."""
    q = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower()).split())
    q = re.sub(r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:please |can you |could you )*", "", q)
    q = re.sub(r"^(?:change|switch)\s+(?:the\s+|this\s+)?(?:song|video|track|music)?\s*(?:to\s+)?", "", q)
    q = re.sub(rf"^(?:{_VIDEO_VERBS}|youtube)\s+", "", q)
    q = re.sub(r"^(?:youtube\s+)?(?:play\s+)?", "", q)
    q = re.sub(r"\s+(?:in|on)\s+(?:a\s+|another\s+)?(?:new|another|separate|second)\s+(?:tab|window)\b", "", q)
    q = re.sub(r"\s+(?:on\s+)?youtube$", "", q)
    q = re.sub(r"\b(?:the|a|an)?\s*(?:youtube\s+)?(?:video|videos|clip)\b(?:\s+(?:of|for|about))?", " ", q)
    q = re.sub(r"^(?:the|a|an|some)\s+", "", q)
    q = " ".join(q.split())
    return "" if q in {"this", "that", "it", "one", "play"} else q


def wants_new_tab(text: str) -> bool:
    """Videos reuse the YouTube tab unless the user asks for another tab or window."""
    return bool(re.search(r"\b(new|another|separate|second)\s+(tab|window)\b", (text or "").lower()))


def youtube_playback_action(text: str):
    """Return "pause" / "resume" when the user wants to control the YouTube video."""
    normalized = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    mentions_youtube = bool(re.search(r"\b(youtube|video|netflix)\b", normalized))
    if re.search(r"\b(pause|stop|halt)\b", normalized):
        action = "pause"
    elif re.search(r"\b(resume|unpause|continue|keep playing)\b", normalized):
        action = "resume"
    else:
        return None
    if mentions_youtube:
        return action
    # A bare "stop the song" means YouTube if Jervis started a video this session
    # or a video is playing in Chrome; otherwise it is left for Spotify.
    if is_spotify_mention(normalized):
        return None
    if youtube_active or netflix_active or stremio_active or (action == "pause" and youtube_is_playing()):
        return action
    return None


def parse_volume_command(text: str):
    """Return (action, amount) for "volume up", "turn it down", "set volume to 40", "mute", else None."""
    n = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    m = re.search(r"\bvolume (?:to |at |on )?(\d{1,3})\b|\bset (?:the )?(?:volume|sound) (?:to )?(\d{1,3})\b", n)
    if m:
        return "set", min(100, int(next(g for g in m.groups() if g)))
    if re.search(r"\b(?:max|maximum|full) volume\b|\bvolume (?:to )?(?:max|maximum|full)\b", n):
        return "set", 100
    if re.search(r"\bhalf volume\b|\bvolume (?:to )?half\b", n):
        return "set", 50
    if re.search(r"\bunmute\b", n):
        return "unmute", None
    step = 25 if re.search(r"\b(a lot|much|way)\b", n) else 5 if re.search(r"\b(a little|a bit|slightly)\b", n) else None
    if re.search(r"\b(volume up|louder|higher volume|volume higher|crank it up)\b|"
                 r"\b(turn up|raise|increase|up) (?:the )?(?:volume|sound|music)\b|\bturn (?:it|the (?:volume|sound|music)) up\b", n):
        return "up", step
    if re.search(r"\b(volume down|quieter|softer|lower volume|volume lower)\b|"
                 r"\b(turn down|lower|decrease|reduce|down) (?:the )?(?:volume|sound|music)\b|\bturn (?:it|the (?:volume|sound|music)) down\b|\blower it\b", n):
        return "down", step
    if re.search(r"\bmute\b", n) and not re.search(r"\b(youtube|video|netflix|stremio)\b", n):
        return "mute", None
    return None


def parse_spotify_request(text: str):
    """"Play on Spotify, Echoes by Pink Floyd, minute two" -> ("echoes pink floyd", 120)."""
    seconds, n = parse_start_time(text)
    if not re.search(r"\bspotify\b", n):
        return None
    m = re.match(
        r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
        r"(?:play|put on|start|listen to)\s+(.+)$", n)
    if not m:
        return None
    query = re.sub(r"\b(?:(?:on|in|with|using|from)\s+)?spotify\b", " ", m.group(1))
    query = re.sub(r"\b(?:the\s+)?(?:song|track|music)\b", " ", query)
    query = re.sub(r"\bby\b", " ", query)
    query = " ".join(query.split())
    return (query, seconds) if query else None


def parse_seek_command(text: str):
    """"Go to minute 5" / "skip to 2:30" -> seconds, else None."""
    n = " ".join(re.sub(r"[^a-z0-9': ]", " ", (text or "").lower()).split())
    if re.search(r"\b(play|put on|watch)\b", n) or not re.search(r"\b(go|skip|jump|seek|fast forward|move|scrub|rewind)\b.{0,20}\b(to|at)\b", n):
        return None
    return parse_start_time(n)[0]


def parse_track_skip(text: str):
    """"Skip the song", "next track", "play the previous song" -> "next" / "previous", else None."""
    n = " ".join(re.sub(r"[^a-z0-9': ]", " ", (text or "").lower()).split())
    if (re.search(r"\b(episode|season|netflix|stremio|show|tab|window|volume)\b", n)
            or parse_start_time(n)[0] is not None or is_restart_command(n)):
        return None
    if re.search(r"\b(previous|prior|last|back)\b.{0,20}\b(song|track|one|music)\b|\bgo back\b|\bsong before\b|"
                 r"\bplay (?:the )?(?:previous|last) (?:song|track|one)\b|\bprevious\b", n):
        return "previous"
    if re.search(r"\bskip\b(?! to\b)|\bnext\b.{0,12}\b(song|track|one|music|video)\b|\b(?:play )?(?:the )?next (?:song|track|one)\b|"
                 r"^next$|\banother (?:song|track)\b|\bdifferent (?:song|track)\b", n):
        return "next"
    return None


def parse_read_document(text: str) -> bool:
    """"Read the story you created", "read it to me", "read me the document"."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    return bool(re.search(r"\b(read|recite)\b.{0,25}\b(story|document|doc|poem|letter|essay|list|note|text|it|that|this|what you (?:wrote|created|made))\b", n)
                and not re.search(r"\b(news|weather|email|emails|message|messages|book)\b", n))


def is_restart_command(text: str) -> bool:
    """"Start the episode from the beginning", "restart the video", "start over", "play it again"."""
    n = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    if re.search(r"\b(computer|mac|laptop|pc|jervis|jarvis|app|application|system)\b", n):
        return False
    return bool(re.search(
        r"\bfrom (?:the )?(?:beginning|start|top)\b|\bstart over\b|\bbegin again\b|\b(?:restart|replay)\b|"
        r"\b(?:rewind|go back|skip back) to (?:the )?(?:beginning|start)\b|\bplay (?:it|that|this)? ?again\b|"
        r"\b(?:start|begin|play) (?:the |this |that )?(?:song|track|video|episode|show|movie|it) (?:over|again)\b", n))


def is_youtube_followup(text: str) -> bool:
    """While a YouTube video is active, "play/change/switch to X" stays on YouTube."""
    if not youtube_active:
        return False
    normalized = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    if is_spotify_mention(normalized):
        return False
    return bool(re.search(r"\b(play|change|switch|put on)\b", normalized))


def is_spotify_mention(normalized: str) -> bool:
    return bool(re.search(r"\b(spotify)\b", normalized))


_TAB_WORDS = r"(?:tabs?|tubes?|pages?)"  # "tube" is what "tab" is often heard as
_ACTIVE_WORDS = {"", "current", "active", "open", "browser", "chrome", "google chrome", "this", "that", "one", "last"}


def parse_close_command(text: str):
    """"Close the YouTube tab" / "close all the Netflix tabs" / "close the Breaking Bad tab" / "close the other tabs"
    -> {"target": "youtube", "mode": "one"|"all"|"active"|"other"|"everything"}, else None."""
    n = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    m = re.search(r"\bclose\b\s+(.*)$", n)
    if not m:
        return None
    rest = re.sub(r"\b(please|now|for me|jervis|jarvis|right now|thanks|thank you)\b", " ", m.group(1))
    rest = re.sub(r"\b(?:on|in|from)\s+(?:google|chrome|google chrome|the browser|browser|my browser)\b", " ", rest)  # "YouTube tab on Google"
    has_tab_word = bool(re.search(rf"\b{_TAB_WORDS}\b", rest))
    plural = bool(re.search(r"\b(tabs|tubes|pages)\b", rest))
    every = bool(re.search(r"\b(all|every|both|those|these)\b", rest))
    other = bool(re.search(r"\b(other|others|rest|remaining)\b", rest))
    target = re.sub(rf"\b(the|my|this|that|a|an|all|every|both|those|these|other|others|rest|remaining|of|on|in|it|"
                    rf"with|called|named|titled|about|window|windows|{_TAB_WORDS})\b", " ", rest)
    target = " ".join(target.split())
    if not has_tab_word:
        # "close YouTube" / "close Netflix": only for names that are websites (not apps like Chrome or Spotify)
        from app_launcher import SITES
        from youtube_browser import _SITES, _TAB_ALIASES
        if not target or not (target in _SITES or target in _TAB_ALIASES or target in SITES) or target == "google chrome":
            return None
    if other:
        return {"target": "", "mode": "other"}
    if target in _ACTIVE_WORDS:
        return {"target": "", "mode": "everything" if (every and plural) else "active"}
    return {"target": target, "mode": "all" if (plural or every) else "one"}


pending_confirmation = None  # {"do": callable, "asked": text, "at": time}: a drastic action waiting for a spoken "yes"


def handle_close_command(text: str):
    """Close the tabs the user asked for. Closing lots of tabs asks "are you sure?" first."""
    global youtube_active, netflix_active, pending_confirmation
    command = parse_close_command(text)
    if command is None:
        return None
    target, mode = command["target"], command["mode"]

    def do_it():
        global youtube_active, netflix_active
        if target in {"youtube"} or mode in ("everything", "other"):
            youtube_active = False
        if target in {"netflix"} or mode in ("everything", "other"):
            netflix_active = False
        return close_tabs(target, mode)

    if mode in ("other", "everything"):
        pending_confirmation = {"do": do_it, "at": time.time()}
        return ("That will close all the other tabs in this window. Say yes to confirm." if mode == "other"
                else "That will close every tab in this window. Say yes to confirm.")
    return do_it()


# ---------- WhatsApp: "do I have unread messages?", "what did Dana write me?" (reading only, all on this Mac) ----------
last_whatsapp = {"at": 0.0}
_WA = re.compile(r"\bwhats ?app\b")


def parse_whatsapp_request(text: str):
    """Returns {"action": "check" | "read_unread" | "read_chat" | "send", "name": str} or None."""
    n = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    mentioned = bool(_WA.search(n))
    fresh = time.time() - last_whatsapp["at"] < 15 * 60  # right after a WhatsApp answer, "read them" needs no app name
    if not (mentioned or fresh):
        return _implicit_whatsapp_request(n)
    if mentioned and re.search(r"\b(?:send|write|text|message|reply|answer|respond|tell)\b.{0,30}\b(?:to|back)\b|\b(?:send|reply)\b", n) \
            and not re.search(r"\b(?:unread|read|check|did|have|any|from|new|missed)\b", n):
        return {"action": "send", "name": ""}
    if re.fullmatch(r"(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you) )*(?:read|play|tell)(?: me)?(?: them| it| those| these| the messages?| my messages?"
                    r"| the unread(?: messages?)?| my unread(?: messages?)?| what (?:they|it) says?)(?: (?:out loud|aloud|please))?", n) and fresh:
        return {"action": "read_unread", "name": ""}
    name = None
    for pattern in (r"\b(?:messages?|chats?|texts?|conversation) (?:from|of|with|by) (?P<n>.+?)(?: (?:on|in|from) whats ?app)?(?: please)?$",
                    r"\bwhat (?:did|does|has|is) (?P<n>.+?) (?:write|wrote|say|said|send|sent|text|texted|message|messaged)(?: to)?(?: me)?(?: (?:on|in) whats ?app)?(?: please)?$",
                    r"\b(?:did|has|is) (?P<n>.+?) (?:write|wrote|text|texted|message|messaged|written|send|sent)(?: to)?(?: me)?(?: (?:on|in) whats ?app)?$",
                    r"\bwhats ?app (?:chat |messages? |conversation )?(?:with|from) (?P<n>.+?)(?: please)?$"):
        m = re.search(pattern, n)
        if m:
            candidate = re.sub(r"^(?:my|the)\s+", "", m.group("n")).strip()
            if candidate and not re.fullmatch(r"(?:unread|new|any|all|unread messages?|new messages?|messages?|chats?|whats ?app)", candidate):
                name = candidate
                break
    if name and name not in {"me", "you", "anyone", "anybody", "someone", "somebody"}:
        return {"action": "read_chat", "name": name}
    if re.search(r"\b(?:unread|new|missed|messages?|chats?|texts?|anything|anyone|anybody|someone|wrote|written|texted|check|waiting|notifications?|read)\b", n) and mentioned:
        return {"action": "check", "name": ""}
    return None


_OTHER_INBOX = re.compile(r"\b(?:e ?mails?|mail|gmail|inbox|sms|imessage|telegram|discord|slack|signal|instagram|facebook|messenger|teams|outlook|voicemail)\b")


def _implicit_whatsapp_request(n: str):
    """"There are new messages that I didn't read", "any new messages?", "did Dana text me?": messages meant WhatsApp,
    the only messaging Jervis can read. Other inboxes are left alone, and reading a person's messages needs a
    message-like verb ("write", "text") and a chat that really has that name."""
    if _OTHER_INBOX.search(n) or not whatsapp.enabled() or not whatsapp.database_path():
        return None
    if re.search(r"\b(?:new|unread|missed|waiting)\s+(?:messages?|chats?|texts?)\b"
                 r"|\b(?:messages?|chats?|texts?)\s+(?:that\s+)?i\s+(?:did not|didn't|haven't|have not|hadn't)\s+read\b"
                 r"|\b(?:did|has|have)\s+(?:anyone|anybody|someone|somebody)\s+(?:write|wrote|text|texted|message|messaged|written)\b"
                 r"|\bwho\s+(?:wrote|texted|messaged|has written|has texted)\s+(?:to )?me\b", n):
        return {"action": "check", "name": ""}
    m = re.search(r"\bwhat\s+(?:did|does|has)\s+(?P<n>.+?)\s+(?:write|wrote|text|texted|message|messaged|send|sent)(?:\s+(?:to\s+)?me)?$"
                  r"|\b(?:did|has)\s+(?P<n2>.+?)\s+(?:write|wrote|text|texted|message|messaged|written)(?:\s+(?:to\s+)?me)?$", n)
    if m:
        name = re.sub(r"^(?:my|the)\s+", "", (m.group("n") or m.group("n2")).strip())
        if name not in {"me", "you", "anyone", "anybody", "someone", "somebody", "it", "he", "she", "they"}:
            try:
                found = whatsapp.find_chat(name)
            except Exception:
                found = None
            if found and whatsapp.find_chat_confidence(name) >= 0.85:
                return {"action": "read_chat", "name": name}
    return None


def handle_whatsapp_command(text: str):
    request = parse_whatsapp_request(text)
    if request is None:
        return None
    if request["action"] == "send":
        return "I can read your WhatsApp messages, but I can't send or reply for you."
    ok, reason = whatsapp.status()
    if not ok:
        return reason
    last_whatsapp["at"] = time.time()
    try:
        whatsapp.refresh()  # if WhatsApp is closed, wake it in the background so what I read is up to date
        if request["action"] == "read_unread":
            return PrivateReply(whatsapp.read_unread())
        if request["action"] == "read_chat":
            answer = whatsapp.read_from(request["name"])
            return answer if answer.startswith(("I couldn't find", "There are no messages")) else PrivateReply(answer)
        return whatsapp.unread_summary()  # counts and names only; the messages themselves stay unread until asked for
    except Exception as e:
        print(f"WhatsApp read failed: {type(e).__name__}")  # never print message content
        return "I couldn't read WhatsApp just now."


# ---------- Google Classroom: "check if I have homework I didn't submit" (opens it in the learning account) ----------
_WORK = r"(?:homework|home work|assignments?|schoolwork|school work|works?|tasks?|classwork|class work)"
_UNSUBMITTED = (r"(?:did not|didn't|didnt|haven't|havent|have not|hadn't|not|never)\s+(?:yet\s+)?(?:submit\w*|turn\w*|hand\w*|finish\w*|do|done|complete\w*)"
                r"|miss(?:ed|ing)?|overdue|over due|late|unsubmitted|undone|to submit|to turn in|to hand in|left to (?:do|submit|turn in)|due|pending|to do")


def parse_classroom_request(text: str) -> bool:
    """True for "check Classroom for work I didn't submit" and for asking about unsubmitted homework in plain words."""
    n = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    if re.search(r"\b(?:close|quit|exit)\b", n):
        return False
    mentions = bool(re.search(r"\bclass ?room\b", n))
    asks = bool(re.search(rf"\b{_WORK}\b", n)) and bool(re.search(rf"\b(?:{_UNSUBMITTED})\b", n))
    if mentions:
        return asks or bool(re.search(r"\b(?:check|see|look at|look in)\b.*\bclass ?room\b", n)) or bool(re.search(r"\b(?:check|see|look|tell|what|any|anything|do i have|is there|are there|show me)\b.*\b(?:missing|due|submit\w*|turned in|hand\w* in|assignments?|homework|works?|to do|todo)\b", n))
    if re.search(r"\b(?:how (?:do|to|can)|help me|write|explain|what is|what's an?)\b", n):
        return False
    return asks and bool(re.search(r"\b(?:i|my|me|do i|did i|have i|what|which|any)\b", n))


def handle_classroom_command(text: str):
    if not parse_classroom_request(text):
        return None
    if not google_accounts.accounts()["learning"]:
        return "I don't know which account is your school account yet. Add it to the .env file as GOOGLE_ACCOUNT_LEARNING."
    try:
        speak("Checking Google Classroom.")
        return classroom.summary(classroom.check_unsubmitted())
    except Exception:
        traceback.print_exc()
        return "I couldn't check Google Classroom just now."


# ---------- Graphs: "graph 2x squared plus 4x plus 6" draws the parabola in the window ----------
globes_drawn = 0   # how many globes the window has been sent this session (kept, to open again)
graphs_drawn = 0   # how many graphs the window has been sent this session (it keeps them all, to open again)
last_function = {"tree": None, "at": 0.0, "equation": None}  # the function/equation talked about last, so follow-ups make sense


def remember_function(tree, equation=None) -> None:
    last_function.update(tree=tree, at=time.time(), equation=equation)


_ASK_STEPS = re.compile(
    r"\b(?:steps?|solution|answer|working|method|process|way\s+to)\b.*\b(?:show|give|tell|explain|what|how)\b"
    r"|\b(?:show|give|tell|explain|walk|what|whats|what's)\b.*\b(?:steps?|solution|working|method|process|way)\b"
    r"|\bhow\s+(?:did|do|can|would|should)\s+(?:you|i|we)\s+(?:get|solve|find|work\s+out|calculate|got)\s+(?:that|it|this|x|the\s+(?:answer|solution))\b"
    r"|\bexplain\s+(?:that|it|this|the\s+(?:solution|answer|steps?|way))\b"
    r"|\bwhy\b.*\b(?:answer|solution)\b")
_FOLLOWUP_WORDS = set("""what whats what's is are the way to solution solutions answer answers steps step show me give tell explain how did do you i we get got solve
find work out calculate that it this its why please can could method process working of for roots root zeros zero vertex minimum maximum lowest
highest intercept intercepts y where does cross touch hit jervis hey and a an function parabola graph equation curve problem one more detail
details again solved by from came come up with was were so then x point points turning""".split())
_ASK_ROOTS = re.compile(r"\b(?:roots?|zeros?|solutions?|x\s*intercepts?|solve)\b|\bwhere\s+does\s+it\s+(?:cross|touch|hit)\b")
_ASK_VERTEX = re.compile(r"\b(?:vertex|minimum|maximum|lowest|highest|turning\s+point|extrema)\b")
_ASK_YINT = re.compile(r"\by\s*intercept\b")
_REFERS = re.compile(r"\b(?:it|its|that|this|them|the\s+(?:function|parabola|graph|equation|curve|solution|answer|problem)|that\s+one)\b")


def handle_math_followup(text: str):
    """A follow-up about the equation or function just discussed: "what is the way to the solution?", "show the steps", "what are its
    roots?", "what is the vertex?". Only when there is something recent to refer to and the message has no formula of its own."""
    if last_function["tree"] is None or time.time() - last_function["at"] > 45 * 60:
        return None
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    if not n or len(n.split()) > 14 or "x" in functions._tokenize(functions.normalize(text)) or re.search(r"\d", n):
        return None
    if not set(n.split()) <= _FOLLOWUP_WORDS:   # only short questions made of these words are about the math (not "steps to bake bread")
        return None
    tree, equation = last_function["tree"], last_function["equation"]
    asks_steps = bool(_ASK_STEPS.search(n))
    asks_roots = bool(_ASK_ROOTS.search(n))
    asks_vertex = bool(_ASK_VERTEX.search(n))
    asks_yint = bool(_ASK_YINT.search(n))
    if not (asks_steps or asks_roots or asks_vertex or asks_yint):
        return None
    if not (_REFERS.search(n) or asks_steps or re.search(r"\bwhat\s+(?:is|are)\s+the\b", n)):
        return None
    if asks_steps or asks_roots:
        worksheet = equations.solve(*(equation if equation else (tree, None)))
        if worksheet:
            return worksheet
    quadratic = functions.as_quadratic(tree)
    if quadratic is not None and quadratic[0] != 0:
        info = graphs.facts(*quadratic)
        if asks_vertex:
            vx, vy = info["vertex"]
            return f"The vertex of {info['plain']} is at x equals {graphs._say(vx)} and y equals {graphs._say(vy)}. It is the {'lowest' if info['opens'] == 'up' else 'highest'} point."
        if asks_yint:
            return f"The y-intercept of {info['plain']} is {graphs._say(info['yint'])}."
    analysis = functions.analyze(tree)
    described = functions.describe_function(tree, analysis, functions.build_view(tree, analysis))
    if asks_yint:
        return "The function doesn't cross the y-axis." if described["yint"] is None else f"The y-intercept is {graphs._say(described['yint'])}."
    if asks_vertex:
        if not described["extrema"]:
            return "This function has no highest or lowest point in the view."
        return "It has " + ", ".join(f"a {e['type']} at x equals {graphs._say(e['x'])} and y equals {graphs._say(e['y'])}" for e in described["extrema"][:4]) + "."
    roots = described["roots"]
    return ("It crosses the x-axis at " + ", ".join(f"x equals {graphs._say(r)}" for r in roots[:6]) + ".") if roots else "It never crosses the x-axis in this view."


def handle_earth_command(text: str):
    """Distance between two places, shown on a 3D globe: geocodes both (a network lookup, like the weather or Classroom
    checks) and works out the great-circle route between them."""
    global globes_drawn
    request = earth.parse_request(text)
    if request is None:
        return None
    if request["action"] == "close":
        send_ui_update_once({"type": "close_globe"})
        return "Okay, I closed the globe." if ws_loop and connected_clients else None
    if request["action"] == "reshow":
        if not globes_drawn:
            return "I haven't shown a globe yet. Ask me the distance between two places."
        send_ui_update_once({"type": "show_globe", "which": request["which"]})
        return {"prev": "Here is the previous one.", "next": "Here is the next one.", "first": "Here is the first one."}.get(request["which"], "Here it is again.")
    if request["action"] == "ask":
        return "Which two places? For example: what's the distance between Tokyo and Paris."
    a = earth.geocode(request["a"])
    b = earth.geocode(request["b"]) if a else None
    if not a or not b:
        return f"I couldn't find {request['a'] if not a else request['b']}."
    info = earth.build(a, b)
    globes_drawn += 1
    send_ui_update_once({"type": "globe", "data": info})
    return earth.describe(info)


planets_shown = 0   # how many planet models the window has been sent this session (kept, to open again)


def handle_planet_command(text: str):
    global planets_shown
    request = planets.parse_request(text)
    if request is None:
        return None
    if request["action"] == "close":
        send_ui_update_once({"type": "close_planet"})
        return "Okay, I closed it." if ws_loop and connected_clients else None
    if request["action"] == "reshow":
        if not planets_shown:
            return "I haven't shown a planet yet. Ask me to tell you about one."
        send_ui_update_once({"type": "show_planet", "which": request["which"]})
        return {"prev": "Here is the previous one.", "next": "Here is the next one.", "first": "Here is the first one."}.get(request["which"], "Here it is again.")
    if request["action"] == "ask":
        return "Which one? Try Mars, Jupiter, Saturn, or any other planet, the Sun, or the Moon."
    info = planets.build(request["body"])
    planets_shown += 1
    send_ui_update_once({"type": "planet", "data": info})
    return info["text"]


# ---------- Google Calendar: "open calendar" asks to hear what's next or make a new event ----------
_CALENDAR_READ = re.compile(
    r"\b(?:hear|read|tell me|check|see|show me|what are)\b.*\b(?:events?|calendar|agenda|schedule)\b|"
    r"\bnext events?\b|\bwhat'?s (?:on my calendar|coming up|next)\b|\b(?:the\s+)?(?:next\s+)?events?\b|"
    r"\bhear (?:them|it)\b|\bread (?:them|it)\b")
_CALENDAR_CREATE = re.compile(
    r"\b(?:make|create|add|schedule|set up|new)\b.*\b(?:event|meeting|appointment)\b|\bnew event\b|\banother\s+(?:one|event)\b")
_CALENDAR_READ_DIRECT = re.compile(
    r"\b(?:check|read|hear|see|show me|what'?s on|what is on)\b.*\b(?:calendar|schedule|agenda)\b|"
    r"\bmy (?:next|upcoming) events?\b|\bwhat'?s (?:coming up|next) on my calendar\b")
_CALENDAR_CREATE_DIRECT = re.compile(r"\b(?:make|create|add|schedule|set up)\b.*\b(?:calendar\s+)?(?:event|meeting|appointment)\b")
_CALENDAR_CANCEL = re.compile(r"(?:never ?mind|cancel|forget it|no thanks|nothing|stop)")
_DURATION_HINT = "How long should it be? Say a length, like '30 minutes' or '2 hours', or say default for one hour."


def handle_calendar_read():
    """Speak, then fetch and describe the next 5 events. A real Calendar API call: the first ever use opens a browser
    tab to sign in (see calendar_api.py); after that a cached, refreshed token is used silently."""
    speak("One moment, checking your calendar.")
    try:
        events = calendar_api.list_upcoming(5)
    except calendar_api.CalendarUnavailable as e:
        return str(e)
    if not events:
        return "You have no upcoming events on your calendar."
    lines = [f"Here {'is' if len(events) == 1 else 'are'} your next {len(events)} event{'' if len(events) == 1 else 's'}."]
    for i, item in enumerate(events, 1):
        when = calendar_time.format_when(item["start"], item["end"], item["all_day"])
        where = f" ({item['location']})" if item["location"] else ""
        lines.append(f"{i}. **{item['title']}** — {when}{where}")
    return "\n".join(lines)


def handle_calendar_choice(text: str):
    """After "open calendar" asked which one, this is the reply: "hear the next events" or "make a new one"."""
    global pending_calendar_choice, pending_calendar_event
    cleaned = " ".join(re.sub(r"[^a-z' ]", " ", text.lower()).split())
    if _CALENDAR_CANCEL.fullmatch(cleaned):
        return "Okay."
    if _CALENDAR_CREATE.search(cleaned):
        pending_calendar_event = {"step": "title", "fields": {}, "at": time.time()}
        return "Sure, what should I call the event?"
    if _CALENDAR_READ.search(cleaned):
        return handle_calendar_read()
    pending_calendar_choice = {"at": time.time()}
    return "Sorry, I didn't catch that. Do you want to hear the next events, or make a new one?"


def handle_calendar_event_step(text: str):
    """One answer in the "make a new event" conversation: title, then date, then time, then how long."""
    global pending_calendar_event
    pending = pending_calendar_event
    cleaned = " ".join(re.sub(r"[^a-z' ]", " ", text.lower()).split())
    if _CALENDAR_CANCEL.fullmatch(cleaned):
        pending_calendar_event = None
        return "Okay, cancelled."
    step = pending["step"]
    if step == "title":
        title = text.strip().strip(".!? ")
        if not title:
            return "Sorry, what should I call the event?"
        pending["fields"]["title"] = title
        pending["step"] = "date"
        return f"Got it: “{title}.” What date?"
    if step == "date":
        date = calendar_time.parse_date(text)
        if not date:
            return "I didn't catch a date. Try something like tomorrow, next Friday, or October 3rd."
        pending["fields"]["date"] = date
        pending["step"] = "time"
        return "And what time?"
    if step == "time":
        parsed = calendar_time.parse_time(text)
        if not parsed:
            return "I didn't catch a time. Try something like 3pm or 15:30."
        pending["fields"]["time"] = parsed
        pending["step"] = "duration"
        return _DURATION_HINT
    if step == "duration":
        duration = calendar_time.parse_duration(text)
        if duration is None:
            return "I didn't catch a length. Try 30 minutes, 2 hours, all day, or say default for one hour."
        pending_calendar_event = None
        fields = pending["fields"]
        hour, minute = fields["time"]
        start = calendar_time.combine(fields["date"], hour, minute)
        end = start + (timedelta(days=1) if duration == "all_day" else timedelta(minutes=duration))
        try:
            created = calendar_api.create_event(fields["title"], start, end)
        except calendar_api.CalendarUnavailable as e:
            return str(e)
        when = calendar_time.format_when(created["start"], created["end"], duration == "all_day")
        return f"Done. I've added “{fields['title']}” to your calendar for {when}."
    return None


def handle_calendar_command(text: str):
    """"Check my calendar", "create a calendar event": the same flows as after "open calendar", without opening it first."""
    global pending_calendar_event
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    if _CALENDAR_CREATE_DIRECT.search(n):
        pending_calendar_event = {"step": "title", "fields": {}, "at": time.time()}
        return "Sure, what should I call the event?"
    if _CALENDAR_READ_DIRECT.search(n):
        return handle_calendar_read()
    return None


_OPEN_IMAGE_RE = re.compile(r"\b(?:open|show(?:\s+me)?)\s+(?:this|that|the)\s+(?:generated\s+|edited\s+)?(?:image|picture|photo)\b")
_SAVE_IMAGE_RE = re.compile(r"\bsave\s+(?:this|that|the)\s+(?:generated\s+|edited\s+)?(?:image|picture|photo)\b")


def handle_image_command(text: str):
    """The two deterministic, non-AI image actions: opening or saving the most recent picture in this conversation.
    Understanding, generating and editing images go through the AI's tools instead (see TOOLS / TOOL_FUNCTIONS)."""
    if not images.has_pending_context():
        return None
    n = " ".join((text or "").lower().split())
    if _OPEN_IMAGE_RE.search(n):
        try:
            osal.open_path(images.last_image(1)[0]["path"])
            return "Opening it now."
        except Exception as e:
            return f"I couldn't open that image: {e}"
    if _SAVE_IMAGE_RE.search(n):
        try:
            return f"Saved to {images.save_copy()}."
        except images.ImageError as e:
            return str(e)
    return None


def handle_graph_command(text: str):
    global graphs_drawn
    request = graphs.parse_request(text)
    if request is None:
        return None
    if request["action"] == "last":
        if last_function["tree"] is not None and time.time() - last_function["at"] < 60 * 60:
            request = graphs.request_from_tree(last_function["tree"])
        elif request.get("explicit"):
            return "Tell me the equation, for example: graph y equals x squared minus 4x plus 3. Or give me a, b and c."
        else:
            return None
    if request.get("ast") is not None:
        remember_function(request["ast"])
    if request["action"] == "close":
        send_ui_update_once({"type": "close_graph"})
        return "Okay, I closed the graph." if ws_loop and connected_clients else None
    if request["action"] == "reshow":
        if not graphs_drawn:
            return "I haven't drawn a graph yet. Give me a function and I'll draw it."
        send_ui_update_once({"type": "show_graph", "which": request["which"]})
        return {"prev": "Here is the previous graph.", "next": "Here is the next graph.", "first": "Here is the first graph."}.get(request["which"], "Here is the graph again.")
    if request["action"] == "ask":
        return "Tell me the equation, for example: graph y equals x squared minus 4x plus 3. Or give me a, b and c."
    if request["action"] == "unsupported":
        return "I can graph any function of x, like y equals something with x. Give me one of those."
    if request["action"] == "unclear":
        return "I couldn't read that as a function of x. Try something like: graph sine of x, or graph x cubed minus 3x."
    if request["action"] == "function":
        info = graphs.build_function(request["ast"])
        send_ui_update_once({"type": "graph", "data": info})
        graphs_drawn += 1
        return graphs.describe_function(info)
    info = graphs.facts(request["a"], request["b"], request["c"])
    send_ui_update_once({"type": "graph", "data": info})
    graphs_drawn += 1
    return graphs.describe(info)


_SERVICE_WORDS = {"netflix": "netflix", "stremio": "stremio", "youtube": "youtube", "spotify": "spotify"}
_COMPOUND = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
    r"(?:open|launch|start)\s+(?:up\s+)?(?:the\s+)?(.+?)(?:\s+(?:app|application))?\s+(?:and\s+then|and|then)\s+"
    r"((?:play|watch|put on|write|type|draft|compose|search|find|set|remind|pause|stop|resume|go|skip|jump|turn|make|create|show|listen)\b.*)$")


def split_open_and_do(text: str):
    """"Open Spotify and play the Smiths song" -> ("spotify", "play the smiths song"), else None."""
    n = " ".join(re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()).split())
    m = _COMPOUND.match(n)
    if not m:
        return None
    target, action = m.group(1), m.group(2)
    known = (target in _SERVICE_WORDS or resolve_app(target)[0] != "missing" or _site_for(target))
    return (target, action) if known else None


def handle_compound_command(text: str):
    parts = split_open_and_do(text)
    if not parts:
        return None
    target, action = parts
    service = _SERVICE_WORDS.get(target)
    mentions_service = re.search(r"\b(netflix|stremio|youtube|spotify)\b", action)
    if service and not mentions_service:
        if service == "spotify" and not re.match(r"(?:play|put on|listen|start)\b", action):
            service = None  # e.g. "open Spotify and pause": open it first, then run the command
        else:
            action = f"{action} on {service}"  # playing there opens the app or site by itself
            result = handle_direct_command(action)
            return result or f"I couldn't work out '{action}'."
    opened = open_application(target)
    remember_media_app(target)
    result = handle_direct_command(action)
    return f"{opened} {result}" if result else f"{opened} I didn't catch what to do next."


# ---------- several things in one message: "solve x^2 + 3x - 4 = 0 and draw the function" ----------
chat_history = None   # the conversation the main loop keeps, so a part that isn't a direct command can still ask the AI
_multi_active = False
_TASK_START = (r"(?:draw|drew|graph|plot|sketch|paint|solve|find|calculate|compute|factor|expand|simplify|open|close|play|pause|stop|resume|skip|set|start|"
               r"cancel|remind|write|read|check|tell|show|what|what's|whats|how|who|where|when|why|search|google|turn|mute|unmute|send|make|create|give|"
               r"explain|list|translate|convert|remember|call|text|schedule|add|remove|delete|type|launch|switch|go|save|put|bring|take)")
_TASK_SPLIT = re.compile(
    rf"(?:\s*[.;!?]+\s+(?:(?:and|then|also)\s+(?:then\s+|also\s+)?)?|\s*,\s*(?:and\s+)?(?:then\s+|also\s+)?|\s+(?:and\s+then|and\s+also|and|then|also|after\s+that|afterwards|plus)\s+)(?=(?i:{_TASK_START})\b)",
    re.I)


def split_tasks(text: str) -> list:
    """The separate things asked for in one message (each starts with an action or a question), or the whole text as one."""
    parts = [p.strip(" ,.;") for p in _TASK_SPLIT.split((text or "").strip())]
    return [p for p in parts if p] or [text]


def handle_multi_task(text: str):
    """Do each task in order and answer them together. Returns None unless the message really holds several tasks and at least
    one of them is a command Jervis can do himself (otherwise the AI answers the whole message at once)."""
    global _multi_active
    if _multi_active or pending_confirmation or pending_dictation:
        return None
    parts = split_tasks(text)
    if len(parts) < 2 or split_open_and_do(text):
        return None
    _multi_active = True
    try:
        results, handled = [], 0
        for part in parts:
            reply = handle_direct_command(part)
            if reply:
                handled += 1
            results.append(reply)
        if not handled:
            return None
        for i, part in enumerate(parts):          # the parts Jervis can't do himself go to the AI, one by one
            if results[i]:
                continue
            asked = (chat_history or []) + [{"role": "user", "content": part}]
            try:
                results[i] = tidy_math(ask_jervis(asked, part))
            except Exception:
                traceback.print_exc()
                results[i] = f"I couldn't do this part: {part}"
        unique = []
        for r in results:                          # "solve it and show the steps" would say the same thing twice
            if str(r) not in [str(u) for u in unique]:
                unique.append(r)
        results = unique
        combined = SpokenReply("\n\n---\n\n".join(str(r) for r in results))
        combined.spoken = " ".join(spoken_version(r) for r in results).replace(" I've put the details on your screen.", "", len(results) - 1)
        return combined
    finally:
        _multi_active = False


def handle_direct_command(text: str):
    """Run reliable, explicitly spoken desktop commands without model tool-call guesses."""
    global youtube_active, netflix_active, stremio_active
    multi = handle_multi_task(text)
    if multi:
        return multi
    normalized = " ".join((text or "").lower().strip().split())
    closed_reply = None
    if not re.search(r"\b(quit|close|exit)\s+(my\s+)?spotify\b", normalized):
        closed_reply = handle_close_command(text)
    if closed_reply:
        return closed_reply
    if re.search(r"\b(quit|close|exit)\s+(my\s+)?spotify\b", normalized):
        return quit_application("Spotify")
    if alerts_open and re.fullmatch(
            r"(?:jervis )?(?:ok|okay|stop|dismiss|thanks|thank you|got it|i got it|silence|quiet|enough|alright)"
            r"(?: (?:it|that|the alarm|the timer|the alert|the sound))?", " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())):
        send_ui_update_once({"type": "dismiss_alert"})
        return "Okay."
    classroom_reply = handle_classroom_command(text)
    if classroom_reply:
        return classroom_reply
    followup = handle_math_followup(text)
    if followup:
        return followup
    earth_reply = handle_earth_command(text)
    if earth_reply:
        return earth_reply
    planet_reply = handle_planet_command(text)
    if planet_reply:
        return planet_reply
    graph_reply = handle_graph_command(text)
    if graph_reply:
        return graph_reply
    image_reply = handle_image_command(text)
    if image_reply:
        return image_reply
    equation = equations.parse_request(text)
    if equation:
        solved = equations.solve(*equation)
        if solved:
            left, right = equation
            remember_function(left if right is None else ["sub", left, right], equation)   # so "draw the function", "show the steps"... refer to it
            return solved
    compound = handle_compound_command(text)
    if compound:
        return compound
    global pending_dictation
    if pending_dictation:
        pending, pending_dictation = pending_dictation, None
        if time.time() - pending["at"] < 90:
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop)", " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())):
                return "Okay, cancelled."
            return write_document(
                "Put exactly what the user dictated into the document, formatted neatly (a clean bulleted list if it is a "
                f"list of items). Do not add anything they did not say. Dictation: {text}", pending["app"])
    global pending_spotify_request
    if pending_spotify_request:
        pending, pending_spotify_request = pending_spotify_request, None
        if time.time() - pending["at"] < 45:
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            return play_song(text)
    global pending_google_search
    if pending_google_search:
        pending, pending_google_search = pending_google_search, None
        if time.time() - pending["at"] < 45:
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            return google_search(text)
    global pending_netflix_request
    if pending_netflix_request:
        pending, pending_netflix_request = pending_netflix_request, None
        if time.time() - pending["at"] < 45:
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            return play_netflix_show(text)
    global pending_stremio_request
    if pending_stremio_request:
        pending, pending_stremio_request = pending_stremio_request, None
        if time.time() - pending["at"] < 45:
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            return play_stremio_title(text)
    global pending_calendar_choice
    if pending_calendar_choice:
        pending, pending_calendar_choice = pending_calendar_choice, None
        if time.time() - pending["at"] < 45:
            return handle_calendar_choice(text)
    global pending_calendar_event
    if pending_calendar_event:
        if time.time() - pending_calendar_event["at"] < 5 * 60:   # a whole conversation, so a longer window than the rest
            pending_calendar_event["at"] = time.time()
            return handle_calendar_event_step(text)
        pending_calendar_event = None
    calendar_reply = handle_calendar_command(text)   # "check my calendar" / "create a calendar event" out of the blue
    if calendar_reply:
        return calendar_reply
    if re.fullmatch(r"(?:jervis )?(?:open|show|bring up) (?:the |your |my )?(?:jervis )?(?:window|interface|screen|ui)",
                    " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())):
        launch_ui()
        return "Opening my window." if ui_failures < 2 else "My window can't start on this computer. The console explains why."
    global pending_confirmation
    if pending_confirmation:
        pending, pending_confirmation = pending_confirmation, None
        answer = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
        if time.time() - pending["at"] < 30:
            if re.fullmatch(r"(?:yes|yeah|yep|sure|ok|okay|do it|confirm|go ahead|yes please|close them|close it|yes close them|yes do it)", answer):
                return pending["do"]()
            if re.fullmatch(r"(?:no|nope|cancel|never mind|nevermind|don't|dont|stop|no thanks)", answer):
                return "Okay, I left them open."
    whatsapp_reply = handle_whatsapp_command(text)
    if whatsapp_reply:
        return whatsapp_reply
    timer_reply = handle_timer_command(text)
    if timer_reply:
        return timer_reply
    fix = re.fullmatch(
        r"(?:(?:no |hey |ok )?(?:this is |that is |it is |it's |that's )?(?:the )?wrong (?:account|profile)"
        r"|(?:open|move|put|switch|do|send|show) (?:it|that|this|the \w+)(?: again)? (?:in|on|with|to|under) (?:my |the )?"
        r"(school|learning|personal|gmail|other|different|right|correct)(?: account| profile)?)",
        " ".join(re.sub(r"[^a-z' ]", " ", text.lower()).split()))
    if fix:
        wanted = {"school": "learning", "learning": "learning", "personal": "personal", "gmail": "personal"}.get(fix.group(1) or "", "")
        return google_accounts.reopen_elsewhere(wanted)
    trailer = parse_trailer_request(text)
    if trailer is not None:
        return play_trailer(trailer, new_tab=wants_new_tab(text))
    if documents.is_transfer_request(text):
        return transfer_to_document(text)
    if documents.is_blank_request(text):
        return open_blank_document(documents.detect_app(text), text)
    doc_app = documents.detect_request(text)
    if doc_app:
        return write_document(text, doc_app)
    volume = parse_volume_command(text)
    if volume:
        return change_volume(*volume)
    seek_to = parse_seek_command(text)
    if seek_to is not None:
        if stremio_active and not (youtube_active or netflix_active):
            return "Stremio doesn't let me jump to a time. Drag its progress bar instead."
        if youtube_active or netflix_active or not sp or youtube_is_playing():
            return control_playback("seek", seek_to)
        return seek_music(seek_to)
    if current_document() and current_document().get("body") and parse_read_document(text):
        doc = current_document()
        return ReadAloud(f"{doc['title']}\n\n{doc['body']}".strip())
    if current_document() and documents.is_edit_request(text):
        return edit_document(text)
    direction = parse_track_skip(text)
    if direction:
        if (netflix_active or stremio_active) and not youtube_active and not re.search(r"\b(song|track|music|spotify)\b", text.lower()):
            return "I can skip songs on Spotify and videos on YouTube. For shows, tell me the season and episode you want."
        if youtube_active and not re.search(r"\b(spotify)\b", text.lower()):
            return control_playback(direction)
        return skip_track(direction)
    spotify_request = parse_spotify_request(text)
    if spotify_request:
        return play_song(spotify_request[0], start_seconds=spotify_request[1])
    if is_restart_command(text):
        if stremio_active and not (youtube_active or netflix_active):
            return ("Stremio doesn't let me restart from the beginning. Drag the progress bar back to the start, "
                    "or say pause and I'll toggle playback.")
        if sp and not (youtube_active or netflix_active) and not youtube_is_playing():
            seek_music(0)  # nothing video-like is active: the song on Spotify
            return "Starting the song over."
        return control_playback("restart")
    spotify_action = spotify_playback_action(text) if not youtube_playback_action(text) else None
    if spotify_action:
        return pause_music() if spotify_action == "pause" else resume_music()
    action = youtube_playback_action(text)
    if action:
        if stremio_active and not (youtube_active or netflix_active) and not re.search(r"\b(youtube|netflix|video)\b", normalized):
            return stremio.toggle_playback()
        return control_playback(action)
    request = parse_service_request(text, "netflix")
    if request:
        return play_netflix_show(request[0], new_tab=wants_new_tab(text), season=request[2], episode=request[3])
    request = parse_service_request(text, "stremio", allow_open=True)
    if request:
        show, kind, season, episode = request
        return play_stremio_title(show, kind, season, episode)
    request = parse_implicit_media_request(text) or parse_episode_request(text)
    if request:
        show, kind, season, episode = request
        named = re.search(r"\b(netflix|stremio)\b", text.lower())
        if (named.group(1) if named else last_media_app or DEFAULT_MEDIA_APP) == "netflix":
            return play_netflix_show(show, season=season, episode=episode)
        return play_stremio_title(show, kind, season, episode)
    if is_youtube_command(text) or is_youtube_followup(text):
        query = extract_youtube_query(text)
        if query:
            return play_youtube_video(query, new_tab=wants_new_tab(text))
        if is_youtube_followup(text) and re.search(r"\bplay\b", normalized):
            return control_playback("resume")

    if re.search(r"\bopen\s+(the\s+)?youtube\b", normalized):
        open_youtube("https://www.youtube.com", wants_new_tab(text), context=text)
        return "Opened YouTube."

    # "Open <any installed app>" — resolved against what's actually installed.
    app_name = parse_open_request(text)
    if app_name:
        remember_media_app(app_name)
        opened = open_application(app_name)
        if app_name.strip().lower() == "spotify" and opened.startswith("Opened"):
            pending_spotify_request = {"at": time.time()}
            return f"{opened} What would you like to listen to?"
        if app_name.strip().lower() == "google" and opened.startswith("Opened"):
            pending_google_search = {"at": time.time()}
            return f"{opened} What do you want to search today?"
        if app_name.strip().lower() == "netflix" and opened.startswith("Opened"):
            pending_netflix_request = {"at": time.time()}
            return f"{opened} What do you want to watch today?"
        if app_name.strip().lower() == "stremio" and opened.startswith("Opened"):
            pending_stremio_request = {"at": time.time()}
            return f"{opened} What do you want to watch today?"
        if app_name.strip().lower() in ("calendar", "google calendar") and opened.startswith("Opened"):
            pending_calendar_choice = {"at": time.time()}
            return f"{opened} Do you want to hear the next events, or make a new one?"
        return opened
    return None


def google_search(query: str, **kwargs) -> str:
    """Open a Google search only after an explicit Google voice command."""
    query = (query or "").strip()
    if not query:
        return "I need a search phrase for Google."
    webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
    return f"Searching Google for {query}."


def is_google_search_command(text: str) -> bool:
    """Require the spoken word 'Google' before a browser search can run."""
    words = " ".join((text or "").lower().strip().split())
    return "google" in words


def play_song(song_name: str, start_seconds=None, **kwargs) -> str:
    """Play a track on Spotify, optionally starting `start_seconds` into it."""
    if not sp:
        return "Spotify integration is not configured."
    spoken_seconds, cleaned = parse_start_time(song_name)  # the model may leave "minute two" in the title
    song_name = cleaned or song_name
    start_seconds = start_seconds or spoken_seconds
    try:
        results = sp.search(q=song_name, type="track", limit=1)
    except Exception as e:
        return f"Spotify search failed: {e}"
    tracks = results.get("tracks", {}).get("items", [])
    if not tracks:
        return f"I couldn't find a song called {song_name}."
    track = tracks[0]
    global youtube_active, netflix_active, stremio_active, spotify_active
    youtube_active = netflix_active = stremio_active = False
    spotify_active = True
    device_id = ensure_spotify_device()
    if not device_id:
        return "Spotify needs to be open on a device first."
    position_ms = None
    if start_seconds:
        position_ms = min(int(start_seconds) * 1000, max(0, track.get("duration_ms", 0) - 1000))
    try:
        sp.start_playback(
            device_id=device_id,
            context_uri=track["album"]["uri"],
            offset={"uri": track["uri"]},
            position_ms=position_ms,
        )
        where = f" from {format_time(position_ms // 1000)}" if position_ms else ""
        return f"Playing {track['name']} by {track['artists'][0]['name']}{where}."
    except Exception as e:
        return f"Spotify player error: {e}"


def seek_music(seconds: int) -> str:
    if not sp:
        return "Spotify integration is not configured."
    try:
        device_id = get_device_id()
        if not device_id:
            return "No active Spotify device found."
        sp.seek_track(int(seconds) * 1000, device_id=device_id)
        return f"Jumping to {format_time(seconds)}."
    except Exception as e:
        return f"Could not jump: {e}"


def skip_track(direction: str) -> str:
    """Spotify: jump to the next or previous song and say what is playing now."""
    if not sp:
        return "Spotify integration is not configured."
    try:
        device_id = get_device_id()
        if not device_id:
            return "No active Spotify device found. Play something on Spotify first."
        if direction == "next":
            sp.next_track(device_id=device_id)
        else:
            # Spotify's "previous" only restarts the song when it is more than a few seconds in.
            state = sp.current_playback() or {}
            sp.previous_track(device_id=device_id)
            if (state.get("progress_ms") or 0) > 3000:
                time.sleep(0.4)
                sp.previous_track(device_id=device_id)
        time.sleep(0.8)  # let Spotify switch before asking what is playing
        item = (sp.current_playback() or {}).get("item") or {}
        if item.get("name"):
            artist = (item.get("artists") or [{}])[0].get("name", "")
            return f"Now playing {item['name']}" + (f" by {artist}." if artist else ".")
        return "Skipped to the next song." if direction == "next" else "Went back to the previous song."
    except Exception as e:
        return f"I couldn't change the song: {e}"


spotify_active = False  # True once Jervis started a song on Spotify; "stop" / "pause" / "resume" then go there directly


def resume_music() -> str:
    if not sp:
        return "Spotify integration is not configured."
    try:
        device_id = get_device_id()
        if not device_id:
            return "No active Spotify device found."
        sp.start_playback(device_id=device_id)
        return "Resuming the music."
    except Exception as e:
        return f"Could not resume: {e}"


def spotify_is_playing() -> bool:
    try:
        return bool(sp and (sp.current_playback() or {}).get("is_playing"))
    except Exception:
        return False


_NOT_SPOTIFY_STOP = re.compile(r"\b(timer|timers|alarm|reminder|listening|talking|speaking|window|tab|tabs|video|show|episode|movie|"
                               r"netflix|stremio|youtube|volume|recording|document|story|writing)\b")


def spotify_playback_action(text: str):
    """"Stop it, please", "pause", "stop the sound", "resume" -> "pause" / "resume" when Spotify is what is playing."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    if not sp or _NOT_SPOTIFY_STOP.search(n) or len(n.split()) > 7:
        return None
    if re.search(r"\b(pause|stop|halt|silence|hold on|be quiet|shut up)\b", n):
        action = "pause"
    elif re.search(r"\b(resume|unpause|continue|keep playing)\b", n):
        action = "resume"
    else:
        return None
    if youtube_active or netflix_active or stremio_active:
        return None
    return action if (spotify_active or spotify_is_playing()) else None


def pause_music(**kwargs) -> str:
    if not sp:
        return "Spotify integration is not configured."
    try:
        device_id = get_device_id()
        if device_id:
            sp.pause_playback(device_id=device_id)
            return "Paused playback."
        return "No active Spotify device found."
    except Exception as e:
        return f"Could not pause: {e}"


def tool_analyze_image(question: str = "") -> str:
    try:
        return images.analyze(question)
    except images.ImageError as e:
        return f"Image analysis failed: {e}"


def tool_extract_image_text(**kwargs) -> str:
    try:
        return images.extract_text()
    except images.ImageError as e:
        return f"Could not read text from the image: {e}"


def tool_compare_images(question: str = "") -> str:
    try:
        return images.compare(question)
    except images.ImageError as e:
        return f"Could not compare the images: {e}"


def tool_generate_image(prompt: str = "") -> str:
    send_status("generating")
    try:
        result = images.generate(prompt)
    except images.ImageError as e:
        return f"Image generation failed: {e}"
    broadcast("ai", "", image=images.display_data_url(result["path"]), image_kind="generated")
    note = f" Note: {result['note']}" if result.get("note") else ""
    return (f"Successfully generated the image for: {prompt}. It has already been shown to the user in the "
            f"conversation and saved to {result['path']} — do not say you are about to generate it, it is already done.{note}")


def tool_edit_image(instruction: str = "") -> str:
    send_status("generating")
    try:
        result = images.edit(instruction)
    except images.ImageError as e:
        return f"Image edit failed: {e}"
    broadcast("ai", "", image=images.display_data_url(result["path"]), image_kind="edited")
    return (f"Successfully edited the image as requested ({instruction}). The result has already been shown to the "
            f"user in the conversation and saved to {result['path']}; the original image was left unchanged.")


TOOL_FUNCTIONS = {
    "open_application": open_application,
    "google_search": google_search,
    "play_youtube_video": play_youtube_video,
    "play_song": play_song,
    "pause_music": pause_music,
    "analyze_image": tool_analyze_image,
    "extract_image_text": tool_extract_image_text,
    "compare_images": tool_compare_images,
    "generate_image": tool_generate_image,
    "edit_image": tool_edit_image,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open any installed desktop application (e.g. Chrome, Notes, Calculator, Discord). ONLY call if user explicitly asks to open an app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name."}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_search",
            "description": "Search Google. ONLY call when the user explicitly says the word 'Google' and asks to search there.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The exact Google search phrase."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_youtube_video",
            "description": "Find and open the first YouTube video matching the user's explicit request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Video title, topic, or search phrase."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_song",
            "description": "Play a track on Spotify.",
            "parameters": {
                "type": "object",
                "properties": {
                    "song_name": {"type": "string", "description": "Song title or artist."}
                },
                "required": ["song_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_music",
            "description": "Pause Spotify music playback.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": (
                "Look at the most recently attached, generated or edited image and answer a question about it, or "
                "describe it if no question is given. ONLY call when the user is clearly asking about an image that "
                "is part of this conversation (an attached photo, screenshot, diagram, chart, or a picture Jervis "
                "just made or edited) — including a vague follow-up like 'what's wrong with it' right after an "
                "image was shared. You cannot see images yourself; this is the only way to know what is in one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "What to find out about the image. Leave empty for a general description."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_image_text",
            "description": "Read and transcribe all text visible in the most recently attached image (OCR). ONLY call when the user explicitly asks to read, extract, or find out what text/words/message is in an image or screenshot.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_images",
            "description": "Compare the most recent images shared in this conversation (at least two must already exist) and describe similarities/differences, or answer a specific comparison question. ONLY call when the user explicitly asks to compare images, or what changed/differs between them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The specific comparison to make. Leave empty for a general comparison."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Create a brand new image from a text description (text-to-image). ONLY call when the user explicitly asks to generate, create, draw, paint or make an image/picture/photo of something.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "A clear, detailed description of the image to create."}
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_image",
            "description": "Edit the most recently attached, generated or edited image according to an instruction (remove or add something, replace something, change the background, change the style, recolor, etc). ONLY call when the user explicitly asks to edit, change, remove something from, or transform an existing image that is part of this conversation. The original file is never overwritten.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "What to change, in clear natural language."}
                },
                "required": ["instruction"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Jervis, an AI desktop assistant.
- NEVER execute tools unless the user explicitly commands an action (e.g., 'open application', 'play music').
- If the user asks general questions or makes conversational statements like 'can you hear me' or 'hello', DO NOT call tools. Respond naturally in 1-2 sentences.
- NEVER search the web or open a browser unless the user explicitly says the word 'Google'. For example: 'Google the weather in Tel Aviv.'
- Never say you opened, wrote, played or changed something unless a tool result confirmed it. If you cannot do something, say so plainly.
- You cannot see the user's messages, emails or files. Never claim that they have, or don't have, any unread messages or new mail: say you can't check that. You cannot see their Google Calendar either (a separate feature checks it before you're ever asked) — if a calendar question reaches you, tell the user to say "check my calendar" or "open my calendar" instead of guessing what is on it.
- Images: the user can attach photos, screenshots or other pictures, and you can create or edit images too. You cannot see an image yourself — only the image tools can. Use analyze_image to describe an attached image or answer a question about it, including a vague follow-up like "what's wrong with it" right after an image was shared (a system message will tell you when one is pending). Use extract_image_text to read text out of an image. Use compare_images once two or more images have been shared. Use generate_image only when explicitly asked to create/draw/make a picture of something, and edit_image only when explicitly asked to change an existing image (remove/add/replace something, change the background or style, etc). Never claim an image was generated, edited or analyzed unless a tool result actually confirmed it. If an image tool result explains what's missing or how to fix it (a setup step, an environment variable, a URL), repeat that specific detail back to the user instead of a vague "I can't do that" — they need to know exactly what to do next.
- After using a tool, give the user a short natural spoken confirmation.
- Keep casual answers concise and natural, never emoji.
- When you recommend a movie or series, always write its exact title in **bold**.
- When the user asks to be taught something, or asks for an explanation, steps, a list or a comparison, answer in clean, well-organized Markdown that is shown on screen: start with ONE short spoken-style sentence, then a few short bullet points or a numbered list, with **bold** for the key terms. Use a table only to compare several things across the same columns, with the header row and the |---| separator row each on their own line. Keep it under about 150 words unless the user asks for more, and end with one short follow-up question.
- Math (any calculation, equation or word problem) is ALWAYS answered in this exact layout, every part on its own line, and no follow-up question. Write ALL formulas in LaTeX between dollar signs, and put each display formula alone on its own line between $$ and $$:
  Line 1: ONE short plain sentence with the result, no symbols and no LaTeX (say it in words; for a long or complex result say it is shown below), for example: The answer is x equals 10.
  Then a blank line, then "### Problem" and the given problem as a display formula.
  Then one "### Step N · short title" heading per step (N = 1, 2, 3...), each followed by exactly ONE display formula that is short enough to fit one line: never chain many equalities on one line, split them into more steps instead.
  Then a blank line and the final result on a line starting with "> " as a formula, for example: > $x = 10$
  Only ever use dollar signs for formulas: never \\( \\) or \\[ \\]. Never write a solution as one paragraph, never use arrows, and never write formulas as plain text like x^2 or 4*2*6: use LaTeX (x^2, 4\\cdot 2, \\frac{a}{b}, \\sqrt{2}, \\pm).
  A plain one-operation sum (like 12 times 7) skips the problem and steps: the sentence and the "> " line are enough.
  Example reply to "what is 2x + 4 = 24":
  The answer is x equals 10.

  ### Problem
  $$2x + 4 = 24$$

  ### Step 1 · Subtract 4 from both sides
  $$2x = 20$$

  ### Step 2 · Divide both sides by 2
  $$x = 10$$

  > $x = 10$
- A recipe for any food, or a meal/menu idea for a goal (more protein, low-carb, quick, kid-friendly, using up leftovers,
  anything): always give the real, complete thing, never a vague description and never a refusal or health disclaimer.
  A recipe for a named dish: a short title line, then a "### Ingredients" heading with a bulleted list with quantities,
  then a "### Steps" heading with numbered steps. A meal idea for a goal (no dish named): 1-3 concrete options with
  roughly what makes each fit (e.g. "≈50g protein"), and give the full recipe (same layout) if the user then asks
  for one. If what's asked for is unusual or impossible to actually cook, still answer helpfully and in the same spirit
  rather than refusing."""


# ---------- Timers ----------
typed_inputs = queue.Queue()  # lines typed into the window, handled by the main loop like spoken commands
announcements = queue.Queue()  # spoken by the main loop, so Jervis never talks over his own microphone


def notify(title: str, message: str) -> None:
    osal.notify(title, message)


def ring() -> None:
    osal.chime(2)


def describe_timer(timer: dict) -> str:
    label = f" for {timer['label']}" if timer["label"] and timer["kind"] == "timer" else ""
    return f"{format_duration(timer['total'])} timer{label}"


def deliver_alert(payload: dict) -> bool:
    """Show an alert card in the window. Opens the window first if it is closed. Returns True if it was delivered now."""
    global alerts_open
    if connected_clients and ws_loop:
        alerts_open += 1
        asyncio.run_coroutine_threadsafe(_send_payload_async(payload), ws_loop)
        return True
    pending_alerts.append(payload)
    launch_ui()
    return False


def on_timer_fired(timer: dict) -> None:
    if timer["kind"] == "reminder":
        message = f"Reminder: {timer['label']}." if timer["label"] else "Time's up."
        spoken = message
    else:
        message = f"Your {describe_timer(timer)} is done."
        spoken = f"Time's up. {message}"
    shown = deliver_alert({"type": "timer_done", "data": {
        "id": timer["id"], "label": timer["label"], "kind": timer["kind"], "total": timer["total"], "message": message}})
    if not shown:  # nobody to play the chime yet, so use the system sound until the window opens
        threading.Thread(target=ring, daemon=True).start()
    notify("Jervis", message)
    announcements.put(spoken)


def publish_timers(timers: list) -> None:
    send_ui_update("timers", [
        {"id": t["id"], "label": t["label"], "kind": t["kind"], "total": t["total"], "end": int(t["end"] * 1000)}
        for t in timers
    ])


timer_manager = TimerManager(on_fire=on_timer_fired, on_change=publish_timers)


def handle_timer_command(text: str):
    command = parse_timer_command(text, have_timers=bool(timer_manager.snapshot()))
    if not command:
        return None
    action = command["action"]
    if action == "ask":
        return "How long should I set it for?"
    if action == "set":
        timer = timer_manager.add(command["seconds"], command["label"], command["kind"])
        if timer["kind"] == "reminder":
            what = f" to {timer['label']}" if timer["label"] else ""
            return f"Okay, I'll remind you{what} in {format_duration(timer['total'])}."
        return f"Timer set for {format_duration(timer['total'])}" + (f", for {timer['label']}." if timer["label"] else ".")
    if action == "cancel":
        cancelled = timer_manager.cancel(command["label"], command["all"])
        if not cancelled:
            return "You don't have any timers running."
        if len(cancelled) > 1:
            return f"Cancelled all {len(cancelled)} timers."
        return f"Cancelled the {describe_timer(cancelled[0])}."
    active = timer_manager.snapshot()
    if not active:
        return "You don't have any timers running."
    now = time.time()
    lines = [f"the {describe_timer(t)} has {format_duration(t['end'] - now, short=True)} left" for t in active]
    if len(lines) == 1:
        return lines[0][0].upper() + lines[0][1:] + "."
    return f"You have {len(lines)} timers: " + "; ".join(lines) + "."


last_llm_reply = None  # {"text", "at"}: the last answer the AI wrote, for "put this list in a document"
pending_dictation = None  # {"app", "at"}: Jervis asked what to write, and the next thing you say is the content
pending_spotify_request = None  # {"at"}: Jervis asked what to listen to, and the next thing you say is a song/artist
pending_google_search = None  # {"at"}: Jervis asked what to search, and the next thing you say is the search itself
pending_netflix_request = None  # {"at"}: Jervis asked what to watch, and the next thing you say is a show/movie title
pending_stremio_request = None  # {"at"}: same, for Stremio
pending_calendar_choice = None  # {"at"}: Jervis asked "hear the next events, or make a new one?"
pending_calendar_event = None  # {"step", "fields", "at"}: building a new event one answer at a time (see calendar_time)
DEFAULT_DOC_APP = "gdocs"


def title_from_question(question: str) -> str:
    """"What is a healthy breakfast?" -> "Healthy Breakfast"."""
    t = " ".join(re.sub(r"[^\w' ]", " ", (question or "").lower()).split())
    t = re.sub(r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:please )?(?:(?:can|could|would) you )?"
               r"(?:(?:give|tell|show|get) me |i (?:need|want) |what(?:'s| is| are) |list |suggest |recommend |write )?"
               r"(?:(?:a|an|the|some|me|few) )*", "", t)
    return " ".join(t.split()[:6]).title()


def fresh_llm_reply():
    if last_llm_reply and time.time() - last_llm_reply["at"] < 30 * 60:
        return last_llm_reply["text"]
    return None


def open_blank_document(app_key: str, context: str = "") -> str:
    global last_document, pending_dictation
    name = documents.APP_NAMES[app_key]
    try:
        ref = documents.create_blank(app_key, context)
    except Exception as e:
        return f"I couldn't open a new document in {name}: {e}"
    last_document = {"app": app_key, "ref": ref, "title": "", "body": "", "at": time.time()}
    pending_dictation = {"app": app_key, "at": time.time()}  # the next thing said becomes the document's content
    return f"Opened a new document in {name}. What would you like to write?"


def transfer_to_document(text: str) -> str:
    """"Put this list in a Google Doc": the last answer goes into a new document. If there is none, ask what to write."""
    global last_document, pending_dictation
    app_key = documents.detect_app(text) or (last_document or {}).get("app") or DEFAULT_DOC_APP
    name = documents.APP_NAMES[app_key]
    reply = fresh_llm_reply()
    if not reply:
        pending_dictation = {"app": app_key, "at": time.time()}
        what = "list" if re.search(r"\blist\b", text.lower()) else "text"
        return f"Sure. What should the {what} say?"
    title, body = documents.reply_to_document(reply)
    if re.match(r"(?i)^(here|sure|okay|of course|certainly|absolutely|great|yes)\b", title):
        title = title_from_question(last_llm_reply.get("question", "")) or "Notes"  # a chatty intro makes a poor title
    try:
        ref = documents.insert(app_key, title, body, context=f"{text} {title} {last_llm_reply.get('question', '')}")
    except Exception as e:
        return f"I couldn't put it into {name}: {e}"
    last_document = {"app": app_key, "ref": ref, "title": title, "body": body, "at": time.time()}
    if app_key == "gdocs":
        return f"I opened a new Google Doc with {title}. The text is also on your clipboard if it doesn't appear."
    return f"Done. I put {title} in {name}."


DOC_EDIT_PROMPT = (
    "You edit the user's document. Apply exactly the requested change to the document below and output the FULL "
    "revised document: the first line is the title, then a blank line, then the body. Keep everything the request "
    "does not touch. No commentary, no introduction, no markdown symbols such as # or **."
)
DOC_CONTEXT_SECONDS = 45 * 60  # how long "make it shorter" still refers to the document Jervis just wrote
last_document = None  # {"app", "ref", "title", "body", "at"}


def current_document():
    if last_document and time.time() - last_document["at"] < DOC_CONTEXT_SECONDS:
        return last_document
    return None


def edit_document(request: str) -> str:
    """Apply a spoken change ("make it shorter", "add a paragraph about X") to the document Jervis wrote."""
    global last_document
    doc = current_document()
    app_key, app_name = doc["app"], documents.APP_NAMES[doc["app"]]
    try:
        response = groq_chat(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": DOC_EDIT_PROMPT},
                {"role": "user", "content": f"Document:\n{doc['title']}\n\n{doc['body']}\n\nRequested change: {request}"},
            ],
            max_tokens=3000,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"Document edit failed: {e!r}")
        return groq_error_reply(e)
    if not text:
        return "I couldn't work out how to make that change. Try saying it another way."
    title, body = documents.split_title(text)
    try:
        documents.update(app_key, doc["ref"], title, body)
        outcome = f"Done. I updated {title} in {app_name}."
        ref = doc["ref"]
    except Exception as e:
        print(f"Document update failed: {e!r}")
        if app_key == "gdocs":
            last_document = {**doc, "title": title, "body": body, "at": time.time()}  # keep the new text for next edits
            return str(e)
        try:  # the old document is gone or was renamed: put the revised text in a new one
            ref = documents.insert(app_key, title, body, context=title)
            outcome = f"I couldn't reach the earlier document, so I made a new one in {app_name} with your changes."
        except Exception as e2:
            return f"I couldn't change the document: {e2}"
    last_document = {"app": app_key, "ref": ref, "title": title, "body": body, "at": time.time()}
    return outcome


DOC_SYSTEM_PROMPT = (
    "You write the text of a document for the user. Output ONLY the document: the first line is a short title, "
    "then a blank line, then the body. No introduction, no closing remarks, no markdown symbols such as # or **. "
    "Ignore any part of the request about opening an app. Unless the request says otherwise, keep it short "
    "(about 150 to 300 words)."
)


def write_document(request: str, app_key: str) -> str:
    """Write what the user asked for, then put it into a new document in the chosen app."""
    app_name = documents.APP_NAMES[app_key]
    try:
        response = groq_chat(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": DOC_SYSTEM_PROMPT}, {"role": "user", "content": request}],
            max_tokens=2500,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"Document generation failed: {e!r}")
        return groq_error_reply(e)
    if not text:
        return "I couldn't come up with any text for that. Try asking again."
    title, body = documents.split_title(text)
    global last_document
    try:
        ref = documents.insert(app_key, title, body, context=f"{request} {title}")
    except Exception as e:
        print(f"Document insert failed: {e!r}")
        return f"I wrote it, but couldn't put it into {app_name}: {e}"
    last_document = {"app": app_key, "ref": ref, "title": title, "body": body, "at": time.time()}
    if app_key == "gdocs":
        return f"I wrote {title} and opened a new Google Doc. The text is also on your clipboard if it doesn't appear."
    return f"Done. I wrote {title} in {app_name}."


def is_music_command(text: str) -> bool:
    """Only allow music controls for an explicit music request."""
    normalized = " ".join((text or "").lower().strip().split())
    return bool(re.search(r"\b(play|pause|stop|resume|next)\b.*\b(song|music|spotify|track)\b", normalized)) or normalized.startswith("play ")


def is_app_command(text: str) -> bool:
    return parse_open_request(text) is not None


def should_enable_tools(text: str) -> bool:
    """Do not expose tools during ordinary conversation or incomplete phrases."""
    return (is_google_search_command(text) or is_music_command(text) or is_app_command(text) or is_youtube_command(text)
            or images.is_image_command(text) or images.has_pending_context())


def diagnose_connection(host: str = "api.groq.com") -> str:
    """Work out WHY a host can't be reached: DNS, blocked connection, or a certificate problem."""
    import socket
    import ssl
    try:
        address = socket.getaddrinfo(host, 443)[0][4][0]
    except OSError:
        return f"this PC can't look up {host} (DNS problem: check the internet connection, a VPN, or a DNS filter)"
    try:
        sock = socket.create_connection((address, 443), timeout=8)
    except OSError as e:
        return f"{host} is found but the connection is blocked or times out ({e}): check the firewall, antivirus, VPN or proxy"
    try:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=host):
            pass
    except ssl.SSLError as e:
        return f"the secure connection to {host} failed ({e}): an antivirus or network filter may be intercepting HTTPS"
    except OSError as e:
        return f"the connection to {host} dropped ({e})"
    finally:
        sock.close()
    return f"{host} is reachable from Python, so the problem is inside the AI library or the key"


def local_ai_summary() -> str:
    model, reason = local_llm.status()
    return f"A local AI backup is ready (Ollama, model {model})." if model else reason


def check_ai_connection() -> None:
    """At startup, say clearly which AI Jervis will use, so a missing key or a blocked network is not a mystery later."""
    global groq_down_until
    local_model, local_reason = local_llm.status()
    problem = None
    if LLM_BACKEND == "ollama":
        print(f"Using the local AI only (LLM_BACKEND=ollama): {local_ai_summary()}", flush=True)
        return
    if not GROQ_KEY:
        problem = "The online AI key is empty. Open the .env file, paste your GROQ_API_KEY after the = sign, save, and start again."
    else:
        try:
            groq_client.with_options(timeout=12, max_retries=0).models.list()
            print("The online AI connection works." + (f"  Local backup: Ollama ({local_model})." if local_model else ""), flush=True)
            return
        except Exception as e:
            if getattr(e, "status_code", None) in (401, 403):
                problem = "The online AI service rejected the key. Check GROQ_API_KEY in the .env file (no spaces, the whole key)."
            else:
                problem = (f"Can't reach the online AI service: {diagnose_connection()}."
                           f" (technical detail: {type(e.__cause__ or e).__name__}: {e.__cause__ or e})")
    groq_down_until = time.time() + 3600
    if LLM_BACKEND == "auto":
        print(f"\n*** {problem}\n    Jervis will use the local AI instead"
              + (f" (Ollama, model {local_model})." if local_model else " as soon as its setup finishes.") + " ***\n",
              flush=True)
    else:
        print(f"\n*** {problem}\n    (Jervis still understands commands like opening apps and timers without any AI.)\n",
              flush=True)


def local_ai_status_reply() -> str:
    """What to say when the AI on this computer can't answer yet: how far its setup is, or what went wrong."""
    state = local_ai_manager.state
    if state.get("active"):
        step = next((s for s in state["steps"] if s["state"] == "active"), None)
        detail = f" ({step['detail'].rstrip('…').rstrip('.')})" if step and step.get("detail") else ""
        return (f"My AI is still getting ready{detail}. Timers, music, apps and the rest already work, "
                "so ask me those any time, and ask me this again in a little while.")
    if state.get("error"):
        return f"My AI couldn't be set up: {state['error']} {state.get('hint') or ''}".strip()
    local_ai_manager.start_background()   # it was ready before and stopped: bring it back
    return "My AI isn't running right now, so I'm starting it again. Ask me again in a moment."


def groq_error_reply(error: Exception) -> str:
    if isinstance(error, local_llm.LocalAIUnavailable):
        return local_ai_status_reply()
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        return "My online AI rejected the Groq key. Check it in Settings, or switch to the local AI there."
    if status == 429:
        wait = rate_limit_wait(error)
        return ("I've used up the free AI's limit for this minute. "
                + (f"Ask me again in about {int(wait) + 1} seconds." if wait else "Ask me again in a few seconds.")
                + " The local AI (Settings) has no limit.")
    if status == 413:
        return "That was too much for the online AI to handle at once. Try a shorter request."
    if status:
        return f"The online AI returned an error ({status}). The details are in logs/ai_errors.log."
    return "I couldn't reach my language model. Check your internet connection."


def log_ai_error(error: Exception) -> None:
    """Keep the real reason an AI call failed (the spoken message can't say it), in logs/ai_errors.log."""
    try:
        with open(os.path.join(paths.logs_dir(), "ai_errors.log"), "a", encoding="utf-8") as f:
            cause = error.__cause__ or error
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {type(error).__name__} "
                    f"status={getattr(error, 'status_code', None)} {type(cause).__name__}: {str(error)[:400]}\n")
    except OSError:
        pass


def rate_limit_wait(error: Exception):
    """Seconds the online AI asks us to wait after a 429 ("Please try again in 5.5s"), or None."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        pass
    match = re.search(r"try again in ([\d.]+)s", str(error))
    return float(match.group(1)) if match else None


def is_model_glitch(error: Exception) -> bool:
    """The model itself produced garbage ("tool_use_failed", "output_parse_failed"). It is random, so retrying works."""
    body = getattr(error, "body", None)
    code = (body.get("error", {}) if isinstance(body, dict) else {}).get("code") if isinstance(body, dict) else None
    return code in ("tool_use_failed", "output_parse_failed") or "tool_use_failed" in str(error) or "output_parse_failed" in str(error)


def _groq_chat_with_retry(**kwargs):
    """One online-AI call. A short rate-limit wait is honoured (the answer comes a few seconds late instead of never)."""
    try:
        return groq_client.chat.completions.create(**kwargs)
    except Exception as e:
        log_ai_error(e)
        status = getattr(e, "status_code", None)
        if is_model_glitch(e):
            print("The online AI produced a garbled answer; asking again...", flush=True)
            return groq_client.chat.completions.create(**kwargs)
        if status in (401, 403) or (status and status < 500 and status != 429):
            raise
        wait = rate_limit_wait(e) if status == 429 else 1.5
        if status == 429 and (wait is None or wait > 8):
            raise  # a long wait: let the caller switch to the local AI instead of making the user wait
        print(f"Online AI busy ({type(e).__name__}); waiting {wait:.1f}s and trying once more...", flush=True)
        time.sleep((wait or 1.5) + 0.3)
        return groq_client.chat.completions.create(**kwargs)


def trim_for_ai(messages: list) -> list:
    """What actually gets sent: the system prompt and the recent turns, with any big document text shortened.

    The free online AI allows only 8,000 tokens a minute, and everything sent counts, so a long history (or the full
    text of a story Jervis wrote) would use it up in a few questions.
    """
    if not messages:
        return messages
    head, rest = messages[:1], messages[1:]
    rest = rest[-10:]
    while rest and (rest[0].get("role") == "tool" or (rest[0].get("role") == "assistant" and rest[0].get("tool_calls"))):
        rest = rest[1:]  # never start in the middle of a tool call
    trimmed = []
    for m in rest:
        if m.get("role") == "system" and len(m.get("content") or "") > 1500:
            m = {**m, "content": m["content"][:1500] + "\n[...text shortened...]"}
        elif m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and len(m["content"]) > 1500:
            m = {**m, "content": m["content"][:1500] + " [...]"}
        trimmed.append(m)
    return head + trimmed


def groq_chat(**kwargs):
    """Ask the AI: the online one first, and the local one (Ollama) when the online one can't be used.

    After a failure the online AI is skipped for a few minutes, so every question isn't delayed by timeouts.
    """
    global groq_down_until
    if "gpt-oss" in str(kwargs.get("model", "")):  # a "thinking" model: keep the thinking short, it counts against the limit
        kwargs.setdefault("reasoning_effort", "low")
        kwargs.setdefault("max_tokens", 1500)
    if LLM_BACKEND == "ollama":
        return local_llm.chat(**kwargs)
    if LLM_BACKEND == "auto" and time.time() < groq_down_until:
        return local_llm.chat(**kwargs)
    try:
        return _groq_chat_with_retry(**kwargs)
    except Exception as e:
        status = getattr(e, "status_code", None)
        log_ai_error(e)
        if LLM_BACKEND == "auto" and is_model_glitch(e):
            try:
                print("The online AI glitched twice; using the local AI for this answer.", flush=True)
                return local_llm.chat(**kwargs)
            except local_llm.LocalAIUnavailable:
                raise e
        if LLM_BACKEND != "auto" or status in (400, 404, 422):  # a bad request is not a reason to switch AI
            raise
        groq_down_until = time.time() + (60 if status == 429 else 300)
        print(f"Online AI unavailable ({type(e.__cause__ or e).__name__}); switching to the local AI for a while.", flush=True)
        try:
            return local_llm.chat(**kwargs)
        except local_llm.LocalAIUnavailable as local_problem:
            groq_down_until = 0.0  # nothing to switch to: try the online AI again next time
            if status == 429:
                raise e  # the honest answer is "rate limited, wait a moment", not "install a local AI"
            raise local_problem from e


IMAGE_READ_TOOLS = [t for t in TOOLS if t["function"]["name"] in ("analyze_image", "extract_image_text", "compare_images")]
_REFERS_TO_SOMETHING = re.compile(r"\b(it|this|that|these|those)\b", re.I)
_REFLEXIVE_APOLOGY_RE = re.compile(
    r"^(i['’]?m (sorry|having trouble|unable)|sorry[,.]|i apologi[sz]e"
    r"|i (can['’]?t|couldn['’]?t|wasn['’]?t able to) (see|view|read|retrieve|access|get|use))", re.I)


def _looks_like_reflexive_apology(text: str) -> bool:
    return bool(_REFLEXIVE_APOLOGY_RE.match(text.strip()))


def select_tools(user_text: str):
    """Which tools to offer the AI this turn, and whether to force one. The model is otherwise reluctant to call an
    image tool for a vague follow-up ("what's wrong with it") even with an image plainly pending, because of the
    "never call tools unless explicit" rule — so a clear read request, or a message that both refers to something
    ("it"/"this"/"that") and arrives right after an image, forces one of the read-only image tools instead of
    leaving the choice to an overly cautious model. Anything else (e.g. "what is 12 plus 30" right after an image
    was shared) is left alone: Groq's API errors out if a forced tool call is offered a message with nothing to
    call it about, so this must stay narrow."""
    other_explicit = (is_google_search_command(user_text) or is_music_command(user_text) or is_app_command(user_text)
                       or is_youtube_command(user_text) or images.is_image_generation_command(user_text)
                       or images.is_image_edit_command(user_text))
    wants_read = (images.is_image_analyze_command(user_text) or images.is_image_ocr_command(user_text)
                  or images.is_image_compare_command(user_text))
    referential_followup = images.just_received_image() and bool(_REFERS_TO_SOMETHING.search(user_text or ""))
    if not other_explicit and (wants_read or referential_followup):
        return IMAGE_READ_TOOLS, "required"
    if should_enable_tools(user_text):
        return TOOLS, "auto"
    return None, "auto"


def _failed_generation_text(error: Exception) -> str:
    """When tool_choice="required" is set but the model reasonably answers in plain text instead (for example, a
    follow-up it can already answer from an earlier tool result still in the conversation, with nothing new to call
    a tool about), Groq rejects the response with a 400 — but hands back exactly what the model would have said."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return ((body.get("error") or {}).get("failed_generation") or "").strip()
    return ""


def ask_jervis(messages, user_text=""):
    tools, tool_choice = select_tools(user_text)
    try:
        kwargs = {"model": GROQ_MODEL, "messages": trim_for_ai(messages)}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        response = groq_chat(**kwargs)
    except Exception as e:
        if tools and tool_choice == "required":
            fallback = _failed_generation_text(e)
            if fallback:
                return fallback
            try:  # a forced image-tool turn failed for some other reason: retry once, without forcing, rather than give up
                response = groq_chat(model=GROQ_MODEL, messages=trim_for_ai(messages))
                content = (response.choices[0].message.content or "").strip()
                return content or "I'm listening. How can I help?"
            except Exception as e2:
                e = e2
        print(f"Groq API Error: {e!r}")
        log_ai_error(e)
        return groq_error_reply(e)

    msg = response.choices[0].message
    tool_calls = msg.tool_calls or []

    if not tool_calls:
        content = (msg.content or "").strip()
        return content if content else "I'm listening. How can I help?"

    messages.append({
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in tool_calls
        ],
    })

    for tc in tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            args = {}
        func = TOOL_FUNCTIONS.get(name)
        try:
            if name == "google_search" and not is_google_search_command(user_text):
                result = "Google search was blocked because the user did not explicitly say Google. Respond without opening a browser."
            elif name in {"play_song", "pause_music"} and not is_music_command(user_text):
                result = "Music control was blocked because the user did not explicitly request music playback. Respond normally."
            elif name == "play_youtube_video" and not is_youtube_command(user_text):
                result = "YouTube playback was blocked because the user did not explicitly request a YouTube video. Respond normally."
            elif name == "open_application" and not is_app_command(user_text):
                result = "Opening an app was blocked because the user did not explicitly ask to open an application. Respond normally."
            elif name == "generate_image" and not images.is_image_generation_command(user_text):
                result = "Image generation was blocked because the user did not explicitly ask to create an image. Respond without generating one."
            elif name == "edit_image" and not images.is_image_edit_command(user_text):
                result = "Image editing was blocked because the user did not explicitly ask to edit the image. Respond without editing it."
            elif func:
                if name == "play_song":
                    args["start_seconds"] = args.get("start_seconds") or parse_start_time(user_text)[0]
                result = func(**args)
            else:
                result = f"Unknown tool: {name}"
        except Exception as e:
            print(f"Tool error: {e}")
            result = f"Tool failed: {e}"

        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    try:
        final_response = groq_chat(model=GROQ_MODEL, messages=trim_for_ai(messages))
        content = (final_response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"Groq final response error: {e!r}")
        return str(result)  # the tool already produced a spoken-ready result; use it as is
    if not content:
        return str(result)
    # A known glitch right after a forced tool call (see select_tools): this composing step sometimes hallucinates a
    # vague, reflexive apology instead of using the tool result sitting right there in the conversation — even when
    # that result is itself a perfectly clear, specific error message (e.g. "no credits remaining, add billing at
    # ..."), which the vague apology then throws away. Every tool result here is already written to be complete and
    # user-facing, so for a single, unambiguous tool call, trust it over a hollow-sounding composed reply.
    if len(tool_calls) == 1 and _looks_like_reflexive_apology(content):
        return str(result)
    return content


class ReadAloud(str):
    """A reply the user asked to hear (\"read me the story\"): spoken in full instead of summarised."""


_HEBREW = re.compile(r"[\u0590-\u05FF]")


def voice_args(text: str) -> list:
    """`say` picks the voice from the script: Hebrew text needs the Hebrew voice, or it is read as gibberish."""
    return ["-v", "Carmit"] if _HEBREW.search(text or "") else []


def tidy_math(text: str) -> str:
    """The AI sometimes writes LaTeX as \\( ... \\) or \\[ ... \\]. The window and the voice both expect dollar signs, so convert."""
    text = re.sub(r"\\\[\s*(.+?)\s*\\\]", lambda m: "\n$$" + m.group(1).strip() + "$$\n", text, flags=re.S)
    text = re.sub(r"\\\(\s*(.+?)\s*\\\)", lambda m: "$" + m.group(1).strip() + "$", text, flags=re.S)
    return re.sub(r"\\[dt]frac", r"\\frac", text)


def _latex_to_speech(text: str) -> str:
    """Formulas between dollar signs, said in words (a safety net: the spoken sentence should not contain any)."""
    text = tidy_math(text)
    def words(m):
        t = m.group(1)
        for pattern, replacement in ((r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1 over \2"), (r"\\sqrt\{([^{}]*)\}", r"square root of \1"),
                                     (r"\\pm", " plus or minus "), (r"\\(?:cdot|times)", " times "), (r"\\div", " divided by "),
                                     (r"\^\{?2\}?", " squared"), (r"\^\{?3\}?", " cubed"), (r"\^\{([^{}]*)\}", r" to the power of \1"),
                                     (r"\\[a-zA-Z]+", " "), (r"[{}\\]", "")):
            t = re.sub(pattern, replacement, t)
        return t
    return re.sub(r"\$\$?([^$]+)\$\$?", words, text)


def _strip_markdown(text: str) -> str:
    text = _latex_to_speech(text)
    text = re.sub(r"\*\*|__|`|~~", "", text)
    text = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)  # emoji
    return " ".join(text.split())


_STRUCTURE = re.compile(r"^(?:\||#{1,6}\s|[-*\u2022]\s|\d+[.)]\s|>\s?|```|\*\*[^*]+\*\*:?\s*$)")


def _say_math(text: str) -> str:
    """Math symbols as words for the voice: "x = 10" -> "x equals 10"."""
    for pattern, words in ((r"\s*[=\u2248]\s*", " equals "), (r"\s*\u00d7\s*", " times "), (r"\s*\u00f7\s*", " divided by "),
                           (r"(?<=\d)\s+\+\s+(?=[\w(])", " plus "), (r"(?<=\d)\s+[-\u2212]\s+(?=\d)", " minus "),
                           (r"\^2\b", " squared"), (r"\^3\b", " cubed"),
                           (r"\u221a", "square root of ")):
        text = re.sub(pattern, words, text)
    return " ".join(text.split())


def spoken_version(text: str) -> str:
    """The part of a (possibly Markdown) reply worth reading aloud: no symbols, tables or long lists."""
    if isinstance(text, SpokenReply):
        return text.spoken
    if isinstance(text, ReadAloud):
        return _strip_markdown(str(text))
    return _say_math(_spoken_version(text))


def _spoken_version(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    # The very first line is always eligible to be the spoken intro (usually a title, like a recipe's bolded name),
    # even if it happens to match _STRUCTURE the same way a "**Ingredients**"-style section label further down would.
    structured = [i for i, ln in enumerate(lines) if i > 0 and _STRUCTURE.match(ln)]
    if structured:
        # Read the intro and a closing question; the lists and tables stay on screen.
        first = structured[0]
        intro = _strip_markdown(" ".join(ln for ln in lines[:first] if not re.fullmatch(r"[-=_*\s|:]{3,}", ln)))
        last = lines[-1]
        closing = ""
        if len(lines) - 1 > first and not _STRUCTURE.match(last) and _strip_markdown(last).endswith("?"):
            closing = _strip_markdown(last)
        note = "I've put the details on your screen." if connected_clients else ""
        return " ".join(part for part in (intro or "Here's what I found.", note, closing) if part)
    plain = _strip_markdown(" ".join(lines))
    if len(plain) <= 320:
        return plain
    short = ""
    for sentence in re.split(r"(?<=[.!?])\s+", plain):
        if short and len(short) + len(sentence) > 240:
            break
        short = f"{short} {sentence}".strip()
    short = short[:320].rsplit(" ", 1)[0] if len(short) > 320 else short
    return f"{short} I've put the details on your screen." if connected_clients else short


_FAREWELL = re.compile(
    r"(?:(?:hey|ok|okay|alright|all right|well|so|right|thanks|thank you|cool|great|jervis|jarvis)\s+)*"
    r"(?P<phrase>goodbye|good bye|bye(?: bye)?|goodnight|good night|see you(?: later| soon| tomorrow| around)?|see ya|"
    r"take care|talk to you later|catch you later|have a (?:good|great|nice|lovely|wonderful|pleasant) "
    r"(?:day|night|evening|one|afternoon|weekend)|sleep well|i(?:'m| am) (?:going|off) to (?:bed|sleep))"
    r"(?:\s+(?:jervis|jarvis|buddy|friend|mate|man|thanks|thank you|now|for now|you too))*"
)


def is_shutdown_command(text):
    """Goodbyes in any of the usual forms ("Goodbye.", "Have a good day, Jervis", "bye bye") put Jervis to sleep."""
    if not text:
        return False
    normalized = " ".join(re.sub(r"[^a-z' ]", " ", text.lower()).split())
    return bool(_FAREWELL.fullmatch(normalized))


def farewell_reply(text: str) -> str:
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    sleep = "Going to sleep. Say Hey Jervis when you want me."
    if re.search(r"good ?night|\bnight\b|\bevening\b|sleep well|\bbed\b|\bsleep\b", n):
        return f"Goodnight! {sleep}"
    if re.search(r"have a", n):
        return f"You too, have a great day! {sleep}"
    if re.search(r"see you|see ya|later|take care", n):
        return f"See you later! {sleep}"
    return f"Goodbye! {sleep}"


# Whisper sometimes invents these when it is fed noise or near-silence.
WHISPER_HALLUCINATIONS = {
    "thanks for watching", "thank you for watching", "please subscribe",
    "subscribe to my channel", "you", "so", "uh", "um", "hmm",
}


def transcribe_groq(wav_bytes: bytes) -> str:
    """Whisper on Groq: far more accurate than the free Google web recognizer.

    No `prompt` on purpose: with silence or noise Whisper echoes the prompt back
    ("Play a song."), which would fire commands from background noise.
    """
    result = groq_client.audio.transcriptions.create(
        file=("speech.wav", wav_bytes),
        model=STT_MODEL,
        language="en",
        temperature=0.0,
        timeout=15,
    )
    return (result.text or "").strip()


def transcribe_google(audio) -> str:
    try:
        return recognizer.recognize_google(audio, language="en-US").strip()
    except sr.UnknownValueError:
        return ""


def transcribe(audio, passive=False) -> str:
    """Speech to text with a fallback engine.

    Passive (sleeping) listening hears every noise in the room, so it tries the
    free Google engine first to spare the Groq rate limit; active listening
    tries Whisper first for accuracy. Either falls back to the other on error.
    """
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    local = [("Local Whisper", lambda: stt_local.transcribe(wav_bytes))] if stt_local.ready() else []
    online_whisper = ([("Whisper", lambda: transcribe_groq(wav_bytes))]
                      if GROQ_KEY and time.time() >= groq_down_until else [])  # needs the key and a reachable Groq
    google = [("Google", lambda: transcribe_google(audio))]
    if passive:   # hears every noise in the room: spare the online limits, prefer this computer
        engines = local + google + online_whisper
    else:         # a real request: the most accurate first (Groq's big Whisper when there's a key)
        engines = online_whisper + local + google

    for name, engine in engines:
        try:
            text = engine()
        except Exception as e:
            print(f"{name} speech recognition failed: {e}")
            continue
        cleaned = " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())
        if cleaned in WHISPER_HALLUCINATIONS:
            return ""
        return text
    return ""


def listen_or_typed(source):
    """recognizer.listen in one-second slices, so a line typed in the window is noticed within a second.
    Returns the audio, or None as soon as something was typed. Raises WaitTimeoutError after 10 quiet seconds.

    dynamic_energy_threshold is off (see the note by its assignment), so slicing the wait like this no longer touches
    energy_threshold at all; this floor is just a last-resort guard in case anything else ever changes it mid-wait."""
    deadline = time.time() + 10
    while True:
        if not typed_inputs.empty():
            return None
        try:
            return recognizer.listen(source, timeout=1, phrase_time_limit=20)
        except sr.WaitTimeoutError:
            recognizer.energy_threshold = max(recognizer.energy_threshold, MIN_ENERGY_THRESHOLD)
            if time.time() >= deadline:
                raise


mic_problem = ""   # what's wrong with the microphone, shown in the window once (not every retry)
_MIC_RETRY_SECONDS = 3


def open_microphone():
    """The microphone chosen in Settings (by name), or the system default if none is chosen or it's unplugged."""
    wanted = os.getenv("JERVIS_MIC", "").strip()
    if wanted:
        try:
            import pyaudio
            audio = pyaudio.PyAudio()
            try:
                for i in range(audio.get_device_count()):
                    info = audio.get_device_info_by_index(i)
                    if info.get("name") == wanted and int(info.get("maxInputChannels", 0)) > 0:
                        return sr.Microphone(device_index=i)
            finally:
                audio.terminate()
            report_mic_problem(f"The microphone \u201c{wanted}\u201d isn't connected; using the system default.",
                               blocking=False)
        except Exception as e:
            print(f"Could not open the chosen microphone: {e}", flush=True)
    return sr.Microphone()


def report_mic_problem(message: str, blocking: bool = True) -> None:
    """Tell the window (once per distinct problem) and, for a problem that stops listening, wait before retrying so
    a missing microphone doesn't make Jervis spin at full speed."""
    global mic_problem
    if message != mic_problem:
        mic_problem = message
        print(message, flush=True)
        send_ui_update("mic", {"ok": False, "message": message})
    if blocking:
        time.sleep(_MIC_RETRY_SECONDS)


def clear_mic_problem() -> None:
    global mic_problem
    if mic_problem:
        mic_problem = ""
        send_ui_update("mic", {"ok": True, "message": ""})


def listen(passive=False):
    """Capture one phrase and return its text, or None if nothing usable was heard."""
    global mic_calibrated, last_calibrated_at
    if AUDIO_OFF:   # test mode: nothing is recorded; typed lines are handled by the main loop
        time.sleep(0.25)
        return None
    try:
        microphone = open_microphone()
    except OSError as e:
        report_mic_problem("No microphone found. Plug one in, or choose one in Settings. "
                           f"(detail: {e})")
        return None
    try:
        with microphone as source:
            clear_mic_problem() if not mic_problem.startswith("The microphone \u201c") else None
            # Recalibrated once at startup, and again every few minutes while asleep (never mid-conversation, so it
            # can't clip the start of something you're saying), so a room that's gotten noisier or quieter is still
            # tracked, without the fast per-slice decay that used to make Jervis go deaf (see the note by MIN_ENERGY_THRESHOLD).
            if not mic_calibrated or (passive and time.time() - last_calibrated_at > RECALIBRATE_EVERY):
                print("Calibrating microphone...")
                recognizer.adjust_for_ambient_noise(source, duration=1.0)
                mic_calibrated = True
                last_calibrated_at = time.time()
            if not passive:
                send_status("listening")
            print(f"Listening... (threshold {recognizer.energy_threshold:.0f})")
            audio = listen_or_typed(source)
            if audio is None:  # something was typed meanwhile: the main loop handles that first
                return None

        recognizer.energy_threshold = max(recognizer.energy_threshold, MIN_ENERGY_THRESHOLD)

        if mic_muted.is_set():
            return None
        seconds = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
        if seconds < MIN_PHRASE_SECONDS:
            send_status("sleeping" if passive else "idle")
            return None

        if not passive:
            send_status("thinking")
        text = transcribe(audio, passive=passive)
        if len(text.strip()) < 2:
            print("Speech was not understood.")
            send_status("sleeping" if passive else "idle")
            return None

        print(f"Recognized: {text}")
        return text

    except sr.WaitTimeoutError:
        send_status("sleeping" if passive else "idle")
        return None
    except OSError as e:   # the device vanished, is busy, or refused to open: say so, and don't retry at full speed
        send_status("sleeping" if passive else "idle")
        report_mic_problem(f"The microphone stopped working ({e}). Check it's plugged in, or pick another in Settings.")
        return None
    except Exception as e:
        print(f"Mic error: {e}")
        send_status("sleeping" if passive else "idle")
        time.sleep(0.5)
        return None


def wait_for_speech(proc) -> None:
    """Wait for `say` to finish, cutting it off as soon as the window's stop button (or Space) is used."""
    while proc.poll() is None:
        if interrupt_speech.is_set():
            proc.terminate()
            break
        time.sleep(0.05)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def speak(text):
    if not text or not text.strip():
        return

    text = text.strip()
    send_status("speaking")
    print(f"Speaking: {text}")
    interrupt_speech.clear()
    if AUDIO_OFF:   # test mode: the reply was printed and shown, nothing is played
        send_status("idle")
        return

    try:
        proc = osal.speech_process(text)
        if proc is not None:
            wait_for_speech(proc)
        elif get_tts_engine() is not None:
            get_tts_engine().say(text)
            get_tts_engine().runAndWait()
        else:
            print("No text-to-speech voice is available on this system.")
    except Exception as e:
        print(f"TTS Error: {e}")
    finally:
        if interrupt_speech.is_set():
            interrupt_speech.clear()
            send_status("listening")  # cut off on purpose: the next thing said is for Jervis, so no pause
        else:
            time.sleep(POST_SPEECH_PAUSE)
            send_status("idle")


def remember_turn(messages: list, user_text: str, reply: str, turn_started: float, private: bool = False) -> None:
    """Put a command Jervis handled himself into the AI's memory, so "read the story" or "shorten it" makes sense later."""
    messages.append({"role": "user", "content": user_text})
    messages.append({"role": "assistant", "content": PRIVATE_PLACEHOLDER if private else reply})
    doc = last_document
    if doc and doc.get("body") and doc["at"] >= turn_started:
        messages.append({"role": "system", "content": (
            f"Context: Jervis just wrote or changed a document in {documents.APP_NAMES[doc['app']]}. "
            f"Title: {doc['title']}\nFull text:\n{doc['body']}")})
    if len(messages) > 42:  # keep the system prompt and the most recent exchanges
        del messages[1:len(messages) - 40]


def main_loop():
    global awake, last_llm_reply

    global chat_history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    chat_history = messages
    print("Jervis background listener is ready. Say 'Wake Up Jervis'.")

    while True:
        while not announcements.empty():  # timers that finished: say so, awake or asleep
            message = announcements.get()
            broadcast("ai", message)
            speak(message)

        try:
            typed = typed_inputs.get_nowait()
        except queue.Empty:
            typed = None
        if typed:
            awake = True  # typing to Jervis wakes him, and works while the microphone is muted
            text = typed
            send_status("thinking")
            print(f"Typed: {text}")
        else:
            if mic_muted.is_set():
                send_status("muted")
                time.sleep(0.3)
                continue

            if not awake and os.getenv("JERVIS_WAKE_WORD", "on") == "off":
                awake = True   # Settings: no wake phrase needed, Jervis is always listening while the mic is on
            if not awake:
                send_status("sleeping")
                text = listen(passive=True)
                if text and is_wake_command(text):
                    awake = True
                    show_fullscreen()
                    welcome = "I'm awake. How can I help?"
                    broadcast("ai", welcome)
                    speak(welcome)
                continue

            text = listen()
            if not text:
                continue

        if not isinstance(text, ImageCaption):  # already shown together with the image itself, in handle_client
            broadcast("user", text)
        if not typed:
            text = fix_names(text) or text  # "Streamio", "Stream here" -> "stremio", etc.
            if is_explicit_wake(text):  # "Hey Jervis" while already awake: bring the window up, full screen
                show_fullscreen()
                here = "I'm here."
                broadcast("ai", here)
                speak(here)
                continue

        turn_started = time.time()
        try:
            direct_result = handle_direct_command(text)
        except Exception:
            # A bug in one command must never take the whole assistant down.
            traceback.print_exc()
            direct_result = "Sorry, something went wrong with that command."
        if direct_result:
            broadcast("ai", direct_result)
            remember_turn(messages, text, str(direct_result), turn_started, private=isinstance(direct_result, PrivateReply))
            speak(spoken_version(direct_result))
            continue

        if is_shutdown_command(text):
            goodbye = farewell_reply(text)
            broadcast("ai", goodbye)
            speak(goodbye)
            awake = False
            send_status("sleeping")
            continue

        messages.append({"role": "user", "content": text})
        image_note = images.context_note()
        if image_note:
            messages.append({"role": "system", "content": image_note})
        try:
            reply = tidy_math(ask_jervis(messages, text))
            if len(reply) > 40:
                last_llm_reply = {"text": reply, "at": time.time(), "question": text}
                note_suggestions(reply)
        except Exception:
            traceback.print_exc()
            reply = "Sorry, something went wrong. Please try again."
        messages.append({"role": "assistant", "content": reply})
        broadcast("ai", reply)
        speak(spoken_version(reply))


if __name__ == "__main__":
    # The window stops the backend with SIGTERM: turn that into a normal exit, so cleanups (the local AI engine Jervis
    # started) run instead of leaving it behind.
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    ws_thread = threading.Thread(target=run_ws_server, daemon=True)
    ws_thread.start()
    ws_loop_ready.wait()

    threading.Thread(target=check_ai_connection, daemon=True).start()
    threading.Thread(target=refresh_devices, daemon=True).start()   # so Settings has them ready
    if LLM_BACKEND in ("ollama", "auto"):   # the local AI is the AI, or the backup: make sure it's there
        local_ai_manager.start_background()
    timer_manager.load()  # timers that were running when Jervis was last closed
    threading.Thread(target=telemetry_loop, daemon=True).start()
    threading.Thread(target=weather_loop, daemon=True).start()
    if os.getenv("JERVIS_SHOW_WINDOW") == "1":  # started with run.py: show the window right away, not only after "Hey Jervis"
        launch_ui()

    try:
        main_loop()
    except KeyboardInterrupt:
        print("\nShutting down.")