import asyncio
import collections
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
if "--selftest" not in __import__("sys").argv:   # (an installed copy checking itself isn't Jervis starting up)
    logbook.install()   # before anything prints, so startup problems end up in logs/jervis.log too
settings.load()     # before any module reads its configuration from the environment
import platform
import re
import secrets
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

import app_launcher
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
import language
import microphones
import write_here
import agent_code
import screen_reader
import blender_commands
import blender_control
import agent_blender
import agent_core
import agent_memory
import agent_minecraft
import reasoning
import nlu
import computer_use
import spotify_local
import spotify_match
import osal
import calendar_api
import calendar_time
import classroom
import earth
import equations
import forecast
import functions
import graphs
import images
import planets
import web_search
import whatsapp
import phone_control
import phone_crypto
import phone_session
import relay_client
import push
import sms
import queue
from timers import TimerManager, format_duration, parse_timer_command
from speech_fixes import fix_names
import speech_fixes
import timeparse
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
# A phone, once paired: a separate server, LAN-bound on purpose (see phone_control.py for why this is never the
# same channel the Electron window uses). JERVIS_RELAY_URL (Settings, Computer control, advanced) defaults to a
# shared relay Jervis ships with, so a paired phone can reach Jervis away from this Wi-Fi with nothing to set up —
# clear it to go back to same-Wi-Fi only, or point it at a different relay (relay/README.md). See relay_client.py.
PHONE_WS_PORT = int(os.getenv("JERVIS_PHONE_PORT") or 8766)
RELAY_URL = (os.getenv("JERVIS_RELAY_URL") or "").strip()
RESTART_EXIT_CODE = 75
PORT_BUSY_EXIT_CODE = 76
AUDIO_OFF = os.getenv("JERVIS_AUDIO", "on").strip().lower() == "off"   # tests: typed input only, replies printed


def speak_volume() -> int:
    """Jervis's own speaking volume (0-100), set from the speaker control next to the mic button."""
    try:
        return max(0, min(100, int(os.getenv("JERVIS_SPEAK_VOLUME", "100"))))
    except ValueError:
        return 100


def speak_muted() -> bool:
    return (os.getenv("JERVIS_SPEAK_MUTED") or "off").strip().lower() == "on"


def set_speak_volume(volume: int, muted: bool) -> None:
    """Applied instantly (settings.update writes .env/settings.json and re-syncs os.environ) and echoed back to
    every window, including ones that connect later (send_ui_update), so the slider reflects reality on load."""
    settings.update({"JERVIS_SPEAK_VOLUME": str(volume), "JERVIS_SPEAK_MUTED": "on" if muted else "off"})
    send_ui_update("speak_volume", {"volume": volume, "muted": muted})

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
# Only his name wakes him: a bare "hi" or "hello" said in the room would open his window at random, now that he keeps
# listening with the window closed. Speech recognition often writes "Jarvis", so both spellings count.
WAKE_PHRASES = [f"{greeting} {name}" for name in ("jervis", "jarvis")
                for greeting in ("wake up", "hey", "hello", "hi", "ok", "okay")]


def time_greeting() -> str:
    """"Good morning/noon/afternoon/evening {name}" for the hour right now (this computer's own clock). Uses
    "Sir" until the user's name is set (Settings, General, or the welcome screen on first start)."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        part = "morning"
    elif hour == 12:
        part = "noon"
    elif 13 <= hour < 18:
        part = "afternoon"
    else:
        part = "evening"
    who = (os.getenv("JERVIS_USER_NAME") or "").strip() or "Sir"
    return f"Good {part}, {who}. How can I help you today?"


window_visible = True   # the window tells us when it's closed (hidden) or shown again
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


_WAKE_LEAD = re.compile(r"^.*?\b(?:wake up|hey|hello|hi|ok|okay)\s+(?:jervis|jarvis)\b[\s,.!?:;-]*", re.I)


def after_wake_phrase(text: str) -> str:
    """What was said after the wake phrase, if it's a request ("Hey Jervis, create a house" -> "create a house"),
    else "" (just "Hey Jervis", or "hey Jervis are you there")."""
    rest = _WAKE_LEAD.sub("", text or "", count=1).strip(" ,.!?")
    if len(rest.split()) < 2 or _EXPLICIT_WAKE.fullmatch(" ".join(re.sub(r"[^a-z0-9 ]", " ", rest.lower()).split())):
        return ""
    return rest[0].upper() + rest[1:]


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
    if control_active():   # the window would cover the app Jervis is working in (and catch his clicks)
        return
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


class PhoneVoiceInput(str):
    """Text transcribed from a phone's push-to-talk recording (see relay_client.py): behaves exactly like any
    other command text to the main loop, but carries the phone session it came from, so the reply can be sent back
    to that phone (relay_client.deliver_reply) in addition to being spoken here as usual."""

    def __new__(cls, text: str, session_id: str):
        obj = str.__new__(cls, text)
        obj.session_id = session_id
        return obj


PRIVATE_PLACEHOLDER = "[private WhatsApp messages: shown and read aloud only]"


def localized(reply):
    """`reply` (English) in the language the user is speaking (language.py), as the same kind of reply: a private
    one stays private, a SpokenReply's spoken version is translated too. Unchanged for English, for text already in
    the user's language, and when it can't be translated reliably."""
    code = language.reply_language()
    if code == "en" or not reply or not isinstance(reply, str):
        return reply
    try:   # never a model call on an event loop's thread (the window's connection): it would stall the loop
        asyncio.get_running_loop()
        allow_model = False
    except RuntimeError:
        allow_model = True
    try:
        text = language.to_user_language(str(reply), code, allow_model=allow_model)
        spoken = (language.to_user_language(reply.spoken, code, allow_model=allow_model)
                  if isinstance(reply, SpokenReply) else None)
    except Exception:
        traceback.print_exc()
        return reply
    if text == str(reply) and spoken is None:
        return reply
    if type(reply) is str:
        return text
    out = str.__new__(type(reply), text)
    out.__dict__.update(getattr(reply, "__dict__", {}))
    if spoken is not None:
        out.spoken = spoken
    return out


def broadcast(sender, text="", image=None, image_kind=None):
    """Show (and, unless private, log) a chat message. `image` is a data: URL, for a picture the user attached or
    Jervis made/edited; `text` may be empty when a message is only a picture. Jervis's own messages are shown in the
    language the user is speaking."""
    if sender != "user" and text:
        text = localized(text)
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
    chat_message = {"type": "chat", "sender": "user" if sender == "user" else "ai", "text": text}
    if image:
        # The relay caps a message at 512 KB (relay/server.py), and encryption grows it by about a third again.
        chat_message["image"] = image if len(image) <= PHONE_IMAGE_MAX_CHARS else ""
    phone_chat_history.append(chat_message)
    mirror_to_phone(chat_message)


# ---------- the phone's chat: a live mirror of this window's conversation (see phone_client.html) ----------
PHONE_HISTORY_MESSAGES = 60        # what a phone sees of the conversation so far, the moment it connects
PHONE_IMAGE_MAX_CHARS = 300_000
phone_chat_history = collections.deque(maxlen=PHONE_HISTORY_MESSAGES)


def mirror_to_phone(message: dict) -> None:
    """Sends `message` to the phone attached right now, if any, over whichever transport (LAN or relay) it's on."""
    session_id = phone_server.current_session_id()
    if session_id:
        session_router.send(session_id, message)


def phone_history() -> list:
    """session_router's callback when a phone attaches: the conversation so far, oldest first, with pictures left
    out (they'd blow well past the relay's message size limit all together) — new ones still arrive live."""
    return [{**m, "image": ""} if m.get("image") else m for m in phone_chat_history]


def send_status(status):
    if ws_loop:
        asyncio.run_coroutine_threadsafe(
            _send_payload_async({"status": status}), ws_loop
        )
    global _phone_status
    if status != _phone_status:   # main_loop re-sends the same status every pass; the phone only needs changes
        _phone_status = status
        mirror_to_phone({"type": "status", "status": status})


_phone_status = None


latest_ui_updates = {}  # last payload per type, replayed to windows that connect later
latest_ui_updates["speak_volume"] = {"type": "speak_volume",
                                     "data": {"volume": speak_volume(), "muted": speak_muted()}}


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


def clear_ui_update(data_type) -> None:
    """Stops a send_ui_update payload from being replayed to a window that connects later — for state that's
    done, not just stale, like a QR code once what it was for (pairing, notification setup) has succeeded."""
    latest_ui_updates.pop(data_type, None)


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
    try:
        return microphones.input_device_names()
    except Exception as e:
        print(f"Could not list microphones: {e}", flush=True)
        return []


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
            "platform": osal.SYSTEM, "dataDir": paths.DATA_DIR, "logFile": logbook.log_path(), "backend": LLM_BACKEND,
            "firstRun": settings.is_first_run()}


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
        if settings.is_first_run():   # a genuinely new install: offer the welcome screen once, right away
            await websocket.send(json.dumps({"type": "first_run"}))
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
            elif data.get("type") == "set_speak_volume":
                try:
                    volume = max(0, min(100, int(data.get("volume", 100))))
                except (TypeError, ValueError):
                    volume = speak_volume()
                set_speak_volume(volume, data.get("muted") is True)
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
            elif data.get("type") == "weather_refresh":   # the weather window's refresh button, or a click on the card
                refresh_weather_window(str(data.get("city") or "")[:80], refresh=data.get("refresh") is not False)
            elif data.get("type") == "window_visibility":
                set_window_visible(data.get("visible") is not False)
            elif data.get("type") == "control_answer":
                answer_control_question(str(data.get("id", "")), data.get("allow") is True)
            elif data.get("type") == "control_command":
                action = data.get("action")
                if action == "stop":
                    if computer_task is not None:
                        computer_task.stop()
                    if session_active():
                        end_control_session()
                elif action == "pause" and control_active():   # pausing only means something mid-task
                    computer_task.pause()
                elif action == "resume" and computer_task is not None:
                    computer_task.resume()
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


# ---------- a phone on the same Wi-Fi (see phone_control.py) ----------
# PHONE_COMMANDS/_dispatch_phone_command/phone_server are defined further down, right before TOOL_FUNCTIONS —
# they reference tool functions (play_song, google_search, ...) that aren't defined yet at this point in the file.


def phone_control_mode() -> str:
    return (os.getenv("JERVIS_PHONE_CONTROL") or "off").strip().lower()


def session_transport_url() -> str:
    """Where a phone should open its session connection: the configured relay if there is one (works from
    anywhere), else this computer's own address on the local network (works only on this Wi-Fi, but that's still
    the whole "connect my phone" experience without deploying a relay — see phone_session.py)."""
    return RELAY_URL or f"ws://{phone_control.lan_address()}:{PHONE_WS_PORT}"


def notification_setup_url() -> str:
    """The link for the one-time "enable notifications on this phone" step. With a relay configured, this is the
    relay's own stable address (it serves the same page — see relay/server.py — and fetches this computer's
    notification key live, so the link works even off this Wi-Fi and never changes with this computer's local IP).
    Without one, it falls back to the local address, same as session_transport_url()."""
    if RELAY_URL:
        return re.sub(r"^ws", "http", RELAY_URL).rstrip("/") + f"/?computerId={relay.computer_id}"
    return f"http://{phone_control.lan_address()}:{PHONE_WS_PORT}"


phone_server_loop = None   # set by run_phone_server(); lets session_router reach a local phone from another thread


async def handle_phone_client(websocket) -> None:
    """One phone's connection: unauthenticated until it pairs (with an open, correct code) or authenticates (with
    a token from an earlier pairing), after which it can run one of PHONE_COMMANDS directly (kind == "command",
    unencrypted — always same-Wi-Fi, always was) or attach a "connect my phone" session (kind == "session_attach",
    then encrypted envelopes) exactly like a relay-routed phone would — see phone_session.py, which owns that
    protocol for both transports."""
    remote = getattr(websocket, "remote_address", None)
    if not phone_control.is_private_address(remote[0] if remote else ""):
        await websocket.close(1008, "not allowed")
        return
    loop = asyncio.get_event_loop()
    device_id = None
    conn_id = f"local:{secrets.token_hex(8)}"

    def schedule_send(obj) -> None:
        if phone_server_loop is not None:
            asyncio.run_coroutine_threadsafe(websocket.send(json.dumps(obj)), phone_server_loop)

    def schedule_end() -> None:
        if phone_server_loop is not None:
            asyncio.run_coroutine_threadsafe(websocket.close(), phone_server_loop)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except (ValueError, TypeError):
                continue
            if session_router.is_attached(conn_id):
                # Every later frame on an attached connection is the session protocol, whatever its own "type"
                # looks like (plaintext for a local session, {"n","ct"} for a relayed one) — including "command",
                # which would otherwise collide with the unrelated LAN quick-action kind just below.
                await session_router.on_frame(conn_id, data, schedule_send, schedule_end, local=True)
                continue
            kind = data.get("type")
            if kind == "hello":
                # Same handshake relay/server.py answers for a relay-routed session (connectSession in
                # phone_client.html always sends this first, whichever transport device.relayUrl points at —
                # one protocol for both, see phone_session.py's module docstring) — there's no connId to hand
                # back here, unlike the relay's, since this connection already *is* the one the phone attaches on.
                await websocket.send(json.dumps({"type": "hello_ok"}))
            elif kind == "push_subscribe":
                subscription = data.get("subscription") or {}
                if isinstance(subscription, dict) and subscription.get("endpoint"):
                    _on_push_subscribe(subscription)
            elif kind == "push_unsubscribe":
                endpoint = str(data.get("endpoint") or "")
                if endpoint:
                    push_store.remove(endpoint)
            elif kind == "pair":
                if not phone_server.pairing_open():
                    await websocket.send(json.dumps({"type": "pair_error",
                        "message": "No pairing is open right now. Ask Jervis to connect your phone again."}))
                elif (paired := phone_server.try_pair(str(data.get("code", "")), str(data.get("deviceName", "")))) is None:
                    await websocket.send(json.dumps({"type": "pair_error",
                        "message": "That code is wrong or has expired."}))
                else:
                    device_id, token, key = paired
                    name = phone_server.registry.authenticate(device_id, token)["name"]
                    await websocket.send(json.dumps({"type": "paired", "deviceId": device_id, "token": token,
                                                     "key": phone_crypto.key_to_b64(key), "deviceName": name,
                                                     "computerId": relay.computer_id,
                                                     "relayUrl": session_transport_url()}))
                    broadcast("ai", f"{name} is now paired and can talk to me on this network.")
                    clear_ui_update("phone_pairing")
                    send_ui_update_once({"type": "phone_paired", "deviceName": name})   # closes the QR panel
            elif kind == "auth":
                found = phone_server.registry.authenticate(str(data.get("deviceId", "")), str(data.get("token", "")))
                if found is None:
                    device_id = None
                    await websocket.send(json.dumps({"type": "auth_error"}))
                else:
                    device_id = str(data.get("deviceId", ""))
                    await websocket.send(json.dumps({"type": "authed", "deviceName": found["name"]}))
            elif kind == "command":
                command_id = str(data.get("commandId") or "")
                if device_id is None:
                    await websocket.send(json.dumps({"type": "result", "commandId": command_id,
                                                     "status": "FAILED", "message": "Not paired."}))
                elif phone_control_mode() == "off":
                    await websocket.send(json.dumps({"type": "result", "commandId": command_id,
                                                     "status": "FAILED", "message": "Phone control is turned off."}))
                elif not command_id or str(data.get("commandType")) not in PHONE_COMMANDS:
                    await websocket.send(json.dumps({"type": "result", "commandId": command_id,
                                                     "status": "FAILED", "message": "Unknown command."}))
                else:
                    result = await loop.run_in_executor(
                        None, phone_server.run_command, device_id, command_id,
                        str(data.get("commandType")), data.get("payload") or {})
                    await websocket.send(json.dumps({"type": "result", "commandId": command_id, **result}))
            elif kind in ("session_attach", "auto_attach") or ("n" in data and "ct" in data):
                await session_router.on_frame(conn_id, data, schedule_send, schedule_end, local=True)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Phone connection handler crashed: {e!r}", flush=True)
        raise
    finally:
        session_router.forget(conn_id)


async def local_process_request(connection, request):
    """Everything phone_control.serve_static already handles (the page, sw.js, letting a real WebSocket handshake
    through), plus this local server's own /decide — the same endpoint relay/server.py exposes, reached instead of
    the relay's when no relay is configured (session_transport_url() then points a phone straight at this
    computer). GET with a query string, not POST with a body, for the same reason relay/server.py's docstring
    gives: the `websockets` library this reuses can't read a request body at all."""
    if not request.headers.get("Upgrade"):
        path = urllib.parse.urlsplit(request.path)
        if path.path == "/decide":
            remote = getattr(connection, "remote_address", None)
            if not phone_control.is_private_address(remote[0] if remote else ""):
                return connection.respond(403, "Not allowed.")
            query = urllib.parse.parse_qs(path.query)
            session_id = (query.get("sessionId") or [""])[0]
            secret = (query.get("secret") or [""])[0]
            decision = (query.get("decision") or [""])[0]
            if not (session_id and secret and decision in ("confirm", "reject")):
                return connection.respond(400, "Bad request.")
            phone_server.decide_session(session_id, secret, decision == "confirm")
            return connection.respond(200, "OK")
    return phone_control.serve_static(connection, request, active_pair_code=phone_server.current_pairing_code())


def run_phone_server() -> None:
    """LAN-bound (0.0.0.0, not just localhost) on its own port, with its own pairing/auth — see phone_control.py."""
    global phone_server_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    phone_server_loop = loop

    async def main():
        # ping_interval disabled: the main thread does CPU-heavy work (local speech recognition, local AI
        # inference) that can starve this event loop's thread of the GIL for long enough to miss a pong, which
        # would otherwise make the library close an otherwise-healthy connection. Real traffic (a status mirror
        # every listen cycle) already proves it's alive, so the library's own keepalive adds risk without benefit.
        async with websockets.serve(handle_phone_client, "0.0.0.0", PHONE_WS_PORT,
                                    process_request=local_process_request, ping_interval=None,
                                    max_size=phone_session.VOICE_MAX_BYTES + 4096):
            await asyncio.Future()

    try:
        loop.run_until_complete(main())
    except OSError as e:
        print(f"Could not start the phone-control server on port {PHONE_WS_PORT}: {e}", flush=True)


_PHONE_PAIR_COMMAND = re.compile(
    r"\b(?:connect|pair|link)(?:\s+\w+){0,3}\s+my\s+phone\b|\bconnect\s+(?:to|with)\s+my\s+phone\b|"
    r"\blet\s+my\s+phone\s+control\s+(?:this|my)\s+computer\b|"
    r"\bcontrol\s+(?:this|my)\s+computer\s+from\s+my\s+phone\b", re.I)


def is_phone_pair_command(text: str) -> bool:
    return bool(_PHONE_PAIR_COMMAND.search(text or ""))


def start_phone_pairing() -> str:
    """"Connect my phone": straight to a QR code on screen — a fresh pairing code inside this computer's local
    address. Scanning it opens phone_client.html on a Confirmed/Not Confirmed tap (its pairCard); that tap, on the
    phone in hand, is the approval, and Confirmed lands straight in the phone's chat. Works the same for a brand-new
    phone and one paired before (which re-pairs, replacing its old record — see handle_phone_client's "pair").
    Needs the phone on the same Wi-Fi: pairing is local-only on purpose, see phone_control.py's module docstring."""
    if phone_control_mode() == "off":
        return ("Phone control is turned off. Turn on “Let your phone control this computer” in Settings, "
                "Computer control, then ask me again.")
    code = phone_server.begin_pairing()
    address = f"http://{phone_control.lan_address()}:{PHONE_WS_PORT}"
    pair_url = f"{address}/?code={code}"   # the code travels in the link, never typed; the address and code are
    # still shown on the panel in full, as a fallback for a phone that can't scan.
    # send_ui_update, not the "once" version: still there if the window wasn't open the instant this fired, or gets
    # reopened a minute later. Cleared on "paired" (handle_phone_client), so a later window never sees a stale QR.
    send_ui_update("phone_pairing", {"address": address, "pairUrl": pair_url, "code": code,
                                     "expiresAt": time.time() + phone_control.PAIR_CODE_TTL})
    return "Scan the QR code on your screen with your phone, on the same Wi-Fi, and tap Confirmed."


def start_phone_session() -> str:
    """"Connect my phone", once at least one phone is already paired: every paired phone gets a push notification
    with Confirmed/Not Confirmed buttons (see phone_sw.js), opening confirm.html — a small, self-contained page
    that decides the session (phone_server.decide_session) using nothing but the session id and secret already in
    its own link, whether or not this phone has ever synced anything with wherever that page happens to be served
    from. From there, "Open Jervis" optionally goes on to attach a live session with the phone's own device
    credentials (phone_server.attach_session) for voice/commands — that part does still need this phone's data to
    already be on that same origin (see phone_client.html's syncToOtherOrigin), but confirming or rejecting the
    request itself never does. Without a relay configured (Settings, "Relay address"), this still works for a
    phone on this Wi-Fi right now — it attaches directly to the local phone server, the same one PHONE_COMMANDS
    already uses, over local_process_request's /decide (see run_phone_server). A relay is only what extends this
    to work from anywhere else. See phone_control.py's and phone_session.py's module docstrings."""
    session = phone_server.begin_session()
    # Everything confirm.html needs is here — no relayUrl: /decide is always relative to wherever that page itself
    # was served from (locally or by the relay), so the decision never depends on the phone already knowing
    # anything about this computer (see confirm.html and phone_sw.js).
    push_data = {"computerId": relay.computer_id, "sessionId": session.id, "secret": session.secret}
    actions = [{"action": "confirm", "title": "Confirmed"}, {"action": "reject", "title": "Not Confirmed"}]
    sent = push.send_to_all(push_store, "Jervis", "Jervis wants to connect to this computer.",
                            tag="jervis-session", actions=actions, data=push_data)
    if not sent:
        url = notification_setup_url()
        # Same QR panel as first-ever pairing (phonePairingLayer in index.html/panels.js) — no reason to make the
        # user open or type a link by hand when a scan does it instead. send_ui_update (not "once") so it's still
        # there if the window wasn't open the instant this fired, or gets reopened later — see that function's own
        # docstring. Closes and clears itself on phone_notify_enabled, same pattern as pairing's own phone_paired;
        # the timer here is just when the panel gives up waiting, not a real expiry on the link itself (it's a
        # stable address — see notification_setup_url's docstring).
        send_ui_update("phone_pairing", {"address": url, "pairUrl": url, "code": "", "expiresAt": time.time() + 600})
        return ("I couldn't reach a paired phone to ask — I've put a QR code on your screen. Scan it with your "
                "phone once and tap “Enable notifications”. One time only; after that this just works.")

    def run():
        if not session.decided_event.wait(phone_control.SESSION_TTL):
            return   # nobody answered in time; a silent expiry, same as an unanswered pairing code
        if session.state == "approved":
            announcements.put("Your phone is connected.")
        elif session.state == "rejected":
            announcements.put("Connection cancelled.")

    threading.Thread(target=run, daemon=True, name="phone-session").start()
    return "I've sent a connection request to your phone."


def disconnect_phone_session() -> str:
    session_id = phone_server.current_session_id()
    if not session_id:
        return "No phone is connected right now."
    session_router.end_session(session_id)
    return "Disconnected."


def list_paired_phones() -> str:
    devices = phone_server.registry.list()
    if not devices:
        return "No phones are paired."
    names = ", ".join(d["name"] for d in devices)
    return f"{len(devices)} phone{'s' if len(devices) != 1 else ''} paired: {names}."


def forget_paired_phones() -> str:
    removed = phone_server.registry.revoke()
    if not removed:
        return "No phones were paired."
    return f"Forgot {removed} paired phone{'s' if removed != 1 else ''}. They'll need to pair again to reconnect."


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


def weather_card(data: dict) -> dict:
    """The small weather card in the window's left column, from a forecast.get() result."""
    current = data["current"]
    return {"city": data["place"]["name"].split(",")[0], "temp": current["temp"] if current["temp"] is not None else "--",
            "condition": current["label"]}


def weather_loop():
    while True:
        delay = 600
        settings_changed.clear()
        try:
            data = forecast.get(fallback_city=os.getenv("WEATHER_CITY", ""), radar=False)
            send_ui_update("weather", weather_card(data))
        except forecast.WeatherError as e:
            city = os.getenv("WEATHER_CITY", "").strip()
            send_ui_update("weather", {"city": f"Can't find {city}" if city else "No city set", "temp": "--",
                                       "condition": "Choose your city in Settings" if "Settings" in str(e) else "Unavailable"})
            delay = 120
        except Exception as e:
            print(f"Weather fetch failed: {e!r}")
            delay = 30  # retry soon instead of waiting 10 minutes with no data
        settings_changed.wait(timeout=delay)   # a new city in Settings refreshes the panel right away


# ---------- The weather window: "what's the weather?" opens it (see forecast.py for the data, weather/ for the window) ----------
_WEATHER_ASK = re.compile(
    r"\b(?:what'?s|what is|how'?s|how is|check|tell me|show me|show|open|give me|get me|bring up|display)\b.*\bweather\b"
    r"|\bweather\b.*\b(?:like|today|tonight|tomorrow|now|outside|forecast|this week|right now)\b"
    r"|^(?:the )?(?:weather|forecast|weather forecast|weather report)(?: please)?$"
    r"|\b(?:what'?s|what is|show me|show|open|check|give me) (?:the |my )?(?:weather )?forecast\b"
    r"|\bis it (?:raining|snowing|sunny|cloudy|cold|hot|windy)(?: outside| now| right now| today)?$"
    r"|\b(?:temperature|forecast)\b.*\b(?:outside|today|now)\b"
    r"|\bdo i need (?:an umbrella|a jacket|a coat)\b")
_WEATHER_CLOSE = re.compile(r"^(?:(?:please|can you|could you) )*(?:close|hide|dismiss|exit) (?:the |my )?weather"
                            r"(?: (?:window|panel|screen|app|forecast))?$")
_WEATHER_TALK = re.compile(r"^(?:i|we|my|our|he|she|they|it was|the weather (?:was|has been))\b")


def parse_weather_request(text: str):
    """{"action": "show", "city": "" | "Paris"} / {"action": "close"} for a weather request, else None. Talking
    about the weather ("I was talking about the weather yesterday") is not a request."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower().replace("’", "'")).split())
    n = re.sub(r"^(?:(?:hey|ok|okay) )?(?:jervis|jarvis) ", "", n)
    if _WEATHER_CLOSE.match(n):
        return {"action": "close"}
    if _WEATHER_TALK.match(n) or not _WEATHER_ASK.search(n):
        return None
    city = ""
    m = re.search(r"\b(?:weather|forecast|temperature|raining|snowing|sunny|cloudy|cold|hot|windy)\b.*?\b(?:in|for|at) "
                  r"(?P<c>[a-z' ]+?)(?: (?:today|tonight|tomorrow|now|right now|this week|please))*$", n)
    if m and m.group("c") not in ("the moment", "general", "my area", "my city", "here", "outside"):
        city = m.group("c").strip()
    return {"action": "show", "city": city}


def show_weather(city: str = "", refresh: bool = False, speak_reply: bool = True, open_window: bool = True) -> str:
    """Open the weather window (straight away, as a skeleton), fetch, then fill it. Returns what to say.
    open_window=False only updates a window that is already open (its own refresh button)."""
    window = bool(ws_loop and connected_clients)
    if window and open_window:
        send_ui_update_once({"type": "weather_open", "city": city})
    try:
        data = forecast.get(city=city, fallback_city=os.getenv("WEATHER_CITY", ""), refresh=refresh)
    except forecast.WeatherError as e:
        send_ui_update_once({"type": "weather_panel", "error": str(e)})
        return str(e)
    except Exception as e:   # never leave the window spinning
        traceback.print_exc()
        send_ui_update_once({"type": "weather_panel", "error": "Weather data is temporarily unavailable."})
        return f"The weather couldn't be loaded ({type(e).__name__})."
    send_ui_update_once({"type": "weather_panel", "data": data})
    if not city:
        send_ui_update("weather", weather_card(data))   # keep the small card in step with what was just shown
    text = forecast.summary(data)
    if window and speak_reply:
        text += " The full forecast is on your screen."
    return text


_CLOCK_TIME = re.compile(r"^(?:hey |ok |okay )?(?:jervis[, ]+)?(?:(?:can you |could you )?(?:please )?tell me )?"
                         r"(?:what(?:'s| is) the (?:current )?time(?: (?:now|right now|please))?|what time is it"
                         r"(?: (?:now|right now|please))?|(?:the )?time(?: please| now)?|current time)\??$", re.I)
_CLOCK_DATE = re.compile(r"^(?:hey |ok |okay )?(?:jervis[, ]+)?(?:(?:can you |could you )?(?:please )?tell me )?"
                         r"(?:what(?:'s| is) (?:the date|today'?s date|the date today)|what date is (?:it|today)"
                         r"(?: today)?|what day is (?:it|today)(?: today)?|which day is (?:it|today)|"
                         r"what(?:'s| is) today)\??$", re.I)
_CLOCK_TIME_HE = re.compile(r"^(?:מה|כמה) השעה(?: עכשיו)?\??$")
_CLOCK_DATE_HE = re.compile(r"^(?:איזה יום (?:היום|זה היום)|מה התאריך(?: היום)?|איזה תאריך היום)\??$")


def handle_clock_question(text: str):
    """"What time is it?" / "What's the date?": this computer's own clock answers, instantly. (The chat model has no
    clock: asked, it said it couldn't check the time.)"""
    said = " ".join((text or "").strip().rstrip(".!").split())
    now = datetime.now()
    clock = now.strftime("%H:%M")
    day = f"{now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}"
    if _CLOCK_TIME.match(said):
        return f"It's {clock}."
    if _CLOCK_DATE.match(said):
        return f"Today is {day}."
    if _CLOCK_TIME_HE.match(said):
        return f"השעה {clock}."
    if _CLOCK_DATE_HE.match(said):
        return f"היום {now.day}.{now.month}.{now.year}."
    return None


def handle_weather_command(text: str):
    request = parse_weather_request(text)
    if request is None:
        return None
    if request["action"] == "close":
        send_ui_update_once({"type": "close_weather"})
        return "Okay, I closed the weather." if ws_loop and connected_clients else "The weather window isn't open."
    return show_weather(request["city"])


def refresh_weather_window(city: str = "", refresh: bool = True) -> None:
    """The window's own refresh button (or a click on the weather card): fetch again, without saying anything."""
    threading.Thread(target=show_weather, kwargs={"city": city, "refresh": refresh, "speak_reply": False,
                                                  "open_window": False},
                     daemon=True, name="weather-refresh").start()


def tool_get_weather(city: str = "", **_ignored) -> str:
    """The get_weather tool (the AI's way in, for weather questions the direct command didn't catch)."""
    return show_weather(str(city or "").strip())


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
    """"Play on Spotify, Echoes by Pink Floyd, minute two" -> ("Echoes Pink Floyd", 120), typed exactly as said."""
    seconds, n = timeparse.strip_start_time(text)
    if not re.search(r"\bspotify\b", n, re.I):
        return None
    m = re.match(
        r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
        r"(?:play|put on|start|listen to|open)\s+(.+)$", n, re.I)
    if not m:
        return None
    query = re.sub(r"\b(?:(?:on|in|with|using|from)\s+)?spotify\b", " ", m.group(1), flags=re.I)
    # (what it says stays: "by Pink Floyd" names the artist, "playlist" what kind — spotify_match reads them)
    query = " ".join(query.split()).strip(" ,.")
    return (query, seconds) if query and spotify_match.parse(query)["text"] else None


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
    if re.search(r"\bsee you\b|\bin the next\b|\bthe next (?:one|video) (?:is|will|we)\b", n):
        return None   # a video's own outro picked up by the microphone, not a request
    if re.search(r"\b(previous|prior|last|back)\b.{0,20}\b(song|track|one|music)\b|\bgo back\b(?!\s+to\b)|"
                 r"\bsong before\b|\bplay (?:the )?(?:previous|last) (?:song|track|one)\b|\bprevious\b", n):
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


# A sentence that describes something ("my WhatsApp is full of...", "I was on WhatsApp all day") rather than asks for
# something. Only used when there's no request word in it, so "is there anything new on WhatsApp" still counts.
_WA_STATEMENT = re.compile(r"^(?:i|my|our|his|her|their|the|whats ?app)\b.*?\b(?:is|was|were|are|keeps?|kept|got|gets|"
                           r"has been|have been|had|used to|am)\b")
_WA_REQUEST_CUE = re.compile(r"\b(?:read|check|show|tell me|open|any|anything|unread|new|missed|what did|what does|"
                             r"what has|did|who)\b")


def parse_whatsapp_request(text: str):
    """Returns {"action": "check" | "read_unread" | "read_chat" | "send", "name": str} or None."""
    n = " ".join(re.sub(r"[^\w' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    mentioned = bool(_WA.search(n))
    if mentioned and _WA_STATEMENT.search(n) and not _WA_REQUEST_CUE.search(n):
        return None   # talking about WhatsApp ("my WhatsApp is full of messages from school") is not asking to read it
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
_BROWSERS = {"chrome", "google chrome", "browser", "the browser", "my browser", "edge", "microsoft edge", "firefox",
             "brave", "the internet", "internet"}
_COMPOUND = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis) )?(?:(?:please|can you|could you|i want to|i wanna|let's|lets) )*"
    r"(?:open|launch|start)\s+(?:up\s+)?(?:the\s+)?(.+?)(?:\s+(?:app|application))?\s+(?:and\s+then|and|then)\s+"
    r"((?:play|watch|put on|write|type|draft|compose|search|find|set|remind|pause|stop|resume|go|skip|jump|turn|make|create|show|listen|"
    r"build|construct|model|design|place|sculpt|add|put)\b.*)$")


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
    if documents.detect_request(text) or documents.is_transfer_request(text):
        return None   # "open Notepad and write a story": the document handlers write it, not just open the app
    parts = split_open_and_do(text)
    if not parts:
        return None
    target, action = parts
    search = re.match(r"(?:search|look up|look for|find)(?: (?:for|up))? (.+)$", action)
    if search and (target in _BROWSERS or target == "google") and not web_search.parse_request(action):
        return run_web_search("google", search.group(1), context=text)   # the search opens the browser itself
    service = _SERVICE_WORDS.get(target)
    mentions_service = re.search(r"\b(netflix|stremio|youtube|spotify)\b", action)
    if service and not mentions_service:
        if service == "spotify" and not re.match(r"(?:play|put on|listen|start)\b", action):
            service = None  # e.g. "open Spotify and pause": open it first, then run the command
        else:
            action = f"{action} on {service}"  # playing there opens the app or site by itself
            result = handle_direct_command(action)
            return result or f"I couldn't work out '{action}'."
    status, value = resolve_app(target)
    if status == "ok" and "blender" in value.lower():
        # "Open Blender and build a house": open it with its bridge; the build waits for it, then runs the agent.
        open_blender_in_background()
        result = handle_direct_command(action)
        return f"Opening {value}. {result}" if result else f"Opening {value}."
    opened = open_application(target)
    remember_media_app(target)
    result = handle_direct_command(action)
    return f"{opened} {result}" if result else f"{opened} I didn't catch what to do next."


# ---------- several things in one message: "solve x^2 + 3x - 4 = 0 and draw the function" ----------
chat_history = None   # the conversation the main loop keeps, so a part that isn't a direct command can still ask the AI
_multi_active = False
_TASK_START = (r"(?:draw|drew|graph|plot|sketch|paint|solve|find|calculate|compute|factor|expand|simplify|open|close|play|pause|stop|resume|skip|set|start|"
               r"cancel|remind|write|read|check|tell|show|what|what's|whats|how|who|where|when|why|search|google|turn|mute|unmute|send|make|create|give|"
               r"explain|list|translate|convert|remember|call|text|schedule|add|remove|delete|type|launch|switch|go|save|put|bring|take|"
               r"build|construct|model|design|place|in blender|improve|refine|polish|enhance|plant|grow|scatter|"
               r"color|colour|rotate|move|scale|resize|duplicate|undo|export|render)")
_TASK_SPLIT = re.compile(
    rf"(?:\s*[.;!?]+\s+(?:(?:and|then|also)\s+(?:then\s+|also\s+)?)?|\s*,\s*(?:and\s+)?(?:then\s+|also\s+)?|\s+(?:and\s+then|and\s+also|and|then|also|after\s+that|afterwards|plus)\s+)(?=(?i:{_TASK_START})\b)",
    re.I)


def split_tasks(text: str) -> list:
    """The separate things asked for in one message (each starts with an action or a question), or the whole text as one."""
    parts = [p.strip(" ,.;") for p in _TASK_SPLIT.split((text or "").strip())]
    return [p for p in parts if p] or [text]


_OPEN_BLENDER = re.compile(r"^(?:please |now |then |first )*(?:open|launch|start|run)\s+(?:up\s+)?blender(?:\s+\d[\d.]*)?"
                           r"[.!]?$", re.I)
_IN_BLENDER = re.compile(r"\s*,?\s*\b(?:in|inside|with|using) blender\b", re.I)


def blender_sequence(text: str, parts: list):
    """The parts of a several-step Blender request, in order (without "open Blender", which the task does anyway),
    or None when this isn't one. Blender is named, or was just being worked in, and the parts are things to build,
    change or save there."""
    if len(parts) < 2:
        return None
    named = bool(re.search(r"\bblender\b", text or "", re.I))
    if not named and time.time() - blender_last_used > BLENDER_RECENT_SECONDS:
        return None
    steps = [_IN_BLENDER.sub("", p).strip(" ,.") for p in parts if not _OPEN_BLENDER.match(p.strip(" ,."))]
    steps = [p for p in steps if p]
    blenderish = [p for p in steps if blender_commands.is_command(p) or _BUILD_REQUEST.match(p)
                  or agent_blender.save_request(p)[1] is not None or re.match(r"^(?:and\s+|then\s+)*save\b", p, re.I)
                  or re.match(r"^(?:improve|refine|polish|enhance|fix)\b", p, re.I)]
    if len(steps) < 2 or len(blenderish) < len(steps):
        return None   # something in it isn't Blender work ("... and play some music"): the usual paths
    return steps


def handle_multi_task(text: str):
    """Do each task in order and answer them together. Returns None unless the message really holds several tasks and at least
    one of them is a command Jervis can do himself (otherwise the AI answers the whole message at once)."""
    global _multi_active
    if _multi_active or pending_confirmation or pending_dictation:
        return None
    if _CONTROL_EXPLICIT.match(text or "") or _CONTROL_PREAMBLE.match(text or ""):
        goal = parse_computer_task(text) or ""
        if not re.search(r"\bblender\b", goal, re.I):
            return None   # "take control of my computer and open Notepad": the "and" joins the request to its goal
        text = goal   # "take control, open Blender, then make the cube bigger": each part on its own, in order
    parts = [p for p in split_tasks(text) if not _CONTROL_BARE.match(p)]   # "take on my computer, then …"
    sequence = blender_sequence(text, parts)
    if sequence:
        # "Open Blender, create an island, add trees, improve the water, and save it": the parts build on each
        # other, so they run one after another, each checked, in ONE task (agent_core.SequenceTask) — answering
        # them here one by one started each before the last had finished, and saved an empty scene.
        return start_computer_task(text, blender=True, sequence=sequence)
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


class _SettingUp:
    """Stands in for computer_task while a goal is still being set up (resolving which app, launching Blender,
    deciding whether to ask about its bridge...) — all of which can take a while, during which control_active()
    must already read as busy, or a second command said in that window could start a second, colliding task."""
    state = "starting"

    def stop(self): pass
    def pause(self): pass
    def resume(self): pass


# ---------- Computer control: Jervis using the mouse and keyboard (see computer_use.py) ----------
computer_task = None            # the ComputerTask (or ScriptedTask/AgentTask) currently mid-run, if any
agent_memory_store = agent_memory.Memory()   # requests the agent fully verified before: examples for similar ones
control_session = None          # the persistent computer_use.ControlSession, once "take control" has been granted
_control_questions = {}         # question id -> (threading.Event, {"answer": bool | None})
pending_control_question = None  # {"id", "at"}: the next "yes"/"no" said answers it

# The wake name as speech recognition actually hears it: "Jervis", "Jarvis", or a mangled "Jargvie," before a comma.
_WAKE_NAME = r"(?:(?:hey |ok |okay )?(?:(?:jervis|jarvis)[, ]+|j[a-z]{3,8}, ?))?"
_TAKE_CONTROL = (r"(?:use|control|take control(?: (?:of|over|on))?|(?:stay|be|keep|remain) in control(?: (?:of|over|on))?"
                 r"|take (?:over|on)(?: all(?: of)?)?)")
_CONTROL_EXPLICIT = re.compile(
    r"^" + _WAKE_NAME + r"(?:please |can you |could you |would you |go ahead and )*"
    + _TAKE_CONTROL + r" (?:my |the )?(?:computer|mouse|screen|pc|mac|laptop)"
    r"(?:,? (?:and|to|then))? (?P<goal>.+)$", re.I)
# The same phrase with nothing after it ("Take control of my computer."): opens a persistent session with no goal
# yet, instead of matching nothing the way it does today.
_CONTROL_BARE = re.compile(
    r"^" + _WAKE_NAME + r"(?:please |can you |could you |would you |go ahead and )*"
    + _TAKE_CONTROL + r" (?:my |the )?(?:computer|mouse|screen|pc|mac|laptop)"
    r"[.!?]*$", re.I)
# One on-screen step said plainly ("click Save", "scroll down", "type hello into the search box"). Only phrasings
# that can't be ordinary conversation: "tap water", "type 2 diabetes in children", "check the box office" don't match.
_UI_NOUN = r"(?:box|field|bar|search|input|form|chat|message|document|window|tab|terminal|editor|cell|text ?box)"
_CONTROL_STEP = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis)[, ]+)?(?:please |can you |could you |would you |go ahead and )*"
    r"(?P<goal>(?:(?:in|on) (?:the )?[\w .'-]{2,40}?,? )?(?:(?:double[- ]?|right[- ]?)?click (?:on )?|tap on )\S.*"
    r"|scroll (?:up|down|to the (?:top|bottom|end))\b.*"
    r"|press (?:the )?(?:[\w-]+ )?(?:button|key|enter|return|escape|esc|tab|space ?bar|backspace)\b.*"
    r"|(?:tick|untick|uncheck) (?:the )?.+"
    r"|check (?:the )?[\w '-]{1,40}(?:checkbox|check box|tick box)\b.*"
    r"|(?:type|enter|write|fill in) .+ (?:in|into) (?:the )?(?:[\w'-]+ ){0,3}" + _UI_NOUN + r"\b.*"
    r"|(?:go to|switch to) the (?:next|previous|first|second|third|last) (?:tab|window)\b.*)$", re.I)
# Looser: allows the AI's use_computer tool only when the request is plainly about operating something on screen.
_COMPUTER_HINT = re.compile(
    r"\b(?:click|double[- ]click|right[- ]click|tap on|scroll|press (?:the|enter|tab|escape)|type (?:it|this|that|in|into)"
    r"|fill (?:in|out)|tick|untick|check ?box|drag|on (?:my|the) screen|use (?:my|the) (?:computer|mouse|keyboard|pc|mac)"
    r"|(?:take )?control(?: (?:of|over|on))? (?:my|the) (?:computer|mouse|pc|mac)|in (?:the )?settings|toggle|"
    r"turn (?:on|off) (?:the )?[\w ]{1,30} (?:in|on))\b",
    re.I)
_CONTROL_STOP = re.compile(r"(?:stop|stop it|stop now|stop that|cancel|abort|enough|that's enough|take over|"
                           r"i'll take over|let me do it|stop using (?:my |the )?(?:computer|mouse)|"
                           r"stop controlling (?:my |the )?(?:computer|mouse)|stop computer control|"
                           r"release control|give me (?:back )?control|exit computer control)")
_CONTROL_PAUSE = re.compile(r"(?:pause|wait|hold on|hang on|one (?:second|moment|sec))")
_CONTROL_RESUME = re.compile(r"(?:continue|resume|go on|go ahead|carry on|keep going|you can continue)")
# Once a session is active, free text that doesn't match a more specific command (open app, search, etc.) is routed
# to it as the next goal — but a plain question shouldn't be hijacked as something to click on screen.
_SESSION_ACTION_VERB = re.compile(
    r"\b(open|create|make|add|click|type|press|scroll|save|duplicate|move|delete|remove|close|switch|arrange|put|"
    r"build|draw|set|change|turn|select|rotate|scale|resize|rename|group|render|export|undo|redo|go to|go back|"
    r"bring|colou?r|paint|spin)\b", re.I)
_SESSION_QUESTION = re.compile(
    # "do"/"does"/"is"/"are" only count as a question starter before a subject ("do you", "is it true") — not before
    # an object pronoun ("do that again", "do it"), which is an imperative repeat command, not a question.
    r"^(?:what|why|how|when|who|where|which|can you tell me|tell me about|"
    r"(?:is|are|do|does)\s+(?:you|we|i|it|there|this|that)\b(?!\s+again\b))\b", re.I)
_YES = re.compile(r"(?:yes|yeah|yep|sure|ok|okay|go ahead|do it|allow|allowed|fine|please do|yes please)")


def bare_answer(text: str):
    """True for a bare yes ("yes", "ok", "כן"), False for a bare no, None for anything that says more — a follow-up
    that asked for a song or a search never takes "yes" as the song or the search."""
    n = " ".join(re.sub(r"[^a-z\u05d0-\u05ea' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    n = re.sub(r"^(?:(?:hey|ok|okay) )?(?:jervis|jarvis) ", "", n)
    n = re.sub(r"\s+(?:thanks|thank you|please|jervis|jarvis)$", "", n)
    if _YES.fullmatch(n) or n in ("כן", "בטח", "סבבה", "אוקיי", "יאללה", "כן בבקשה", "תעשה את זה"):
        return True
    if _NO.fullmatch(n) or n in ("לא", "לא תודה", "בטל", "עזוב"):
        return False
    return None
_NO = re.compile(r"(?:no|nope|don't|do not|don't do it|cancel|stop|not now|never mind|nevermind)")


def parse_computer_task(text: str):
    """The goal, if this asks Jervis to use the computer (and no other command handled it already)."""
    n = " ".join(re.sub(r"[^\w'+ ,.-]", " ", (text or "").replace("\u2019", "'")).split())   # keeps "TextEdit" as said
    match = _CONTROL_EXPLICIT.match(n) or _CONTROL_STEP.match(n)
    if not match:
        preamble = _CONTROL_PREAMBLE.match(n)
        goal = n[preamble.end():].strip(" ,.") if preamble else ""
        return goal if len(goal) > 3 else None
    goal = (match.groupdict().get("goal") or n).strip(" ,.")
    return goal if len(goal) > 3 else None


def is_computer_request(text: str) -> bool:
    return bool(_COMPUTER_HINT.search(text or ""))


def tool_use_computer(goal: str = "", **_ignored) -> str:
    goal = " ".join(str(goal or "").split())[:300]
    if not goal:
        return "No task given."
    # "stay in control on my computer" is permission, not a task: a free-form task with no action in it just
    # makes the small local AI click and type at random. Open a session that waits for the next command instead.
    if _CONTROL_BARE.match(goal) or not (_SESSION_ACTION_VERB.search(goal) or _CONTROL_STEP.match(goal)):
        return start_computer_task("", persistent=True)
    return start_computer_task(goal)


def computer_environment():
    if osal.IS_WIN:
        import screen_windows
        return screen_windows.WindowsScreen()
    if osal.IS_MAC:
        import screen_mac
        return screen_mac.MacScreen()
    return computer_use.Environment()   # available() explains it isn't supported here


LOCAL_CONTROL_STEPS = 20   # plain GUI clicking with the local agent model (a 7B when installed): unproductive clicks
                           # compound, and aren't individually verified the way agent (Blender) steps are.
# Blender work is different: most of it goes through blender_commands.py's deterministic, verified one-shot
# actions, which never touch this budget at all (see ScriptedTask). This ceiling only matters for the minority of
# requests that genuinely need BlenderComputerTask's free-form multi-step reasoning ("build a simple house"), where
# a persistent session must not get cut off arbitrarily early — see the user's "no 12-step cutoff" requirement.
BLENDER_LOCAL_STEPS = 40
BLENDER_ONLINE_STEPS = 60


def local_llm_only() -> bool:
    """Whether answers come only from the small local model (no online AI to fall back on)."""
    return LLM_BACKEND == "ollama" or (LLM_BACKEND == "auto" and time.time() < groq_down_until)


def _ask_ai_for_control(messages, tools):
    try:
        return groq_chat(model=GROQ_MODEL, messages=messages, tools=tools, tool_choice="required", role="agent")
    except Exception as e:
        log_ai_error(e)
        raise computer_use.AIError(groq_error_reply(e)) from e


def open_control_question(question: str) -> str:
    """Show a yes/no question in the window and listen for "yes"/"no". Returns its id for wait_control_answer.
    Also shown in a connected phone's chat, where typing "yes"/"no" answers it the same way."""
    global pending_control_question
    question = localized(question)
    ask_id = f"q{int(time.time() * 1000)}"
    _control_questions[ask_id] = (threading.Event(), {"answer": None})
    pending_control_question = {"id": ask_id, "at": time.time()}
    send_ui_update_once({"type": "control_confirm", "id": ask_id, "question": question})
    mirror_to_phone({"type": "chat", "sender": "ai", "text": f"{question} {language.phrase('(yes / no)')}"})
    return ask_id


def ask_control_question(question: str, timeout: float = 90.0) -> bool:
    """Ask the user (in the window and aloud) and wait for yes or no. No answer means no."""
    question = localized(question)
    ask_id = open_control_question(question)
    announcements.put(f"{question} {language.phrase('Say yes or no.')}")
    return wait_control_answer(ask_id, timeout)


def wait_control_answer(ask_id: str, timeout: float = 90.0) -> bool:
    global pending_control_question
    answered, holder = _control_questions[ask_id]
    answered.wait(timeout)
    _control_questions.pop(ask_id, None)
    if pending_control_question and pending_control_question["id"] == ask_id:
        pending_control_question = None
    send_ui_update_once({"type": "control_confirm_done", "id": ask_id})
    return holder["answer"] is True


def answer_control_question(ask_id: str, allow: bool) -> bool:
    entry = _control_questions.get(ask_id)
    if not entry:
        return False
    entry[1]["answer"] = bool(allow)
    entry[0].set()
    return True


def _report_control(state: dict) -> None:
    send_ui_update_once({"type": "control", "data": state})


def control_active() -> bool:
    return computer_task is not None and computer_task.state not in ("completed", "stopped", "error")


def session_active() -> bool:
    """A persistent "take control" session is open — it survives past any one goal; see start_computer_task."""
    return control_session is not None


def end_control_session(final_state: str = "stopped", detail: str = "Stopped. You have control again.") -> None:
    global control_session
    control_session = None
    _report_control({"state": final_state, "detail": detail, "goal": "", "step": 0, "maxSteps": 0})


def _is_explicit_control_phrase(text: str) -> bool:
    """Whether `text` itself asked to take control (vs. being a bare on-screen step like "click Save"), which is
    what makes the session this starts persist past the one goal — see start_computer_task's `persistent`."""
    n = " ".join(re.sub(r"[^\w'+ ,.-]", " ", (text or "").replace("’", "'")).split())
    return bool(_CONTROL_EXPLICIT.match(n) or _CONTROL_PREAMBLE.match(n))


def looks_like_session_goal(text: str) -> bool:
    """Whether something said while a control session is open is the next on-screen command. Only an actual
    instruction counts: background speech ("that's a hot deal", "see you in the next video") and plain questions
    must never become a task that clicks around and keeps everything else waiting."""
    t = text or ""
    if _SESSION_QUESTION.match(t) and not _SESSION_ACTION_VERB.search(t):
        return False
    return bool(_SESSION_ACTION_VERB.search(t) or _CONTROL_STEP.match(" ".join(t.split())))


def _make_room_for_new_task() -> bool:
    """A new command replaces whatever task is still running (usually one the small local AI got stuck on), rather
    than being told "Still working on that" for minutes. False only if it can't be stopped right now."""
    task = computer_task
    if task is None or task.state in ("completed", "stopped", "error"):
        return True
    if isinstance(task, _SettingUp):
        return False
    task.stop()
    deadline = time.time() + 8
    while task.state not in ("completed", "stopped", "error") and time.time() < deadline:
        time.sleep(0.05)
    return task.state in ("completed", "stopped", "error")


def scripted_steps_for(goal: str):
    """Steps for a take-control goal that is one plain command ("open Notepad", "search Google for cats", "close
    Discord"), so it runs exactly, visibly, step by step, instead of the AI working out clicks. None otherwise."""
    search = web_search.parse_request(goal)
    if search:
        engine, query = search
        where = "YouTube" if engine == "youtube" else "Google"
        return [(f"Searching {where} for {query}", lambda: run_web_search(engine, query, context=goal))]
    scroll = re.fullmatch(r"scroll (up|down|to the top|to the bottom|to the end)(?: (?:a bit|a little|more|again|"
                          r"please|for me|on the page|the page))*", " ".join(re.sub(r"[^a-z ]", " ", goal.lower()).split()))
    if scroll:
        direction = scroll.group(1)
        notches = {"up": 5, "down": -5, "to the top": 40}.get(direction, -40)
        word = "up" if notches > 0 else "down"

        def scroll_step():
            env = computer_environment()
            env.observe()                     # finds the window being worked in (never Jervis's own)
            problem = env.scroll(notches)
            return problem or f"Scrolled {word}."
        return [(f"Scrolling {word}", scroll_step)]
    close_target = app_launcher.parse_close_request(goal)
    if close_target and not app_launcher.means_this_app(close_target):
        return [(f"Closing {close_target}", lambda: app_launcher.close_application(close_target)
                 or f"I couldn't find an open app called {close_target}.")]
    name = parse_open_request(goal)
    if name and not app_launcher.means_this_app(name):
        status, value = resolve_app(name)
        if status == "ok" or (status == "missing" and _site_for(name)):
            shown = value if status == "ok" else name
            # A slow app (Blender, games) can take a while to show its window: wait for it, then say it's open.
            return [(f"Opening {shown}", lambda: open_application(name, confirm_seconds=CONTROL_LAUNCH_SECONDS))]
    return None


CONTROL_LAUNCH_SECONDS = 60

_ONE_CLICK = re.compile(r"^(?:(?:in|on) (?:the )?[\w .'-]{2,40}?,? )?(?:double[- ]?click|right[- ]?click|click|tap on|tick|"
                        r"untick|uncheck|check|select|choose|press (?:the )?[\w '-]{1,40}(?:button|tab|link|icon))\b")
_ONE_PRESS = re.compile(r"^press (?:the )?(?:[\w-]+ )?(?:key|enter|return|escape|esc|tab|space ?bar|backspace)\b")
_ONE_TYPE = re.compile(r"^(?:type|enter|write|fill in) .+ (?:in|into) ")


def finishing_actions(goal: str):
    """For a goal that is one action ("click the Edit menu", "press Enter", "type hello into the search box"), the
    action kinds that complete it; None for anything longer (then the AI says when it's done)."""
    g = " ".join((goal or "").lower().split())
    if re.search(r"\b(?:and|then|after that)\b", g):
        return None   # several steps
    if _ONE_CLICK.match(g):
        return {"click", "double_click", "right_click", "click_on"}
    if _ONE_PRESS.match(g):
        return {"press_keys"}
    if _ONE_TYPE.match(g):
        return {"type_text"}
    return None


def _which_app_first(goal: str):
    """"Take control … and open Blender" with Blender 4.3 and 4.5 installed: the names to choose from, asked before
    the permission question (so the answer can't get lost inside a running task). None when the goal is clear."""
    name = parse_open_request(goal)
    if not name or app_launcher.means_this_app(name):
        return None
    status, value = resolve_app(name)
    return value[:4] if status == "ambiguous" else None


def start_computer_task(goal: str, scripted=None, after=None, persistent: bool = False, blender: bool = False,
                        agent_adapter=None, sequence=None) -> str:
    """Use the mouse and keyboard for `goal`: worked out step by step by the AI, or, with `scripted`, a list of
    known steps (see computer_use.ScriptedTask). Either way: asked first (Settings), shown, and stoppable.

    `persistent`: whether granting this keeps a computer_use.ControlSession open afterward, so later goals ("create
    a chair" -> "make it wooden") don't need "take control" said again and don't re-ask permission. True only for
    goals that themselves said "take control…" (see handle_direct_command); a bare one-off like "click Save" stays
    exactly as one-shot as it is today. Once a session is already open, permission is skipped regardless of this
    flag — whatever is already granted covers anything said next."""
    global computer_task, control_session
    mode = (os.getenv("JERVIS_COMPUTER_CONTROL") or "ask").strip().lower()
    # Off means no mouse and keyboard. Building in Blender through its scripting bridge uses neither, so it stays on.
    if mode == "off" and not (blender and not scripted and goal.strip()):
        return "Using the mouse and keyboard is turned off. You can allow it in Settings, under Computer control."
    if not _make_room_for_new_task():
        return "Still working on that — one moment."
    env = computer_environment()
    ok, why = env.available()
    if not ok:
        return why

    global pending_app_choice
    wanted = None if scripted else parse_open_request(goal)
    if wanted and resolve_app(wanted)[0] == "missing" and app_launcher.broken_app(wanted):
        return open_application(wanted)   # says the shortcut is left over from an uninstall; nothing to take control for
    options = None if scripted else _which_app_first(goal)
    if options:
        pending_app_choice = {"options": options, "at": time.time(), "control": True, "persistent": persistent}
        return f"Which one should I open: {', '.join(options[:-1])} or {options[-1]}?"

    already_active = session_active()
    session = control_session if already_active else computer_use.ControlSession(env)
    keep_session = persistent or already_active
    bare = not goal.strip() and not scripted

    # "open Blender" launched with the scripting bridge from the start, so a follow-up goal ("create a chair")
    # doesn't have to restart it and ask first (see blender_control.ensure_bridge).
    blender_open = None
    if not bare and not scripted and not sequence:   # (a sequence opens Blender itself, if it isn't open)
        opening = parse_open_request(goal)
        if opening and not app_launcher.means_this_app(opening):
            status, value = resolve_app(opening)
            if status == "ok" and "blender" in value.lower():
                blender_open = value

    question = "Can I use your mouse and keyboard?" if bare else f"Can I use your mouse and keyboard to {goal}?"
    # Blender work through its scripting bridge never touches the mouse or keyboard: nothing to ask permission for.
    code_only = blender and not bare and (blender_launching() or blender_control.BlenderBridge().ping(timeout=1.5))
    ask_id = open_control_question(question) if (mode != "on" and not already_active and not code_only) else None

    def report(state: dict) -> None:
        # Between goals in a persistent session, "completed"/"error" would read (and look, in the overlay) as
        # control having ended; "listening" keeps it visibly active while saying the same thing.
        if keep_session and state.get("state") in ("completed", "error"):
            state = {**state, "state": "listening"}
        _report_control(state)

    def run():
        global computer_task, control_session
        if ask_id and not wait_control_answer(ask_id):
            return
        if keep_session:
            control_session = session
        if bare:
            report({"state": "listening", "detail": "Listening for your next command…", "goal": "", "step": 0,
                   "maxSteps": 0})
            return
        # Busy from here on, even before there's a real task object — resolving the goal, launching Blender and
        # deciding whether to ask about its bridge can all take a while, and control_active() must say so
        # throughout, or a command said in that window could start a second, colliding task (see _SettingUp).
        computer_task = _SettingUp()
        # Anything below can legitimately fail (a slow/missing Blender, a Windows file-sharing hiccup, a platform
        # quirk) — none of that may crash this thread silently and strand the session: catch everything, report
        # it in plain words, and keep listening. See the user's own "don't lose control because of errors" ask.
        stopped = False
        try:
            import screen_vision
            vision = screen_vision.ScreenVision() if screen_vision.available() else None
            # The small local model manages simple, short tasks; long ones need the online AI (see local_llm_only).
            steps = LOCAL_CONTROL_STEPS if local_llm_only() else computer_use.MAX_STEPS
            blender_steps = BLENDER_LOCAL_STEPS if local_llm_only() else BLENDER_ONLINE_STEPS
            task_scripted = scripted
            if blender_open and not task_scripted:
                def _open_blender_with_bridge():
                    bridge = blender_control.launch_with_bridge()
                    if bridge:
                        session.blender = bridge
                        return f"Opened {blender_open}."
                    return open_application(blender_open, confirm_seconds=CONTROL_LAUNCH_SECONDS)
                task_scripted = [(f"Opening {blender_open}", _open_blender_with_bridge)]
            task_scripted = task_scripted or scripted_steps_for(goal)
            # `session.blender is not None` (not just live window-focus) matters here: a notification popup from
            # some other app (Discord, chat, email) can steal the foreground for an instant, and a short ambiguous
            # command ("move it right") said right then must still mean Blender, not whatever briefly grabbed focus.
            blender_context = (blender or bool(re.search(r"\bblender\b", goal, re.I)) or session.blender_in_front()
                               or session.blender is not None)

            task = None
            if agent_adapter is not None:
                # An app with its own agent adapter (Minecraft...): plan -> act -> verify -> repair, agent_core.py.
                task = agent_core.AgentTask(goal, agent_adapter(), report=report, confirm=ask_control_question,
                                            history=session.history, memory=agent_memory_store)
            elif task_scripted:
                task = computer_use.ScriptedTask(goal, task_scripted, report=report, cursor=spotify_local.cursor)
            elif blender_context:
                launching = blender_launch
                if launching is not None and launching.is_alive():
                    report({"state": "starting", "detail": "Waiting for Blender to open…", "goal": goal, "step": 0,
                            "maxSteps": 0})
                    launching.join(blender_control.LAUNCH_SECONDS)   # never start a second Blender meanwhile
                bridge = blender_control.ensure_bridge(session, confirm=ask_control_question)
                if not bridge and mode == "off":   # clicking is what's turned off: don't fall back to it
                    result = ("I can't reach Blender's scripting bridge, and using the mouse and keyboard is turned "
                              "off, so I didn't do anything. Is Blender open?")
                    computer_task = None
                    report({"state": "error", "detail": result, "goal": goal, "step": 0, "maxSteps": 0})
                elif not bridge:   # Blender unreachable, or the user declined restarting it: fall back to plain clicking
                    task = computer_use.ComputerTask(goal, env, _ask_ai_for_control, report=report,
                                                     confirm=ask_control_question, vision=vision, max_steps=steps,
                                                     finish_after=finishing_actions(goal))
                elif sequence and local_llm.role_model("agent"):
                    # Several parts, in order, each planned, done and checked before the next (agent_core.SequenceTask).
                    task = agent_core.SequenceTask(goal, sequence, agent_blender.BlenderAdapter(bridge, session),
                                                   report=report, confirm=ask_control_question,
                                                   history=session.history, memory=agent_memory_store)
                else:
                    deterministic = blender_commands.steps_for(goal, session, bridge)
                    if deterministic:
                        # The common case: a known, verified bpy snippet — no model call, nothing to invent.
                        task = computer_use.ScriptedTask(goal, deterministic, report=report,
                                                         cursor=spotify_local.cursor)
                    elif not blender_commands.looks_concrete(goal) and not wants_picture_rebuilt(goal):
                        # Never hand a vague/incomplete remark to the AI to interpret — ask instead.
                        result = blender_commands.clarification_for(goal)
                        computer_task = None
                        report({"state": "listening", "detail": result, "goal": "", "step": 0, "maxSteps": 0})
                    elif local_llm.role_model("agent"):
                        # Plan -> build with the kit -> verify against the real scene -> repair (agent_core.py).
                        task = agent_core.AgentTask(goal, agent_blender.BlenderAdapter(bridge, session),
                                                    report=report, confirm=ask_control_question,
                                                    history=session.history, memory=agent_memory_store)
                    else:   # no local model yet (only the online AI): the older step-by-step Blender loop
                        task = computer_use.BlenderComputerTask(goal, env, _ask_ai_for_control, bridge,
                                                                session=session, report=report,
                                                                confirm=ask_control_question, vision=vision,
                                                                max_steps=blender_steps,
                                                                finish_after=finishing_actions(goal))
            else:
                task = computer_use.ComputerTask(goal, env, _ask_ai_for_control, report=report,
                                                 confirm=ask_control_question, vision=vision, max_steps=steps,
                                                 finish_after=finishing_actions(goal))

            if task is not None:
                computer_task = task
                task._report("starting", "Getting out of your way…")   # the window steps aside (see main.js)
                if connected_clients:
                    time.sleep(1.2)
                result = task.run()
                stopped = task.state == "stopped"
                if task.state == "completed" and after:
                    after()
                if task.state == "error" and local_llm_only() and not task_scripted:
                    result += " My local AI is small, so short, one-step requests work best: try it one step at a time."
                if keep_session:
                    # A step-limit/stuck message says "stopped... you have control again", which is misleading for
                    # a persistent session: control hasn't ended, only this one goal paused. Say that instead.
                    result = (result.replace("so I stopped. You have control again.",
                                             "so I paused there — tell me what to do next.")
                                    .replace("You have control again.", "I'm still listening."))
            crashed = False
        except Exception as e:
            traceback.print_exc()
            result = (f"That didn't work ({type(e).__name__}: {e}). " +
                      ("Still listening — try that again, or tell me something else." if keep_session
                       else "You have control again."))
            crashed = True
        if keep_session and not stopped:
            session.remember(goal, result)
            control_session = session
            if crashed:   # a normal finish already reported "listening" itself (via the wrapped `report` above)
                report({"state": "listening", "detail": result, "goal": "", "step": 0, "maxSteps": 0})
        if not stopped:   # whoever stopped it has already been told
            announcements.put(result)

    threading.Thread(target=run, daemon=True, name="computer-control").start()
    if ask_id:
        return f"{question} Say yes or no."
    if bare:
        return "Sure, I'm ready."
    if already_active:
        return "Okay."
    if code_only:
        return "On it."   # the verified result is announced when it's done
    return (f"Okay, I'm using the computer to {goal}. Move the mouse, press {computer_use.STOP_SHORTCUT}, "
            "or say stop to take over.")


def handle_control_voice(text: str):
    """While Jervis is using the computer (or asking about it): stop, pause, continue, and yes/no answers."""
    global pending_control_question
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower().replace("\u2019", "'")).split())
    n = re.sub(r"^(?:(?:hey|ok|okay) )?(?:jervis|jarvis) ", "", n)   # "Hey Jervis, stop"
    if pending_control_question and time.time() - pending_control_question["at"] < 120:
        if _YES.fullmatch(n) and answer_control_question(pending_control_question["id"], True):
            pending_control_question = None
            return (f"Okay. Move the mouse, press {computer_use.STOP_SHORTCUT}, or say stop "
                    "whenever you want to take over.")
        if _NO.fullmatch(n) and answer_control_question(pending_control_question["id"], False):
            pending_control_question = None
            return "Okay, I won't."
    if session_active() or control_active():
        if _CONTROL_STOP.fullmatch(n):
            if computer_task is not None:
                computer_task.stop()
            if session_active():
                end_control_session()
            return "Stopping. You have control."
        if control_active():
            if _CONTROL_PAUSE.fullmatch(n):
                computer_task.pause()
                return "Paused. Say continue when you want me to go on."
            if _CONTROL_RESUME.fullmatch(n) and computer_task.state == "paused":
                computer_task.resume()
                return "Continuing."
    return None


_SERVICE_NAMES = re.compile(r"\b(spotify|youtube|netflix|stremio|google)\b")


def is_new_command(text: str, service: str) -> bool:
    """After "Open Spotify" -> "What would you like to listen to?", is this reply a *different* request (it names
    another service, or it's a command of its own, like a timer), rather than the answer?"""
    lowered = (text or "").lower()
    other = {m for m in _SERVICE_NAMES.findall(lowered) if m != service}
    return bool(other) or bool(parse_timer_command(text)) or bool(parse_volume_command(text))


def handle_direct_command(text: str):
    """Run reliable, explicitly spoken desktop commands without model tool-call guesses."""
    global youtube_active, netflix_active, stremio_active, pending_open_app, pending_app_choice
    control = handle_control_voice(text)
    if control:
        return control
    if is_phone_pair_command(text):
        return start_phone_pairing()
    if re.search(r"\bdisconnect\s+(?:the\s+|my\s+)?phone\b|\bend\s+(?:the\s+|my\s+)?phone\s+(?:session|connection)\b",
                text, re.I):
        return disconnect_phone_session()
    if re.search(r"\b(?:what|which|show|list)\b.*\bphones?\b.*\bpaired\b|\bpaired\s+phones?\b", text, re.I):
        return list_paired_phones()
    if re.search(r"\bforget\s+(?:my\s+|all\s+)?(?:paired\s+)?phones?\b|\bunpair\s+(?:my\s+)?phones?\b", text, re.I):
        return forget_paired_phones()
    text = fix_typos(text)
    blender_reply = handle_blender_command(text)
    if blender_reply:
        return blender_reply
    game_reply = handle_minecraft_command(text)
    if game_reply:
        return game_reply
    spotify = handle_spotify_search(text)   # before splitting "take control and search … in Spotify" into parts
    if spotify:
        return spotify
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
    clock_reply = handle_clock_question(text)
    if clock_reply:
        return clock_reply
    weather_reply = handle_weather_command(text)
    if weather_reply:
        return weather_reply
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
    global pending_spotify_choice
    if pending_spotify_choice:
        pending, pending_spotify_choice = pending_spotify_choice, None
        if time.time() - pending["at"] < 60:
            answer = bare_answer(text)
            if answer is True:   # exactly the result that was offered, by its URI — "yes" is never a new request
                return play_spotify_choice(pending)
            if answer is False:
                return "Okay, I didn't play anything."
    global pending_spotify_request
    if pending_spotify_request:
        pending, pending_spotify_request = pending_spotify_request, None
        if time.time() - pending["at"] < 45 and not is_new_command(text, "spotify"):
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            if bare_answer(text) is not None:   # "yes"/"ok" to "what would you like to listen to?" isn't a song
                pending_spotify_request = {"at": time.time()}
                return "What should I play?"
            return play_song(text)
    global pending_google_search
    if pending_google_search:
        pending, pending_google_search = pending_google_search, None
        if time.time() - pending["at"] < 45 and not is_new_command(text, "google"):
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            if bare_answer(text) is not None:
                pending_google_search = {"at": time.time()}
                return "What should I search for?"
            return google_search(text)
    app_reply = handle_app_followup(text)
    if app_reply:
        return app_reply
    global pending_netflix_request
    if pending_netflix_request:
        pending, pending_netflix_request = pending_netflix_request, None
        if time.time() - pending["at"] < 45 and not is_new_command(text, "netflix"):
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            if bare_answer(text) is not None:
                pending_netflix_request = {"at": time.time()}
                return "What should I put on?"
            return play_netflix_show(text)
    global pending_stremio_request
    if pending_stremio_request:
        pending, pending_stremio_request = pending_stremio_request, None
        if time.time() - pending["at"] < 45 and not is_new_command(text, "stremio"):
            cleaned = " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())
            if re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|stop|nevermind)", cleaned):
                return "Okay."
            if bare_answer(text) is not None:
                pending_stremio_request = {"at": time.time()}
                return "What should I put on?"
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
    seen = handle_screen_question(text)
    if seen:
        return seen
    here = handle_write_here(text)
    if here:
        return here
    program = handle_program_request(text)
    if program:
        return program
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
        if youtube_active or netflix_active or not spotify_available() or youtube_is_playing():
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
        if spotify_available() and (spotify_active or spotify_is_playing()) and not (youtube_active or netflix_active) \
                and not youtube_is_playing():
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
    search = web_search.parse_request(text)
    if search:
        return run_web_search(*search, new_tab=wants_new_tab(text), context=text)
    if is_youtube_command(text) or is_youtube_followup(text):
        query = extract_youtube_query(text)
        if query:
            return play_youtube_video(query, new_tab=wants_new_tab(text))
        if is_youtube_followup(text) and re.search(r"\bplay\b", normalized):
            return control_playback("resume")

    if re.search(r"\bopen\s+(the\s+)?youtube\b", normalized):
        open_youtube("https://www.youtube.com", wants_new_tab(text), context=text)
        return "Opened YouTube."

    close_target = app_launcher.parse_close_request(text)
    if close_target:
        closed = app_launcher.close_application(close_target)
        if closed:
            print(f"Close app: {close_target!r} -> {closed}", flush=True)
            return closed

    # "Open <any installed app>" — resolved against what's actually installed.
    app_name = parse_open_request(text)
    if app_name and app_launcher.means_this_app(app_name):
        pending_open_app = {"at": time.time()}
        return "Which app should I open?"
    if app_name:
        remember_media_app(app_name)
        # Blender always opens with Jervis's scripting bridge running, so a later "create a chair" (in this
        # session or a future one) never has to restart it and ask first — see blender_control.ensure_bridge.
        blender_status, blender_value = resolve_app(app_name)
        if blender_status == "ok" and "blender" in blender_value.lower():
            open_blender_in_background()
            opened = f"Opening {blender_value}."
        else:
            opened = open_application(app_name)
        print(f"Open app: {app_name!r} -> {opened}", flush=True)
        if app_launcher.last_choices:
            pending_app_choice = {"options": list(app_launcher.last_choices), "at": time.time()}
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
    if _CONTROL_BARE.match(text or ""):
        return start_computer_task("", persistent=True)
    goal = parse_computer_task(text)
    if goal:
        if _is_explicit_control_phrase(text):
            blender_reply = handle_blender_command(goal)   # "take control and make the cube bigger"
            if blender_reply:
                return blender_reply
        return start_computer_task(goal, persistent=_is_explicit_control_phrase(text))
    if session_active() and _ACKNOWLEDGEMENT.fullmatch(text.strip()):
        return "Okay."   # "okay, thank you" between commands: nothing to do, and no reason to wait for the AI
    if session_active() and looks_like_session_goal(text):
        # Routed through start_computer_task even while a task is already running: a new command replaces a stuck
        # one (see _make_room_for_new_task) instead of silently falling through to the general chat AI.
        return start_computer_task(text.strip(), persistent=True)
    return None


_ACKNOWLEDGEMENT = re.compile(r"(?:(?:ok(?:ay)?|thanks?|thank you(?: so much)?|cool|great|nice|got it|alright|"
                              r"all right|good|perfect|jervis)[ ,.!]*)+", re.I)
_BLENDER_THING = re.compile(r"\b(?:blender|cube|sphere|cylinder|cone|torus|donut|monkey|suzanne|mesh|object|"
                            r"vertex|vertices|modifier|material)\b", re.I)
blender_session = None     # tracks Blender objects for commands run without a "take control" session
blender_launch = None      # the thread opening Blender with its bridge, while it runs


def is_blender_goal(goal: str, said: str = "") -> bool:
    """A concrete Blender instruction ("create a cube", "make the cube bigger"), with Blender open (or opening), or
    with "Blender" said outright. Not "take control …" or "open Blender …" sentences: those have their own paths."""
    said = said or goal
    named = bool(re.search(r"\bblender\b", said, re.I))
    recent = time.time() - blender_last_used < BLENDER_RECENT_SECONDS
    if goal and _BLENDER_HOUSEKEEPING.fullmatch(goal) and (named or recent):
        return True   # "undo" / "do it again" right after working in Blender means Blender's last change
    if goal and blender_commands.correction(goal) and (named or recent):
        return True   # "no, the roof" / "the door too" right after a Blender command corrects or repeats it
    if not goal or not looks_like_session_goal(goal) or _is_explicit_control_phrase(said):
        return False
    if re.search(r"\b(?:open|launch|start)\s+(?:up\s+)?blender\b", said, re.I):
        return False
    if not named and agent_code.is_program_request(said):
        return False   # "create a Python program that ..." right after Blender work is for the code agent
    known = blender_commands.is_command(goal)
    thing = bool(_BLENDER_THING.search(said)) and blender_commands.looks_concrete(goal)
    build = (bool(_BUILD_REQUEST.match(goal)) and blender_commands.looks_concrete(goal)
             and not _NOT_BLENDER.search(goal))
    if not (known or thing or build):
        return False
    if named or blender_launching():
        return True
    if not blender_control.blender_running():
        return False
    if known or thing:
        return True
    # "Make a car" with Blender merely open somewhere could mean anything: only when Blender is what's being worked in.
    return time.time() - blender_last_used < BLENDER_RECENT_SECONDS or app_in_front("blender")


_BUILD_REQUEST = re.compile(r"^(?:please |can you |could you |now |then |also )*(?:create|make|build|model|design|"
                            r"add|draw|generate|construct|put|place|give me|sculpt|colou?r|paint|rotate|spin|scale|"
                            r"resize|duplicate|rename|move|delete|remove|stack|arrange|align|plant|grow|scatter|"
                            r"spawn|set up|erect)\b", re.I)
# "Remove the timer" / "move the song to my playlist" with Blender in front are still not about the scene.
_NOT_BLENDER = re.compile(r"\b(?:timers?|alarms?|songs?|music|tracks?|volume|reminders?|playlists?|videos?|tabs?|"
                          r"windows? (?:of|in) (?:chrome|the browser)|emails?|messages?|events?|meetings?)\b", re.I)
BLENDER_RECENT_SECONDS = 15 * 60
_BLENDER_HOUSEKEEPING = re.compile(r"(?:please )?(?:undo|redo)(?: (?:that|it|the last (?:change|action|step)))?|"
                                   r"do (?:that|it) again|again|one more time|save(?: (?:it|the (?:file|project|scene)))?",
                                   re.I)
blender_last_used = 0.0


def app_in_front(name: str) -> bool:
    """Is `name` (e.g. "blender", "minecraft") the app the user is working in?"""
    window = app_launcher.front_app_window()
    if not window:
        return False
    hwnd, title, friendly = window
    try:
        import winctl
        exe = winctl.window_process_name(hwnd) or ""
    except Exception:
        exe = ""
    return name.lower() in f"{title} {friendly} {exe}".lower()


def run_blender_directly(goal: str):
    """Everyday Blender commands run straight through the bridge: no mouse, no permission question, no AI — done in
    well under a second, and checked against Blender's real state before saying so. None if this can't handle it
    (no bridge, or not a command blender_commands.py knows), so the caller falls back to the slower paths."""
    global blender_session
    if blender_launching():
        return None   # still opening: the task thread waits for it (start_computer_task), the voice thread doesn't
    bridge = blender_control.BlenderBridge()
    if not bridge.ping(timeout=1.5):
        return None
    if session_active():
        session = control_session
        session.blender = bridge
    else:
        blender_session = blender_session or computer_use.ControlSession(None)
        session = blender_session
    steps = blender_commands.steps_for(goal, session, bridge)
    if not steps:
        return None
    if not _make_room_for_new_task():   # a running task may be sending Blender code too: one at a time
        return "Still working on that — one moment."
    results = []
    for description, action in steps:
        print(f"Blender: {description}", flush=True)
        try:
            results.append(action())
        except Exception as e:
            results.append(str(e))
            break
    return " ".join(r for r in results if r)


def open_blender_in_background() -> None:
    """Open Blender with its scripting bridge (slow: off the voice thread). A request said meanwhile ("open Blender
    and build a house") waits for it in run_blender_directly; the agent model is loaded into the GPU in parallel."""
    global blender_launch, blender_last_used

    def launch():
        bridge = blender_control.launch_with_bridge()
        if bridge and session_active():
            control_session.blender = bridge
    blender_last_used = time.time()
    blender_launch = threading.Thread(target=launch, daemon=True, name="blender-bridge-launch")
    blender_launch.start()
    threading.Thread(target=prime_blender_agent, daemon=True, name="agent-warm-up").start()


def blender_launching() -> bool:
    return blender_launch is not None and blender_launch.is_alive()


def prime_blender_agent() -> None:
    # Not while the conversation is in another language: on an 8 GB GPU the agent's model and the translator can't
    # both stay loaded, and warming one up evicts the other just before it's needed (each swap ~5 s).
    if language.reply_language() != "en" and language.translator():
        return
    agent_core.AgentTask("", agent_blender.BlenderAdapter(None)).prime()


def wants_picture_rebuilt(text: str) -> bool:
    """"Recreate this image in Blender" / "turn this photo into a 3D scene" with a picture in the conversation:
    the Blender agent rebuilds it (agent_blender reads the picture itself) — never the chat AI describing it."""
    try:
        import reconstruct
    except Exception:
        return False
    if not reconstruct.is_reconstruction_request(text) or not images.has_pending_context():
        return False
    named = re.search(r"\b(?:blender|3d|3-d|three[- ]d|scene)\b", text or "", re.I)
    return bool(named or blender_control.blender_running() or
                time.time() - blender_last_used < BLENDER_RECENT_SECONDS)


def handle_blender_command(text: str):
    global blender_last_used
    if wants_picture_rebuilt(text):
        blender_last_used = time.time()
        return start_computer_task(" ".join(text.split()), persistent=True, blender=True)
    goal = blender_commands.normalize(text)
    if not is_blender_goal(goal, said=text):
        return None
    blender_last_used = time.time()
    # The chat AI can't touch Blender and would only claim it did: this never reaches it.
    direct = run_blender_directly(goal)
    if direct:
        threading.Thread(target=prime_blender_agent, daemon=True).start()   # ready for a bigger request next
        return direct
    understood = understand_blender_command(text)
    if understood:
        return understood
    return start_computer_task(goal, persistent=True, blender=True)


# "Make it nicer / more realistic": real requests for the modelling agent's inspect-and-refine, never a question.
_BLENDER_REFINE = re.compile(r"\b(?:nicer|better|prettier|cooler|cuter|improve|polish|refine|realistic|detailed|"
                             r"beautiful|interesting|more (?:detail|realism|style))\b", re.I)


def understand_blender_command(text: str):
    """A Blender command the quick commands didn't recognise as said ("put more size on the cube"): if the language
    model reads it as one of them, run that (instant, exact) instead of the modelling agent — which, given a
    one-line edit, can plan something else entirely. Unclear ("make it", "do the thing"): ask. None: the agent."""
    global pending_clarify
    if _BLENDER_REFINE.search(text) or not nlu.worth_understanding(text) or text.lower().startswith("in blender, "):
        return None    # (the last: already the language model's own reading of a build request)
    try:
        kind, value = nlu.interpret(text, language_context(), local_llm.chat_json)
    except Exception as e:
        print(f"Language understanding unavailable: {str(e)[:120]}", flush=True)
        return None
    print(f"Understood Blender request {text!r} as {kind}: {value!r}", flush=True)
    if kind == "command" and blender_commands.is_command(value):
        return run_blender_directly(blender_commands.normalize(value))
    if kind == "clarify":
        pending_clarify = {"said": text, "question": value, "at": time.time()}
        return value
    return None


_GAME_ACTION = re.compile(r"^(?:please |can you |could you |now |then |also )*(?:create|make|build|construct|put|"
                          r"place|give me|summon|spawn|teleport|tp|set|change|turn|fill|clear|dig|make it)\b", re.I)


def handle_minecraft_command(text: str):
    """"Build a stone tower" while playing Minecraft (or "… in Minecraft"): the agent, with the Minecraft adapter."""
    named = bool(re.search(r"\bminecraft\b", text or "", re.I))
    goal = re.sub(r",?\s*\b(?:in|on|inside)\s+minecraft\b,?", " ", text or "", flags=re.I)
    goal = re.sub(r"^(?:(?:okay|ok|so|now|hey|jervis|jarvis)\b[,.!]?\s*)+", "", " ".join(goal.split())).strip(" ,.!?")
    if not goal or not _GAME_ACTION.match(goal) or not looks_like_session_goal(goal):
        return None
    if not (named or app_in_front("minecraft")):
        return None
    if not app_launcher.app_windows("Minecraft"):
        return "Minecraft isn't open. Start a world first, then ask me again." if named else None
    threading.Thread(target=local_llm.warm_up, args=("agent",), daemon=True).start()
    return start_computer_task(goal, persistent=True, agent_adapter=agent_minecraft.MinecraftAdapter)


def _install_blender_bridge() -> None:
    try:
        count = blender_control.install_startup_script()
        if count:
            print(f"Blender bridge set up for {count} Blender version(s).", flush=True)
    except Exception as e:
        print(f"Couldn't set up the Blender bridge: {e!r}", flush=True)


def run_web_search(engine: str, query: str, new_tab: bool = False, context: str = "") -> str:
    """"Search Google for cats" / "search YouTube for Minecraft": the results page, in the browser."""
    query = " ".join((query or "").split())
    if not query:
        return "What should I search for?"
    if engine == "youtube":
        try:
            open_youtube(web_search.youtube_results_url(query), new_tab, context=context or query)
        except Exception as e:
            print(f"YouTube search failed: {e!r}", flush=True)
            return f"I couldn't open YouTube to search for {query}: {e}"
        return f"Here are YouTube results for {query}."
    return google_search(query)


# "Open this app" -> "Which app should I open?"; "Blender" -> "Which one did you mean: 4.3 or 4.5?": the next answer.
pending_open_app = None    # {"at"}
pending_app_choice = None  # {"options": [names], "at"}


def handle_app_followup(text: str):
    """The answer to Jervis's own "which app?" questions, or None (then the sentence is handled as usual)."""
    global pending_open_app, pending_app_choice
    cleaned = " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())
    cancel = re.fullmatch(r"(?:never ?mind|cancel|forget it|no|nothing|none|stop|neither)(?: of them)?", cleaned)
    if pending_app_choice:
        pending, pending_app_choice = pending_app_choice, None
        if time.time() - pending["at"] < 60:
            if cancel:
                return "Okay."
            picked = app_launcher.pick_choice(text, pending["options"])
            if picked and pending.get("control"):   # asked while taking control: carry on with that, visibly
                return start_computer_task(f"open {picked}", persistent=pending.get("persistent", False))
            if picked:
                return open_application(picked)
    if pending_open_app:
        pending, pending_open_app = pending_open_app, None
        if time.time() - pending["at"] < 60:
            if cancel:
                return "Okay."
            name = parse_open_request(text) or app_launcher._clean_target(cleaned)
            known = resolve_app(name)[0] != "missing" or _site_for(name) if name else False
            if known and not app_launcher.means_this_app(name):
                opened = open_application(name)
                if app_launcher.last_choices:
                    pending_app_choice = {"options": list(app_launcher.last_choices), "at": time.time()}
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


def spotify_available() -> bool:
    """Spotify can be controlled: with the user's own Spotify keys (Settings), or through the Spotify app itself."""
    return bool(sp) or spotify_local.installed()


def _mark_spotify_playing() -> None:
    global youtube_active, netflix_active, stremio_active, spotify_active
    youtube_active = netflix_active = stremio_active = False
    spotify_active = True


pending_spotify_choice = None   # {"candidate": {uri, kind, title, artists, query}, "at"}: "play the closest one?"


def _offer_closest(message: str, closest) -> str:
    """Nothing fit well enough to play without asking: offer the nearest result — kept exactly (its URI), so a
    "yes" plays that very result and nothing else."""
    global pending_spotify_choice
    if not closest:
        return message
    pending_spotify_choice = {"action": "PLAY_SPOTIFY_ITEM", "at": time.time(),
                              "candidate": {k: closest.get(k) for k in ("uri", "kind", "title", "artists", "query")}}
    return f"{message} Should I play it?"


def _playing_reply(chosen: dict, start_seconds=None, where_ok=False, request: str = "") -> str:
    where = f" from {format_time(int(start_seconds))}" if start_seconds and where_ok else ""
    asked = spotify_match.parse(request) if request else {}
    if asked.get("title") and asked.get("artist") and chosen.get("kind") == "artist":
        # a song by them was asked for and Spotify hasn't got it: say so, don't pass their music off as it
        return (f"I couldn't find \"{asked['title']}\" by {chosen['title']} on Spotify, so I'm playing "
                f"{chosen['title']}.")
    closest = " (the closest match I found)" if chosen.get("verdict") == "plausible" else ""
    return f"Playing {spotify_match.describe(chosen)} on Spotify{where}{closest}."


def play_song_locally(request: str, start_seconds=None) -> str:
    """No Spotify keys: Jervis reads the Spotify app's own search results, picks the one meant (spotify_match),
    presses its own Play button and checks it really plays (spotify_local.play_request)."""
    global youtube_active, netflix_active, stremio_active, spotify_active
    try:
        chosen = spotify_local.play_request(request)
    except spotify_local.NotFound as e:
        print(f"Spotify: nothing fits {request!r} (searched {e.searched})", flush=True)
        return _offer_closest(str(e), e.closest)
    except spotify_local.SpotifyLocalError as e:
        print(f"Spotify (app) didn't start {request!r}: {e}", flush=True)
        return str(e)
    except Exception as e:
        traceback.print_exc()
        return f"Something went wrong while starting Spotify ({type(e).__name__}: {e}). Try again, or press play in Spotify."
    youtube_active = netflix_active = stremio_active = False
    spotify_active = True
    print(f"Spotify: {request!r} -> {chosen.get('uri')} ({chosen.get('verdict')} {chosen.get('score')}), "
          f"now playing {chosen.get('now')!r}", flush=True)
    seeked = bool(start_seconds) and spotify_local.seek(int(start_seconds))
    if chosen.get("uri") is None:   # (a Mac: Spotify's Quick Search played its top result)
        return f"Playing {chosen['now']} on Spotify." if chosen.get("now") else "Playing it on Spotify."
    return _playing_reply(chosen, start_seconds, seeked, request)


def play_spotify_choice(pending: dict) -> str:
    """The offered result, exactly (by its URI)."""
    cand = pending["candidate"]
    if not sp:
        try:
            chosen = spotify_local.play_exact(cand)
        except spotify_local.SpotifyLocalError as e:
            return str(e)
        _mark_spotify_playing()
        return _playing_reply(chosen)
    return _play_uri_with_keys(cand)


def play_song(song_name: str, start_seconds=None, **kwargs) -> str:
    """Play a track on Spotify, optionally starting `start_seconds` into it."""
    spoken_seconds, cleaned = timeparse.strip_start_time(song_name)  # the model may leave "minute two" in the title
    song_name = cleaned or song_name
    start_seconds = start_seconds or spoken_seconds
    if not sp:
        return play_song_locally(song_name, start_seconds)
    # With the user's own Spotify keys: the Web API's results, ranked by the same rules, played by exact URI.
    intent = spotify_match.parse(song_name)
    found, searched, pick = [], [], None
    for q in spotify_match.queries(intent):
        try:
            results = sp.search(q=q, type="track,artist,album,playlist", limit=10)
        except Exception as e:
            return f"Spotify search failed: {e}"
        searched.append(q)
        found += spotify_api_candidates(results, q)
        pick = spotify_match.choose(intent, found)
        if spotify_match.settled(intent, pick):
            break
    if not pick or pick["verdict"] == "none":
        closest = pick["best"] if pick else None
        return _offer_closest(f"I couldn't find {intent['text']} on Spotify." +
                              (f" The closest was {spotify_match.describe(closest)}." if closest else ""), closest)
    chosen = dict(pick["best"], verdict=pick["verdict"])
    print(f"Spotify (API): {song_name!r} -> {chosen['uri']} ({pick['verdict']} {pick['score']:.2f})", flush=True)
    return _play_uri_with_keys(chosen, start_seconds)


def spotify_api_candidates(results: dict, query: str) -> list:
    """The Web API's search results as candidates for spotify_match (Spotify's own order kept as position)."""
    out = []
    for kind, key in (("track", "tracks"), ("artist", "artists"), ("album", "albums"), ("playlist", "playlists")):
        for i, item in enumerate(((results or {}).get(key) or {}).get("items") or []):
            if not item or not item.get("uri"):
                continue
            artists = [a.get("name", "") for a in item.get("artists") or []]
            if kind == "playlist":
                artists = [((item.get("owner") or {}).get("display_name") or "")]
            out.append({"uri": item["uri"], "kind": kind, "title": item.get("name", ""), "artists": artists,
                        "position": i, "query": query, "duration_ms": item.get("duration_ms")})
    return out


def _play_uri_with_keys(chosen: dict, start_seconds=None) -> str:
    """Start exactly `chosen` (its URI) with the Web API, and check Spotify reports it playing."""
    global youtube_active, netflix_active, stremio_active, spotify_active
    device_id = ensure_spotify_device()
    if not device_id:
        return "Spotify needs to be open on a device first."
    position_ms = None
    if start_seconds and chosen.get("kind") == "track":
        position_ms = min(int(start_seconds) * 1000, max(0, int(chosen.get("duration_ms") or 10 ** 9) - 1000))
    try:
        if chosen.get("kind") == "track":
            sp.start_playback(device_id=device_id, uris=[chosen["uri"]], position_ms=position_ms)
        else:
            sp.start_playback(device_id=device_id, context_uri=chosen["uri"])
    except Exception as e:
        return f"Spotify didn't start {spotify_match.describe(chosen)}: {e}"
    youtube_active = netflix_active = stremio_active = False
    spotify_active = True
    for _ in range(10):   # did it really start? (a device can accept the call and play nothing)
        time.sleep(0.4)
        try:
            now = sp.current_playback() or {}
        except Exception:
            break
        item = now.get("item") or {}
        context = (now.get("context") or {}).get("uri")
        if now.get("is_playing") and (item.get("uri") == chosen["uri"] or context == chosen["uri"]):
            return _playing_reply(chosen, position_ms and position_ms // 1000, bool(position_ms))
    return f"I asked Spotify to play {spotify_match.describe(chosen)}, but it didn't report it playing."


def seek_music(seconds: int) -> str:
    if not sp:
        if spotify_local.seek(int(seconds)):
            return f"Jumping to {format_time(seconds)}."
        return "Spotify doesn't let me jump to a time here. Drag its progress bar instead."
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
        try:
            now = spotify_local.skip(direction)
        except spotify_local.SpotifyLocalError as e:
            return str(e)
        if now:
            return f"Now playing {now}."
        return "Skipped to the next song." if direction == "next" else "Went back to the previous song."
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
        return "Resuming the music." if spotify_local.resume() else "Spotify isn't open."
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
        if not sp:
            return spotify_local.is_playing()
        return bool((sp.current_playback() or {}).get("is_playing"))
    except Exception:
        return False


_NOT_SPOTIFY_STOP = re.compile(r"\b(timer|timers|alarm|reminder|listening|talking|speaking|window|tab|tabs|video|show|episode|movie|"
                               r"netflix|stremio|youtube|volume|recording|document|story|writing)\b")


def spotify_playback_action(text: str):
    """"Stop it, please", "pause", "stop the sound", "resume" -> "pause" / "resume" when Spotify is what is playing."""
    n = " ".join(re.sub(r"[^a-z' ]", " ", (text or "").lower()).split())
    if not spotify_available() or _NOT_SPOTIFY_STOP.search(n) or len(n.split()) > 7:
        return None
    if re.search(r"\b(pause|stop|halt|silence|hold on|be quiet|shut up)\b", n):
        action = "pause"
    elif re.search(r"\b(resume|unpause|continue|keep playing)\b", n):
        action = "resume"
    else:
        return None
    if youtube_active or netflix_active or stremio_active:
        return None
    if spotify_active or spotify_is_playing():
        return action
    # Paused in a Spotify the user opened themselves: "resume the music" / "continue the song" (but not a bare
    # "continue", which could mean anything) still means Spotify when it's running.
    if action == "resume" and re.search(r"\b(music|song|track|spotify)\b", n) and spotify_local.running():
        return action
    return None


def pause_music(**kwargs) -> str:
    if not sp:
        return "Paused playback." if spotify_local.pause() else "Spotify isn't playing anything."
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


# ---------- a phone on the same Wi-Fi (see phone_control.py) ----------
PHONE_COMMANDS = {   # commandType -> (the existing tool it reuses, the payload field it reads)
    "OPEN_APPLICATION": (open_application, "app_name"),
    "PLAY_SONG": (play_song, "song_name"),
    "PAUSE_MUSIC": (pause_music, None),
    "PLAY_YOUTUBE_VIDEO": (play_youtube_video, "query"),
    "SEARCH_GOOGLE": (google_search, "query"),
}


def _dispatch_phone_command(command_type: str, payload: dict) -> str:
    """Runs one allowed remote command through the same tool voice/chat would use. Only ever one of
    PHONE_COMMANDS — handle_phone_client refuses anything else before this is even reached."""
    entry = PHONE_COMMANDS.get(command_type)
    if not entry:
        raise ValueError(f"“{command_type}” isn't something a phone can ask Jervis to do.")
    func, key = entry
    if key is None:
        return str(func())
    value = str((payload or {}).get(key, "")).strip()
    if not value:
        raise ValueError(f"That needs {key.replace('_', ' ')}.")
    return str(func(value))


phone_server = phone_control.PhoneControlServer(execute=_dispatch_phone_command)
push_store = push.SubscriptionStore()   # phones that asked to be notified — see push.py


def _on_push_subscribe(subscription: dict) -> None:
    """A phone just turned notifications on — local or relay, same callback either way. Saves it, and closes the
    QR panel start_phone_session() puts up when it can't reach any phone yet (same signal pairing's own QR panel
    closes on, see phone_paired above)."""
    push_store.add(subscription)
    clear_ui_update("phone_pairing")
    send_ui_update_once({"type": "phone_notify_enabled"})


def _transcribe_phone_audio(pcm16_bytes: bytes, sample_rate: int) -> str:
    """session_router's callback: the same multi-engine transcribe() the desktop microphone uses, just fed PCM
    that started life as a phone recording instead of sr.Microphone (see phone_session.decode_audio_to_pcm16)."""
    return transcribe(sr.AudioData(pcm16_bytes, sample_rate, 2))


def _deliver_phone_voice_text(text: str, session_id: str) -> None:
    """session_router's callback for a finished transcription: queued like any typed/spoken command (see
    PhoneVoiceInput) so it goes through the exact same main-loop pipeline — must return immediately, not block
    whichever asyncio loop is currently running the transport (relay_client.py, or handle_phone_client below)."""
    typed_inputs.put(PhoneVoiceInput(text, session_id))


def _vapid_key_b64() -> str:
    """relay_client's answer to the relay's get_page_context — see relay/server.py's docstring on why the relay
    asks for this live instead of any key being baked into it: every Jervis install generates its own (push.py)."""
    return push.public_key_b64() if push.available() else ""


def _local_address() -> str:
    """relay_client's other answer to get_page_context: this computer's own current local address, shown by the
    relay-hosted page to a phone it doesn't recognize yet (the one-time local<->relay sync never ran for it — see
    phone_client.html's syncToOtherOrigin) so there's a real way forward instead of a dead end."""
    return f"http://{phone_control.lan_address()}:{PHONE_WS_PORT}"


# Shared between the local LAN phone server (handle_phone_client, right below) and relay_client.py: a "connect my
# phone" session behaves identically either way — see phone_session.py for why that's one router, not two.
session_router = phone_session.PhoneSessionRouter(phone_server, _transcribe_phone_audio, _deliver_phone_voice_text,
                                                   on_push_subscribe=_on_push_subscribe,
                                                   on_push_unsubscribe=push_store.remove)
relay = relay_client.RelayClient(RELAY_URL, session_router,
                                 is_enabled=lambda: bool(RELAY_URL) and phone_control_mode() != "off",
                                 get_vapid_key=_vapid_key_b64, get_local_address=_local_address)


def reply_to_phone_if_needed(typed, message: str) -> None:
    """The three places in main_loop that finish a turn all call this right after broadcast("ai", message) — a
    no-op unless `typed` is the PhoneVoiceInput that started this turn, in which case the phone that asked also
    gets the answer, over whichever transport (LAN or relay) it's actually attached on — session_router already
    knows which."""
    if isinstance(typed, PhoneVoiceInput):
        session_router.deliver_reply(typed.session_id, message)


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
    "use_computer": tool_use_computer,
    "get_weather": tool_get_weather,
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
    {
        "type": "function",
        "function": {
            "name": "use_computer",
            "description": "Operate the user's computer with the mouse and keyboard to do a task in an app that is on screen (click buttons, fill in fields, change a setting, move through a website). ONLY call when the user explicitly asks you to do something on their screen that no other tool does. Never for questions, and never to open an app or play music (other tools do that).",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "The task, in the user's words, e.g. 'scroll down' or 'fill in this form'."}
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Show the weather window and get the current weather and forecast (for the city set in Settings, or the city named). ONLY call when the user explicitly asks about the weather (e.g. 'what's the weather', 'is it raining', 'how hot is it outside').",
            "parameters": {"type": "object", "properties": {
                "city": {"type": "string", "description": "Only if the user named a place; otherwise leave empty."}}},
        },
    },
]

SYSTEM_PROMPT = """You are Jervis, an AI desktop assistant.
- NEVER execute tools unless the user explicitly commands an action (e.g., 'open application', 'play music').
- If the user asks general questions or makes conversational statements like 'can you hear me' or 'hello', DO NOT call tools. Respond naturally in 1-2 sentences.
- A statement that only mentions an app, website or topic in passing (e.g. "I installed Chrome yesterday") is not a request: reply to what the user actually said, and never bring up, offer, or describe an unrelated action, setting, or example from your own instructions.
- NEVER search the web or open a browser unless the user explicitly says the word 'Google'. For example: 'Google the weather in Tel Aviv.'
- Never say you opened, wrote, played or changed something unless a tool result confirmed it. If you cannot do something, say so plainly.
- You cannot see the user's messages, emails or files. Never claim that they have, or don't have, any unread messages or new mail: say you can't check that. You cannot see their Google Calendar either (a separate feature checks it before you're ever asked) — if a calendar question reaches you, tell the user to say "check my calendar" or "open my calendar" instead of guessing what is on it.
- Images: the user can attach photos, screenshots or other pictures, and you can create or edit images too. You cannot see an image yourself — only the image tools can. Use analyze_image to describe an attached image or answer a question about it, including a vague follow-up like "what's wrong with it" right after an image was shared (a system message will tell you when one is pending). Use extract_image_text to read text out of an image. Use compare_images once two or more images have been shared. Use generate_image only when explicitly asked to create/draw/make a picture of something, and edit_image only when explicitly asked to change an existing image (remove/add/replace something, change the background or style, etc). Never claim an image was generated, edited or analyzed unless a tool result actually confirmed it. If an image tool result explains what's missing or how to fix it (a setup step, an environment variable, a URL), repeat that specific detail back to the user instead of a vague "I can't do that" — they need to know exactly what to do next.
- use_computer lets you work in an app on the user's screen with the mouse and keyboard. Call it only when the user explicitly asks you to do something on screen (for example "scroll down" or "fill in this form"). The user is asked for permission and can stop you at any time; say in one short sentence what you're starting, never that it's finished.
- get_weather answers a direct weather question with the city set in Settings. Call it only when the user is actually asking about the weather.
- After using a tool, give the user a short natural spoken confirmation.
- Keep casual answers concise and natural, never emoji.
- Reply in English. Only when the user's message is written in Hebrew, reply in Hebrew.
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
pending_spotify_play = None     # {"query", "at"}: Spotify is showing a search, and "play it" plays it

# Words people mistype when giving orders ("take contorl"), matched loosely so a typo doesn't send a command to the AI.
_TYPO_TARGETS = ("control", "computer", "spotify", "search")


def fix_typos(text: str) -> str:
    import difflib
    def fix(match):
        word = match.group(0)
        if len(word) < 5 or word.lower() in _TYPO_TARGETS:
            return word
        close = difflib.get_close_matches(word.lower(), _TYPO_TARGETS, n=1, cutoff=0.8)
        return close[0] if close else word
    return re.sub(r"[A-Za-z]+", fix, text or "")


# "Take control (of my computer) and …", said before something Jervis can do directly: the preamble adds nothing.
_CONTROL_PREAMBLE = re.compile(
    r"^(?:(?:hey |ok |okay )?(?:jervis|jarvis)[, ]+)?(?:please |can you |could you )*(?:take (?:the )?control"
    r"(?: (?:over|of|on))?(?: (?:my|the) (?:computer|mac|pc|laptop|screen))?|use my (?:computer|mac|pc)|control my "
    r"(?:computer|mac|pc))(?:,? (?:and|to|then))?\s+", re.I)
_SPOTIFY_SEARCH = re.compile(
    r"^(?:(?:please|can you|could you|go ahead and) )*(?:search(?: for)?|look up|find|type(?: in)?(?: the search"
    r"(?: bar| box)?)?(?: for)?)\s+(?P<query>.+?)\s+(?:in|on|with)\s+(?:the\s+)?spotify(?: search(?: bar| box)?)?"
    r"(?: app)?[.!?]*$", re.I)
_SPOTIFY_PLAY = re.compile(
    r"^(?:(?:please|can you|could you|go ahead and) )*(?:play|put on|start|listen to|open)\s+(?P<query>.+?)\s+"
    r"(?:on|in|with|using|from)\s+(?:the\s+)?spotify(?: app)?[.!?]*$", re.I)
_PLAY_IT = re.compile(r"^(?:yes|yeah|yep|sure|ok|okay)?[, ]*(?:please )?(?:play (?:it|that|this|the first one|the song)"
                      r"|start it|yes|yeah|yep|sure|go ahead)(?: please)?[.!]*$", re.I)


def handle_spotify_search(text: str):
    """"Search for Jane! in Spotify" opens Spotify's search for it; "play it" then plays it. Spotify requests go to
    Spotify directly, never through general computer control (which the small local AI can't do reliably)."""
    global pending_spotify_play
    if pending_spotify_play and time.time() - pending_spotify_play["at"] < 90 and _PLAY_IT.match((text or "").strip()):
        query, pending_spotify_play = pending_spotify_play["query"], None
        return play_song(query)
    rest = _CONTROL_PREAMBLE.sub("", (text or "").strip(), count=1)
    if rest != (text or "").strip() and re.search(r"\bspotify\b", rest, re.I):
        # "Take control … and play X on Spotify": you asked to see it done, so it's done visibly, step by step.
        play = _SPOTIFY_PLAY.match(rest)          # (keeps the request exactly as written: "Jane!", not "jane")
        search = _SPOTIFY_SEARCH.match(rest)
        wanted = (play or search).group("query") if (play or search) else ""
        wanted = spotify_local.clean_query(re.sub(r"\b(?:the )?(?:song|track|album|artist|playlist)\s+", "", wanted,
                                                  flags=re.I))
        if wanted:
            # "Take control" was said explicitly: show it, even if Spotify keys are set up (those would otherwise
            # play it invisibly through the online API) — the whole point of the words was to watch it happen.
            return start_computer_task(f"play {wanted} on Spotify", scripted=spotify_local.visible_steps(wanted),
                                       after=_mark_spotify_playing)
    match = _SPOTIFY_SEARCH.match(rest)
    if not match:
        return None
    query = spotify_local.clean_query(re.sub(r"\b(?:the )?(?:song|track|album|artist|playlist)\s+", "",
                                             match.group("query"), flags=re.I))
    if not query:
        return None
    if not spotify_local.open_search(query):
        return "Spotify isn't installed on this computer. Get it from spotify.com, then ask me again."
    pending_spotify_play = {"query": query, "at": time.time()}
    return f"Here's {query} in Spotify. Say “play it” and I'll start it."
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


last_turn_typed = False   # whether the request being handled was typed into Jervis's window (else spoken)


def handle_screen_question(text: str):
    """"What's on my screen?" / "What does this error say?": read the window the user is working in and answer from
    what's really there (screen_reader.py). Reading only — nothing is clicked or typed."""
    if not screen_reader.is_screen_question(text):
        return None
    if (os.getenv("JERVIS_SCREEN_READING") or "on").strip().lower() == "off":
        return "Reading your screen is turned off in Settings."
    import screen_vision
    vision = screen_vision.ScreenVision() if screen_vision.available() else None

    def chat(messages):
        response = groq_chat(model=GROQ_MODEL, messages=messages, max_tokens=500)
        return response.choices[0].message.content or ""
    try:
        return screen_reader.answer(text, computer_environment(), vision, chat)
    except Exception as e:
        print(f"Reading the screen failed: {e!r}", flush=True)
        return "I couldn't read your screen just now."
last_program = None       # the last program written (agent_code.CodeTask.program()): "make it also ...", "run it again"
code_task = None


def handle_program_request(text: str):
    """"Write a Python program that ...": written, run, checked and fixed until its own self-checks pass
    (agent_code.py), on a thread of its own; the verified result is announced when it's done. Follow-ups ("make it
    also print the total", "run it again") change or rerun the last program."""
    global code_task
    recent = last_program is not None and time.time() - last_program["at"] < 15 * 60
    follow = bool(recent and agent_code.FOLLOW_UP.match(text or ""))
    if not (agent_code.is_program_request(text) or follow) or re.search(r"\bblender\b", text or "", re.I):
        return None
    if code_task is not None and code_task.state not in ("completed", "error", "stopped"):
        return "I'm still working on the last program — one moment."
    rerun = follow and bool(re.match(r"^(?:(?:now|ok|okay|and|please)\s+)*(?:run|rerun|test) it", text, re.I))
    task = agent_code.CodeTask(text, log=lambda m: print(m, flush=True),
                               confirm=ask_control_question, previous=last_program if follow else None, rerun=rerun)
    code_task = task

    def work():
        global last_program
        result = task.run()
        if task.path:
            last_program = task.program()
            if task.code:   # the code itself goes in the window (never read aloud)
                broadcast("ai", f"**{os.path.basename(task.path)}** — `{task.path}`\n\n```{task.language}\n"
                                f"{task.code.rstrip()}\n```")
        print(f"Program task {task.state}: {result[:160]}", flush=True)
        announcements.put(result)

    threading.Thread(target=work, daemon=True, name="code-task").start()
    if rerun:
        return "Running it again and checking it."
    return ("On it — I'll change it, run it and check it." if follow else
            "On it — I'll write it, run it, and check it works before I tell you it's done.")


def handle_write_here(text: str):
    """"Write me a story about a secret island" with the cursor in a document, an email or an editor: write it and
    type it in right there, then check it's really there (see write_here.py). None when it isn't that."""
    if not write_here.is_write_request(text):
        return None
    target = write_here.find_target()   # now, before Jervis's own window steps forward or aside
    if not write_here.wants_here(text, target, spoken=not last_turn_typed):
        return None

    def write_and_type():
        try:
            response = groq_chat(model=GROQ_MODEL, max_tokens=2500, messages=[
                {"role": "system", "content": write_here.writing_prompt(target)}, {"role": "user", "content": text}])
            body = write_here.clean(response.choices[0].message.content or "")
        except Exception as e:
            print(f"Writing failed: {e!r}", flush=True)
            raise RuntimeError(groq_error_reply(e)) from e
        if not body:
            raise RuntimeError("I couldn't come up with any text for that, so I didn't type anything.")
        return write_here.insert(target, body)

    print(f"Writing where the cursor is, in {target.app!r} ({target.title[:60]!r})", flush=True)
    return start_computer_task(text, scripted=[("Writing it and typing it where your cursor is", write_and_type)])


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


def is_weather_command(text: str) -> bool:
    """Only allow the weather tool for an explicit question, not a passing mention of the word (e.g. "I was
    talking about the weather yesterday" must not trigger it)."""
    request = parse_weather_request(text)
    return bool(request and request["action"] == "show")


def should_enable_tools(text: str) -> bool:
    """Do not expose tools during ordinary conversation or incomplete phrases."""
    return (is_google_search_command(text) or is_music_command(text) or is_app_command(text) or is_youtube_command(text)
            or images.is_image_command(text) or images.has_pending_context() or is_computer_request(text)
            or is_weather_command(text))


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
    if os.getenv("JERVIS_NO_AI_SETUP") != "1":
        local_ai_manager.start_background()   # it was ready before and stopped: bring it back
    return "My AI isn't running right now, so I'm starting it again. Ask me again in a moment."


def groq_error_reply(error: Exception) -> str:
    if isinstance(error, local_llm.LocalAIUnavailable):
        if "ReadTimeout" in str(error):   # it's running, just busy (a long Blender build on the same GPU)
            return "My local AI is busy with another job and didn't answer in time. Ask me again in a moment."
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
    if head[0].get("role") == "system":   # the model has no clock: "how long until Friday?" needs today's date
        now = datetime.now()
        # The coming week spelled out: a small model miscounts "days until Friday" from the weekday name alone.
        week = "; ".join(f"in {n} day{'s' if n > 1 else ''} it is {(now + timedelta(days=n)).strftime('%A, %B')} "
                         f"{(now + timedelta(days=n)).day}" for n in range(1, 8))
        head = [{**head[0], "content": f"{head[0]['content']}\n- Right now it is {now.strftime('%A')}, "
                                       f"{now.strftime('%B')} {now.day}, {now.year}, {now.strftime('%H:%M')} (this "
                                       f"computer's clock); {week}. Use it for anything about the time, date or day."}]
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
    role = kwargs.pop("role", "chat")   # which local model does this job (see local_llm.model_for)
    if "gpt-oss" in str(kwargs.get("model", "")):  # a "thinking" model: keep the thinking short, it counts against the limit
        kwargs.setdefault("reasoning_effort", "low")
        kwargs.setdefault("max_tokens", 1500)
    if LLM_BACKEND == "ollama":
        return local_llm.chat(role=role, **kwargs)
    if LLM_BACKEND == "auto" and time.time() < groq_down_until:
        return local_llm.chat(role=role, **kwargs)
    try:
        return _groq_chat_with_retry(**kwargs)
    except Exception as e:
        status = getattr(e, "status_code", None)
        log_ai_error(e)
        if LLM_BACKEND == "auto" and is_model_glitch(e):
            try:
                print("The online AI glitched twice; using the local AI for this answer.", flush=True)
                return local_llm.chat(role=role, **kwargs)
            except local_llm.LocalAIUnavailable:
                raise e
        if LLM_BACKEND != "auto" or status in (400, 404, 422):  # a bad request is not a reason to switch AI
            raise
        groq_down_until = time.time() + (60 if status == 429 else 300)
        print(f"Online AI unavailable ({type(e.__cause__ or e).__name__}); switching to the local AI for a while.", flush=True)
        try:
            return local_llm.chat(role=role, **kwargs)
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


ACTION_TOOLS = {"use_computer", "play_song", "pause_music", "open_application", "play_youtube_video"}
_CLAIMS_ACTION = re.compile(
    r"\b(?:i'?m (?:now )?(?:using|controlling) (?:the|your) (?:computer|mouse)|i (?:have |'ve )?(?:opened|clicked|typed|"
    r"searched|started|played|launched|pressed)\b|i(?:'ll| will) (?:now )?(?:take control (?:of|over|on)|open|click|"
    r"type|search|play|launch|press)\b|(?:starts|started|is now|now) playing|is playing now|"
    r"the (?:search bar|screen|window) (?:says|shows)|the result is a list|type (?:the word )?[\"“]confirm[\"”]|"
    r"please confirm (?:that )?you(?:'d| would)? like|"
    r"i(?: have|'ve)? (?:selected|scaled|resized|rotated|colou?red|painted)\b|"
    r"i(?: have|'ve)? (?:created|added|moved|deleted|made) (?:a|an|the|your) (?:cube|sphere|cylinder|cone|object|"
    r"mesh|shape)\b|"
    r"(?:^|[.!] )(?:scaling|resizing|creating|adding|moving|rotating|colou?ring|deleting) (?:the|a|an|it|your)\b|"
    # Jervis's own command replies start "Done —": the chat model copies them from the history ("Done — Cube.002 is
    # taller now.") for something that never ran
    r"^done\b|\b(?:is|are) (?:now (?:taller|shorter|bigger|smaller|wider|narrower|larger|thinner)\b|"
    r"(?:taller|shorter|bigger|smaller|wider|narrower|larger|thinner) now\b)|"
    r"\bi(?: have|'ve)? (?:made|undid|undone|duplicated) (?:it|that|the|a|an)\b)", re.I)


def with_verified_math(messages: list, user_text: str) -> list:
    """For a question with numbers in it, the exact answer worked out in code (reasoning.py), handed to the AI as a
    fact for this one answer — so the explanation can be its own, but the numbers are right."""
    if not reasoning.looks_quantitative(user_text) or not local_llm.role_model("agent"):
        return messages
    facts = reasoning.verified_facts(user_text, local_llm.chat_json)
    if not facts:
        return messages
    print(f"Verified math: {facts}", flush=True)
    note = {"role": "system", "content": f"Exact result, computed in code for the user's last question: {facts} "
                                         "Use exactly these numbers in your answer."}
    return messages[:-1] + [note] + messages[-1:] if messages else messages


def ask_jervis(messages, user_text=""):
    tools, tool_choice = select_tools(user_text)
    try:
        kwargs = {"model": GROQ_MODEL, "messages": trim_for_ai(with_verified_math(messages, user_text))}
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
        # This turn plainly asked for an action (by the same classifiers that gate the real tools), but no tool
        # ran — whatever the model wrote instead (a claim, or a whole fake back-and-forth about "confirming") is
        # never shown: a free-text answer to an action request is untrustworthy by construction here.
        action_shaped = (is_computer_request(user_text) or is_music_command(user_text) or is_youtube_command(user_text)
                         or is_app_command(user_text))
        if content and (action_shaped or _CLAIMS_ACTION.search(content)):
            print("The AI answered in text instead of acting on a request that needed a tool; replaced.", flush=True)
            return ("I didn't do anything on your computer for that. Say it as a command, like “make it taller”, "
                    "“play Jane on Spotify” or “use my computer to open Downloads”.")
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
            elif name == "use_computer" and not is_computer_request(user_text):
                result = "Using the computer was blocked because the user did not ask for anything to be done on screen. Respond normally."
            elif name == "get_weather" and not is_weather_command(user_text):
                result = "The weather tool was blocked because the user did not explicitly ask about the weather. Respond normally."
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

    # An action's own result is exactly what happened ("Playing X on Spotify.", "Can I use your mouse…?"): say that,
    # rather than letting the AI retell it (a small model turns "Can I…?" into "I'm using the computer…").
    if len(tool_calls) == 1 and tool_calls[0].function.name in ACTION_TOOLS:
        return str(result)

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


_MATH_WORDS = {
    "en": (" equals ", " times ", " divided by ", " plus ", " minus ", " squared", " cubed", "square root of "),
    "he": (" \u05e9\u05d5\u05d5\u05d4 ", " \u05db\u05e4\u05d5\u05dc ", " \u05d7\u05dc\u05e7\u05d9 ", " \u05d5\u05e2\u05d5\u05d3 ", " \u05e4\u05d7\u05d5\u05ea ", " \u05d1\u05e8\u05d9\u05d1\u05d5\u05e2", " \u05d1\u05d7\u05d6\u05e7\u05ea \u05e9\u05dc\u05d5\u05e9", "\u05e9\u05d5\u05e8\u05e9 \u05e9\u05dc "),
}


def _say_math(text: str) -> str:
    """Math symbols as words for the voice: "x = 10" -> "x equals 10" (in Hebrew for a Hebrew reply)."""
    words = _MATH_WORDS["he" if osal.has_hebrew(text) else "en"]
    for pattern, said in zip((r"\s*[=\u2248]\s*", r"\s*\u00d7\s*", r"\s*\u00f7\s*", r"(?<=\d)\s+\+\s+(?=[\w(])",
                              r"(?<=\d)\s+[-\u2212]\s+(?=\d)", r"\^2\b", r"\^3\b", r"\u221a"), words):
        text = re.sub(pattern, said, text)
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
        note = _note("I've put the details on your screen.", text) if connected_clients else ""
        return " ".join(part for part in (intro or _note("Here's what I found.", text), note, closing) if part)
    plain = _strip_markdown(" ".join(lines))
    if len(plain) <= 320:
        return plain
    short = ""
    for sentence in re.split(r"(?<=[.!?])\s+", plain):
        if short and len(short) + len(sentence) > 240:
            break
        short = f"{short} {sentence}".strip()
    short = short[:320].rsplit(" ", 1)[0] if len(short) > 320 else short
    return f"{short} " + _note("I've put the details on your screen.", text) if connected_clients else short


def _note(english: str, reply: str) -> str:
    """A sentence the voice adds to a reply, in the reply's own language."""
    return language.phrase(english, language.detect(reply)[0] or "en")


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
# ...and these in Hebrew (the closing lines of the subtitled videos it learned from). "תודה" / "תודה רבה" can be
# real, so they're only dropped while Jervis is asleep and hearing the whole room.
WHISPER_HALLUCINATIONS_HE = re.compile(r"^(?:תודה (?:רבה )?(?:ש|על ה|ל)צפי(?:תם|ה|יה)|הפקה|"
                                       r"(?:תרגום|כתוביות)(?: \S+){0,3}|אה+|אממ+|הממ+|מממ+)$")   # (credits)
WHISPER_HALLUCINATIONS_HE_PASSIVE = {"תודה", "תודה רבה", "שלום", "ביי", "להתראות"}


def is_whisper_hallucination(text: str, passive: bool) -> bool:
    cleaned = " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())
    if cleaned in WHISPER_HALLUCINATIONS:
        return True
    hebrew = " ".join(re.sub(r"[^א-ת\"״ ]", " ", text).split())
    if not hebrew or re.search(r"[a-z]", text, re.I):
        return False
    return bool(WHISPER_HALLUCINATIONS_HE.match(hebrew)) or (passive and hebrew in WHISPER_HALLUCINATIONS_HE_PASSIVE)


def transcribe_local(wav_bytes: bytes) -> str:
    heard = stt_local.transcribe_full(wav_bytes)
    print(f"Local Whisper ({heard.engine}, {heard.language} {heard.confidence:.2f}, {heard.seconds:.2f}s): "
          f"{heard.text!r}", flush=True)
    return heard.text


def transcribe_groq(wav_bytes: bytes) -> str:
    """Whisper on Groq: far more accurate than the free Google web recognizer.

    No `prompt` on purpose: with silence or noise Whisper echoes the prompt back
    ("Play a song."), which would fire commands from background noise.
    """
    language = stt_local.whisper_language()    # JERVIS_STT_LANGUAGE: "en" unless Hebrew speech was turned on
    result = groq_client.audio.transcriptions.create(
        file=("speech.wav", wav_bytes),
        model=STT_MODEL,
        temperature=0.0,
        timeout=15,
        **({"language": language} if language else {}),
    )
    return (result.text or "").strip()


def transcribe_google(audio) -> str:
    try:
        # Google's free recognizer hears one language: the one the conversation is in.
        hebrew = stt_local.BILINGUAL and language.reply_language() == "he"
        return recognizer.recognize_google(audio, language="he-IL" if hebrew else "en-US").strip()
    except sr.UnknownValueError:
        return ""


def transcribe(audio, passive=False) -> str:
    """Speech to text with a fallback engine.

    Passive (sleeping) listening hears every noise in the room, so it tries the
    free Google engine first to spare the Groq rate limit; active listening
    tries Whisper first for accuracy. Either falls back to the other on error.
    """
    last_transcription.update(started=time.time(), seconds=0.0, engine="")
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    # This computer's Whisper gets the recording as made (44.1/48 kHz): stt_local resamples it with a proper filter.
    native = audio.get_wav_data(convert_width=2)
    local = [("Local Whisper", lambda: transcribe_local(native))] if stt_local.ready() else []
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
        last_transcription.update(seconds=time.time() - last_transcription["started"], engine=name)
        if is_whisper_hallucination(text, passive):
            return ""
        # Hebrew speech: "היי ג'רביס" -> "hey Jervis"; and "hey Gravis" / "okay Gervis" -> "hey jervis": the wake
        # phrases work however the name was heard.
        return speech_fixes.fix_wake_name(nlu.latin_names(text))
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
            index = microphones.input_device_index(wanted)
            if index is not None:
                return microphones.Microphone(device_index=index)
            report_mic_problem(f"The microphone \u201c{wanted}\u201d isn't connected; using the system default.",
                               blocking=False)
        except Exception as e:
            print(f"Could not open the chosen microphone: {e}", flush=True)
    return microphones.Microphone()


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


CONTINUATION_SECONDS = 3.0   # how long a sentence cut off by a pause ("make the roof... green") is waited on


def listen_for_the_rest() -> str:
    """The rest of a sentence the speaker paused in ("put a tree next to the..." "...house"): one more short listen,
    transcribed and returned ("" if nothing more was said)."""
    if os.getenv("JERVIS_TEST_AUDIO"):
        audio = _test_recording(gap=False) if TEST_AUDIO else None
        return transcribe(audio).strip() if audio is not None else ""
    try:
        with open_microphone() as source:
            send_status("listening")
            audio = recognizer.listen(source, timeout=CONTINUATION_SECONDS, phrase_time_limit=15)
    except (sr.WaitTimeoutError, OSError):
        return ""
    except Exception as e:
        print(f"Couldn't listen for the rest: {e}", flush=True)
        return ""
    seconds = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
    if seconds < MIN_PHRASE_SECONDS or mic_muted.is_set():
        return ""
    send_status("thinking")
    return transcribe(audio).strip()


# Tests only: JERVIS_TEST_AUDIO="a.wav;b.wav" plays these recordings to the listening loop, one per listen, in
# place of the microphone — the whole voice path (wake phrase, recognition, follow-ups) runs for real, and no
# microphone is opened.
TEST_AUDIO = [p for p in (os.getenv("JERVIS_TEST_AUDIO") or "").split(";") if p]


def _test_recording(gap: bool = True):
    if not TEST_AUDIO:
        time.sleep(0.25)
        return None
    if gap:   # JERVIS_TEST_AUDIO_GAP: seconds of "silence" before each recording (a build finishing meanwhile)
        time.sleep(float(os.getenv("JERVIS_TEST_AUDIO_GAP") or 0))
    import wave
    with wave.open(TEST_AUDIO.pop(0), "rb") as wav:
        return sr.AudioData(wav.readframes(wav.getnframes()), wav.getframerate(), wav.getsampwidth())


def _recognized(audio, passive: bool):
    """The text of one captured phrase (None if too short or not understood), with a sentence cut off by a pause
    completed from the next one."""
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
    if not passive and speech_fixes.sounds_unfinished(text):
        rest = listen_for_the_rest()
        if rest:
            text = f"{text.rstrip(' ,.')} {rest}"
    print(f"Recognized: {text}")
    return text


def listen(passive=False):
    """Capture one phrase and return its text, or None if nothing usable was heard."""
    global mic_calibrated, last_calibrated_at
    if TEST_AUDIO or os.getenv("JERVIS_TEST_AUDIO"):
        audio = _test_recording()
        return _recognized(audio, passive) if audio is not None else None
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
        return _recognized(audio, passive)

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

    text = str(localized(text)).replace("`", "").strip()   # (osal picks the Hebrew voice for Hebrew text)
    send_status("speaking")
    print(f"Speaking: {text}")
    interrupt_speech.clear()
    volume = speak_volume()
    if AUDIO_OFF or speak_muted() or volume == 0:   # test mode, or the user muted/zeroed Jervis's voice
        send_status("idle")
        return

    try:
        proc = osal.speech_process(text, volume)
        if proc is not None:
            wait_for_speech(proc)
        elif get_tts_engine() is not None:
            get_tts_engine().setProperty("volume", volume / 100)
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


# ---------------------------------------------------------------- language understanding (nlu.py)
# Speech -> STT -> deterministic rewrite (Hebrew, mixed, known speech slips) -> the command handlers -> if still
# unhandled and it reads like a command: the local model's structured intent -> validated -> canonical English ->
# the same handlers. The model only ever picks from a closed set of intents; it never writes code that runs.

SAY_NOTHING = PrivateReply("")      # handle_command's answer for speech that wasn't meant for Jervis
CLARIFY_SECONDS = 90                # how long an answer to "Which colour?" still belongs to the unclear command
last_command = {"text": None, "at": 0.0}
pending_clarify = None              # {"said", "question", "at"} after Jervis asked what an unclear command meant


def language_context() -> dict:
    """What "it", "the second one", "go back" and "again" can refer to — small, so the model call stays fast."""
    context = {}
    try:
        window = app_launcher.front_app_window()
        if window:
            context["app_in_front"] = (window[2] or window[1] or "")[:60]
    except Exception:
        pass
    session = control_session if session_active() else blender_session
    if session is not None and getattr(session, "blender_objects", None):
        context["blender_objects"] = [o["name"] for o in session.blender_objects[-8:]]
        if session.blender_focus:
            context["blender_focus"] = str(session.blender_focus)[:60]
    if session_active():
        context["control_session"] = True
    if spotify_active or youtube_active:
        context["music_playing_on"] = "Spotify" if spotify_active else "YouTube"
    if last_command["text"] and time.time() - last_command["at"] < 15 * 60:
        context["last_command"] = last_command["text"][:120]
    return context


def _run_command(text):
    result = handle_direct_command(text)
    if result:
        last_command.update(text=str(text), at=time.time())
    return result


# ---------------------------------------------------------------- other languages (language.py)
# A request in Hebrew (or Hebrew mixed with English) is translated into English here, before anything else sees it,
# so every command, the Blender and code agents, the chat and its tools, follow-ups and corrections work exactly as
# they do in English; the reply is translated back when it's shown and spoken (localized). The window shows the
# words as said, and the log keeps them next to the English.
CONFIRM_SECONDS = 90
pending_translation = None   # {"english", "input", "at"} while Jervis asks whether he understood a request right
last_request = {"text": "", "at": 0.0}   # the last request, in English: helps read a follow-up or a correction


current_turn = {"language": "en", "original": "", "translated": False}   # how this turn was said (see main_loop)


class TurnTimer:
    """One line per request in the log, written when Jervis is back to listening: where its time went, stage by
    stage, from the end of the speech to the end of the spoken answer (never the words said or answered)."""

    def __init__(self):
        self.count = 0
        self.open = False
        self.stages = []

    def start(self, how: str, began: float, waiting: str = "") -> None:
        self.finish()
        self.count += 1
        self.open, self.began, self.how, self.waiting, self.stages = True, began, how, waiting, []

    def mark(self, stage: str, seconds: float, note: str = "") -> None:
        if self.open:
            self.stages.append((stage, seconds, note))

    def timed(self, stage: str, note: str = ""):
        timer, started = self, time.time()

        class _Stage:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                timer.mark(stage, time.time() - started, note)
        return _Stage()

    def finish(self) -> None:
        if not self.open:
            return
        self.open = False
        parts = " · ".join(f"{name} {seconds:.1f}s" + (f" ({note})" if note else "") for name, seconds, note
                           in self.stages)
        busy = []
        if control_active():
            busy.append("computer task running")
        if code_task is not None and code_task.state not in ("completed", "error", "stopped"):
            busy.append("program task running")
        print(f"Turn {self.count} ({self.how}, {current_turn['language']}): {parts} · total "
              f"{time.time() - self.began:.1f}s" + (f" [{'; '.join(busy)}]" if busy else "") +
              (f" [{self.waiting}]" if self.waiting else ""), flush=True)


turn_timer = TurnTimer()
last_transcription = {"started": 0.0, "seconds": 0.0, "engine": ""}   # the speech just heard (see transcribe)

HEBREW_CHAT_PROMPT = (   # (for talk in English too: see answer_in_users_language)
    "You are Jervis, a friendly voice assistant on the user's computer, talking with the user in {name}. Answer in "
    "natural, correct {name}, speaking about yourself in the masculine, briefly - one to three sentences - unless "
    "the user asks for more. You can't see the screen, the user's messages or files from here: never claim you did, "
    "opened, played or changed anything.")


def answer_in_users_language(messages: list, english: str):
    """Plain talk — no tool to use, no numbers to verify, no picture — answered in one call by the bilingual model
    DictaLM, without swapping models on an 8 GB GPU (each swap: a reload of several seconds, and the coder model's
    long prompt re-read; measured up to 150 s when part of it had to run on the CPU):
      - in Hebrew, from the Hebrew as said, in place of translate -> chat model -> translate back;
      - in English, when DictaLM is the model loaded right now (a Hebrew conversation) and the chat model isn't.
    None: the usual path answers (commands, tools, maths, pictures, the online AI, or no DictaLM)."""
    if not local_llm_only():
        return None
    model = local_llm.role_model("hebrew") or ""
    if "dictalm" not in model.lower():   # another model's Hebrew is worse than a translated answer
        return None
    hebrew_turn = current_turn["translated"] and current_turn["language"] in language.LANGUAGES
    if not hebrew_turn and not (current_turn["language"] == "en" and local_llm.is_loaded(model)
                                and not local_llm.is_loaded(local_llm.role_model("chat") or "")):
        return None
    if select_tools(english)[0] or reasoning.looks_quantitative(english) or images.context_note():
        return None
    lang = language.LANGUAGES[current_turn["language"]] if hebrew_turn else None
    recent = [m for m in messages[1:-1] if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
              and m.get("content") != PRIVATE_PLACEHOLDER][-6:]
    talk = ([{"role": "system", "content": HEBREW_CHAT_PROMPT.format(name=lang.name if lang else "English")}] +
            recent + [{"role": "user", "content": current_turn["original"] if lang else english}])
    try:
        response = local_llm.chat(role="hebrew" if lang else "translate", messages=talk, max_tokens=300,
                                  temperature=0.5)
    except Exception as e:
        print(f"The bilingual model couldn't answer ({str(e)[:100]}); answering the usual way.", flush=True)
        return None
    reply = (response.choices[0].message.content or "").strip()
    if lang:
        return reply if re.search(f"[{lang.letters}]", reply) else None
    return reply if reply and not osal.has_hebrew(reply) else None


def _same_kind(original, text: str):
    """`text` as the same kind of input as `original` (an image's caption, a phone's voice input...)."""
    if type(original) is str or not isinstance(original, str):
        return text
    out = str.__new__(type(original), text)
    out.__dict__.update(getattr(original, "__dict__", {}))
    return out


def _answer_now(reply, typed) -> None:
    broadcast("ai", reply)
    reply_to_phone_if_needed(typed, str(reply))
    speak(spoken_version(reply))


def understand_language(text, typed=None):
    """The request in English for the rest of Jervis, or None when Jervis has already answered it himself (he asked
    whether he understood it right, or to hear it again). English passes through untouched."""
    global pending_translation
    current_turn.update(language="en", original=str(text), translated=False)
    pending, pending_translation = pending_translation, None
    if pending and time.time() - pending["at"] > CONFIRM_SECONDS:
        pending = None
    previous = last_request["text"] if time.time() - last_request["at"] < 10 * 60 else ""
    try:
        heard = language.to_english(str(text), previous)
    except Exception:   # never lose a request to a bug here: it goes on as said
        traceback.print_exc()
        return text
    if heard.status != "same":
        print(heard.log_line(), flush=True)
    current_turn.update(language=heard.language, original=heard.original, translated=heard.translated)
    turn_timer.mark("understand", heard.seconds, heard.method or heard.status)
    switch_to = language.turn_language(str(text))
    if switch_to:
        language.set_reply_language(switch_to)
        stt_local.prefer(switch_to)   # that language's speech model on the GPU from now on (the other one leaves)
    if pending:   # the answer to "did I understand you right?"
        answer = " ".join(re.sub(r"[^a-z' ]", " ", (heard.english or "").lower()).split())
        answer = re.sub(r"\s+(?:thanks|thank you|please)$", "", answer)
        if _YES.fullmatch(answer):
            print(f"Confirmed: {pending['english']!r}", flush=True)
            last_request.update(text=pending["english"], at=time.time())
            return _same_kind(pending["input"], pending["english"])
        if _NO.fullmatch(answer):
            _answer_now(language.phrase("Okay, I didn't do anything. Say it again in other words?"), typed)
            return None
        # anything else is a new request
    if heard.status == "unclear":
        _answer_now(language.phrase("Sorry, I didn't catch that. Could you say it again?"), typed)
        return None
    if heard.status == "confirm":
        pending_translation = {"english": heard.english, "input": text, "at": time.time()}
        shown, spoken = language.confirm_question(heard)
        question = SpokenReply(shown)
        question.spoken = spoken
        _answer_now(question, typed)
        return None
    if heard.status == "unavailable" and heard.error:
        # The translator failed (timed out, stopped): say so now. Handing the untranslated words on would only queue
        # more calls to the same struggling local AI (that once made one sentence take two minutes).
        _answer_now(language.phrase("Sorry, my local AI didn't answer in time. Please try again in a moment.",
                                    heard.language), typed)
        return None
    if heard.status == "unavailable":
        # No translator (still downloading, or the local AI isn't running): as before, the words go on as they
        # were said — the Hebrew command rules, the online AI and the local Hebrew model still understand much of it.
        return text
    if heard.method != "answer":
        last_request.update(text=heard.english, at=time.time())
    return _same_kind(text, heard.english) if heard.translated else text


def handle_command(text, typed: bool = False):
    """A reply when Jervis handled `text` as a command (or asked what it meant), SAY_NOTHING for background speech,
    None for conversation (the chat model answers it, as before)."""
    global pending_clarify, last_turn_typed
    last_turn_typed = typed
    if isinstance(text, ImageCaption):
        return handle_direct_command(text)
    pending, pending_clarify = pending_clarify, None
    if pending and time.time() - pending["at"] > CLARIFY_SECONDS:
        pending = None
    rewritten = nlu.rewrite(text)
    for candidate in ([rewritten] if rewritten else []) + [text]:
        result = _run_command(candidate)
        if result:
            if rewritten and candidate == rewritten:
                print(f"Understood {text!r} as {rewritten!r}", flush=True)
            return result
    if pending and len(text.split()) <= 8 and not nlu.has_hebrew(text):   # "make it" ... "Which way?" ... "taller"
        result = _run_command(f"{pending['said']} {text}")
        if result:
            return result
    # A bare "taller" / "to the left" while working in Blender is a follow-up, not chat: the chat model can't act,
    # and once answered "Done — it's taller now" for a change that never happened.
    follow_up = len(text.split()) <= 4 and time.time() - blender_last_used < BLENDER_RECENT_SECONDS
    if is_shutdown_command(text) or not (pending or follow_up or nlu.worth_understanding(text)):
        return None
    context = language_context()
    if pending:
        context.update(unclear_command=pending["said"], you_asked=pending["question"])
    started = time.time()
    try:
        kind, value = nlu.interpret(text, context, local_llm.chat_json)
    except Exception as e:   # no local AI (or it failed): the chat path answers, and says so if the AI is down
        print(f"Language understanding unavailable: {str(e)[:120]}", flush=True)
        return None
    print(f"Understood {text!r} as {kind}: {value!r} ({time.time() - started:.1f}s)", flush=True)
    if kind == "command":
        # English requests for computer control already reach the chat model, which has the control tool and more
        # (WhatsApp, documents...): only take them over for Hebrew, which used to have no way in.
        if not nlu.has_hebrew(text) and value.startswith(("use my computer to ", "take control of my computer and ")):
            return None
        return _run_command(value)
    if kind == "clarify":
        said = f"{pending['said']} {text}" if pending else text
        pending_clarify = {"said": said, "question": value, "at": time.time()}
        return value
    if kind == "ignore" and not typed:
        return SAY_NOTHING
    return None


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
        turn_timer.finish()   # the last request's timing line, now that Jervis is back to listening
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
            waiting = typed_inputs.qsize()
            turn_timer.start("typed", time.time(), f"{waiting} more typed lines waiting" if waiting else "")
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
                if not (text and is_wake_command(text)):
                    continue
                awake = True
                show_fullscreen()
                command = after_wake_phrase(text)
                if not command:   # just "Hey Jervis": greet, and listen for the request
                    greeting = time_greeting()
                    broadcast("ai", greeting)
                    speak(greeting)
                    continue
                # "Hey Jervis, create a house" in one breath: the request is handled right away, not dropped
                text = command
                send_status("thinking")
            else:
                text = listen()
                if not text:
                    continue

        if not typed:   # from the end of the speech: recognising it is part of the wait
            turn_timer.start("spoken", last_transcription["started"] or time.time())
            turn_timer.mark("stt", last_transcription["seconds"], last_transcription["engine"])
        if not isinstance(text, ImageCaption):  # already shown together with the image itself, in handle_client
            broadcast("user", text)
        if not typed:
            text = fix_names(text) or text  # "Streamio", "Stream here" -> "stremio", etc.
            if is_explicit_wake(text):  # "Hey Jervis" while already awake: bring the window up, full screen
                reopened = not window_visible
                show_fullscreen()
                here = time_greeting() if reopened else "I'm here."
                broadcast("ai", here)
                speak(here)
                continue

        english = understand_language(text, typed)   # Hebrew -> English (or a question back, then None)
        if english is None:
            continue
        text = english

        turn_started = time.time()
        try:
            with turn_timer.timed("command"):
                direct_result = handle_command(text, typed=bool(typed))
        except Exception:
            # A bug in one command must never take the whole assistant down.
            traceback.print_exc()
            direct_result = "Sorry, something went wrong with that command."
        if direct_result is SAY_NOTHING:
            print(f"Not for me, staying quiet: {text!r}", flush=True)
            send_status("idle")
            continue
        if direct_result:
            with turn_timer.timed("reply-translate"):
                shown = localized(direct_result)   # in the user's language; the AI remembers the English
            broadcast("ai", shown)
            reply_to_phone_if_needed(typed, str(shown))
            remember_turn(messages, text, str(direct_result), turn_started, private=isinstance(direct_result, PrivateReply))
            with turn_timer.timed("speak"):
                speak(spoken_version(shown))
            continue

        if is_shutdown_command(text):
            goodbye = localized(farewell_reply(text))
            broadcast("ai", goodbye)
            reply_to_phone_if_needed(typed, goodbye)
            speak(goodbye)
            awake = False
            send_status("sleeping")
            continue

        messages.append({"role": "user", "content": text})
        image_note = images.context_note()
        if image_note:
            messages.append({"role": "system", "content": image_note})
        try:
            asked = time.time()
            direct = answer_in_users_language(messages, text)   # Hebrew talk: no swap, no translation back
            if direct is not None:
                turn_timer.mark("answer", time.time() - asked, "bilingual model, no swap")
            else:
                with turn_timer.timed("answer", "chat"):
                    direct = ask_jervis(messages, text)
            reply = tidy_math(direct)
            if len(reply) > 40:
                last_llm_reply = {"text": reply, "at": time.time(), "question": text}
                note_suggestions(reply)
        except Exception:
            traceback.print_exc()
            reply = "Sorry, something went wrong. Please try again."
        messages.append({"role": "assistant", "content": reply})
        with turn_timer.timed("reply-translate"):
            shown = localized(reply)
        broadcast("ai", shown)
        reply_to_phone_if_needed(typed, str(shown))
        with turn_timer.timed("speak"):
            speak(spoken_version(shown))


def greet_after_voice_launch() -> None:
    """Jervis was opened by saying "Hey Jervis" while he was closed (see wake/jervis_wake.py): once his window is up,
    show it and answer, then listen for the command right away."""
    global awake
    awake = True
    deadline = time.time() + 25
    while not connected_clients and time.time() < deadline:   # the window starts alongside the engine
        time.sleep(0.2)
    show_fullscreen()
    greeting = time_greeting()
    broadcast("ai", greeting)
    speak(greeting)


def greet_on_startup() -> None:
    """Opened normally (double-clicked, or the window started the backend): once the window is up, greet and start
    awake, so you can talk right away instead of having to say a wake phrase first."""
    global awake
    deadline = time.time() + 25
    while not connected_clients and time.time() < deadline:   # the window starts alongside the engine
        time.sleep(0.2)
    if not connected_clients:   # started headless (no window): stay asleep, the wake phrase still works
        return
    awake = True
    greeting = time_greeting()
    broadcast("ai", greeting)
    speak(greeting)


def set_window_visible(visible: bool) -> None:
    """Closing the window puts Jervis back to sleep: he keeps listening, and the wake phrase opens him again. (Not
    while he's using the computer: then his window only steps aside.)"""
    global window_visible, awake
    window_visible = visible
    if not visible and not control_active() and not session_active():
        awake = False


def watch_parent_window() -> None:
    """The engine never outlives its window. If the window is ended without being able to stop the engine (Task
    Manager, a crash, an installer ending it), the engine would otherwise keep listening with nothing on screen."""
    try:
        window = psutil.Process(int(os.getenv("JERVIS_PARENT_PID") or 0))
    except (ValueError, psutil.Error):
        return
    while True:
        time.sleep(2)
        if not window.is_running():   # (also false if the id now belongs to another program)
            print("Jervis's window is gone, so the engine is stopping too.", flush=True)
            shutdown_now()


def shutdown_now() -> None:
    """Stop what Jervis started (a computer-control task, his local AI) and exit, from any thread."""
    try:
        if computer_task is not None:
            computer_task.stop()
        if session_active():
            end_control_session()
        local_ai_manager.stop()
    except Exception:
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:   # an installed copy checking it has every part (see selftest.py)
        import selftest
        sys.exit(selftest.run())
    # The window stops the backend with SIGTERM: turn that into a normal exit, so cleanups (the local AI engine Jervis
    # started) run instead of leaving it behind.
    signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
    if SUPERVISED and os.getenv("JERVIS_PARENT_PID"):
        threading.Thread(target=watch_parent_window, daemon=True, name="parent-watch").start()
    ws_thread = threading.Thread(target=run_ws_server, daemon=True)
    ws_thread.start()
    ws_loop_ready.wait()

    if phone_control_mode() != "off":
        threading.Thread(target=run_phone_server, daemon=True, name="phone-control").start()
        if RELAY_URL:
            threading.Thread(target=relay_client.run_relay_client, args=(relay,), daemon=True,
                             name="phone-relay").start()

    threading.Thread(target=check_ai_connection, daemon=True).start()
    threading.Thread(target=refresh_devices, daemon=True).start()   # so Settings has them ready
    if LLM_BACKEND in ("ollama", "auto") and os.getenv("JERVIS_NO_AI_SETUP") != "1":   # (that switch: tests only)
        local_ai_manager.start_background()   # the local AI is the AI, or the backup: make sure it's there
    timer_manager.load()  # timers that were running when Jervis was last closed
    threading.Thread(target=telemetry_loop, daemon=True).start()
    threading.Thread(target=weather_loop, daemon=True).start()
    threading.Thread(target=_install_blender_bridge, daemon=True, name="blender-startup-script").start()
    def warm_up():   # the speech models, then the local AI model needed first, so the first sentence doesn't wait
        if not AUDIO_OFF or TEST_AUDIO:
            stt_local.prefer(language.reply_language(), background=False)   # the language last spoken
            stt_local.preload()   # first: the AI model's GPU plan has to count the speech models' memory
        if LLM_BACKEND in ("ollama", "auto"):
            local_llm.warm_up(local_ai.first_role())
    threading.Thread(target=warm_up, daemon=True, name="warm-up").start()
    if stt_local.BILINGUAL:   # the Hebrew voice (CPU, ~3 s to load): ready before the first Hebrew answer
        import hebrew_voice
        threading.Thread(target=hebrew_voice.preload, daemon=True, name="hebrew-voice-preload").start()
    if os.getenv("JERVIS_SHOW_WINDOW") == "1":  # started with run.py: show the window right away, not only after "Hey Jervis"
        launch_ui()

    if os.environ.pop("JERVIS_WOKEN_BY_VOICE", "") == "1":   # opened by Jervis Wake (wake/): greet right away
        greet_after_voice_launch()
    else:
        greet_on_startup()   # opened normally: greet once the window connects, and start awake right away

    try:
        main_loop()
    except KeyboardInterrupt:
        print("\nShutting down.")
        