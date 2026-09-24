"""Jervis's settings: one JSON file in the user's data folder, edited from the Settings screen.

Every setting is named after the environment variable the rest of Jervis already reads (GROQ_API_KEY, LLM_BACKEND,
...), and load() applies the saved values to os.environ. So every existing os.getenv() keeps working unchanged, and
a developer's .env file keeps working too.

Precedence, highest first:
  1. variables already set in the real environment when Jervis starts (a developer's shell, tests)
  2. settings.json (what the user chose in the Settings screen)
  3. .env (the old way of configuring Jervis; still read, and imported into settings.json the first time)
  4. the defaults below

The file is versioned so later releases can migrate it, and a damaged file is set aside (never silently lost) and
replaced by defaults, so Jervis always starts.
"""
import json
import os
import shutil
import tempfile
import threading
import time

import paths

VERSION = 1
FILE_NAME = "settings.json"

# The Settings screen is built from this list, so a new setting only needs adding here.
#   restart: the backend restarts to apply it (it's read once at startup)
#   secret: never sent back to the window in full, only whether it is set
SCHEMA = [
    # --- AI ---
    {"key": "LLM_BACKEND", "section": "AI", "label": "Which AI answers", "type": "choice", "default": "ollama",
     "choices": [["ollama", "Local AI on this computer (no account needed)"],
                 ["auto", "Online AI (Groq), with the local AI as backup"],
                 ["groq", "Online AI (Groq) only"]],
     "restart": True},
    {"key": "GROQ_API_KEY", "section": "AI", "label": "Groq API key (optional)", "type": "secret", "default": "",
     "help": "Only for the online AI: faster and smarter answers. Free at console.groq.com.", "restart": True},
    {"key": "OLLAMA_MODEL", "section": "AI", "label": "Local AI model", "type": "text", "default": "llama3.2",
     "help": "On a slower computer, llama3.2:1b answers faster.", "restart": True, "advanced": True},
    {"key": "JERVIS_LOCAL_VISION", "section": "AI", "label": "Let the local AI see pictures and the screen",
     "type": "choice", "default": "auto",
     "choices": [["auto", "Automatic (computers with 16 GB of memory or more)"], ["on", "On"], ["off", "Off"]],
     "help": "Needs a 3 GB download and plenty of free memory.", "restart": True, "advanced": True},
    {"key": "OLLAMA_VISION_MODEL", "section": "AI", "label": "Local vision model", "type": "text",
     "default": "qwen2.5vl:3b", "help": "Lets the local AI see pictures and the screen.", "restart": True,
     "advanced": True},
    # --- Voice ---
    {"key": "JERVIS_MIC", "section": "Voice", "label": "Microphone", "type": "device", "default": "",
     "help": "Leave on System default unless Jervis can't hear you."},
    {"key": "JERVIS_VOICE", "section": "Voice", "label": "Jervis's voice", "type": "voice", "default": ""},
    {"key": "JERVIS_WAKE_WORD", "section": "Voice", "label": "Wait for “Hey Jervis”", "type": "toggle",
     "default": "on", "help": "Off: Jervis listens all the time while the microphone is on."},
    # --- Computer control ---
    {"key": "JERVIS_COMPUTER_CONTROL", "section": "Computer control", "label": "Let Jervis use the mouse and keyboard",
     "type": "choice", "default": "ask",
     "choices": [["ask", "Ask me before each task"], ["on", "Allowed (still asks before risky steps)"],
                 ["off", "Never"]]},
    # --- General ---
    {"key": "WEATHER_CITY", "section": "General", "label": "Weather city", "type": "text", "default": "",
     "help": "For the weather panel, e.g. Tel Aviv or London."},
    {"key": "JERVIS_KEEP_TRANSCRIPTS", "section": "Privacy", "label": "Keep conversation logs on this computer",
     "type": "toggle", "default": "on"},
    {"key": "WHATSAPP_READING", "section": "Privacy", "label": "Let Jervis read WhatsApp (macOS)", "type": "toggle",
     "default": "on", "restart": True},
    # --- Optional services ---
    {"key": "OPENAI_API_KEY", "section": "Optional services", "label": "OpenAI API key", "type": "secret",
     "default": "", "help": "Better pictures, and editing pictures.", "restart": True},
    {"key": "SPOTIFY_CLIENT_ID", "section": "Optional services", "label": "Spotify client ID", "type": "text",
     "default": "", "restart": True, "advanced": True,
     "help": "Create an app at developer.spotify.com/dashboard with the redirect URI http://localhost:8888/callback. "
             "Needs Spotify Premium."},
    {"key": "SPOTIFY_CLIENT_SECRET", "section": "Optional services", "label": "Spotify client secret",
     "type": "secret", "default": "", "restart": True, "advanced": True},
    {"key": "GOOGLE_ACCOUNT_LEARNING", "section": "Optional services", "label": "School Google account",
     "type": "text", "default": "", "advanced": True,
     "help": "The name of its Chrome profile, so school things open in the right account."},
    {"key": "GOOGLE_ACCOUNT_PERSONAL", "section": "Optional services", "label": "Personal Google account",
     "type": "text", "default": "", "advanced": True},
    {"key": "GOOGLE_CALENDAR_CLIENT_ID", "section": "Optional services", "label": "Google Calendar client ID",
     "type": "text", "default": "", "restart": True, "advanced": True,
     "help": "A free Desktop app OAuth client from console.cloud.google.com, with the Calendar API turned on."},
    {"key": "GOOGLE_CALENDAR_CLIENT_SECRET", "section": "Optional services", "label": "Google Calendar client secret",
     "type": "secret", "default": "", "restart": True, "advanced": True},
]
BY_KEY = {item["key"]: item for item in SCHEMA}
_lock = threading.Lock()
_values = {}          # what settings.json holds (only keys the user or the .env import set)
_from_env_file = {}   # what .env holds
_process_env = set()  # keys that were already in the real environment at startup: they always win


def path() -> str:
    return os.path.join(paths.DATA_DIR, FILE_NAME)


def _parse_env_file(file_path: str) -> dict:
    values = {}
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip()
                value = value.split(" #", 1)[0].strip().strip("\"'")
                if key:
                    values[key] = value
    except (OSError, UnicodeDecodeError):
        pass
    return values


def migrate(data: dict) -> dict:
    """Bring an older settings file up to VERSION. Keys are never dropped, so nothing the user set is lost."""
    version = int(data.get("version", 0) or 0)
    values = dict(data.get("values", {}))
    if version < 1:
        values = {k: v for k, v in data.items() if k != "version"} if "values" not in data else values
    # Future: if version < 2: rename or convert keys here.
    return {"version": VERSION, "values": {k: str(v) for k, v in values.items() if isinstance(k, str)}}


def _read_file() -> dict:
    file_path = path()
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        return migrate(data)["values"]
    except (OSError, ValueError, TypeError) as e:
        backup = f"{file_path}.damaged-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.move(file_path, backup)
        except OSError:
            backup = "(could not be moved)"
        print(f"Settings file was damaged ({e}); kept a copy at {backup} and started from defaults.", flush=True)
        return {}


def _write_file(values: dict) -> None:
    """Atomic: a crash or power cut mid-save never leaves a half-written settings file."""
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=paths.DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "values": values}, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path())
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load() -> None:
    """Read everything and apply it to os.environ. Call once, before the rest of Jervis reads its configuration."""
    global _values, _from_env_file, _process_env
    with _lock:
        _process_env = {k for k in os.environ}
        env_files = [os.path.join(paths.RESOURCE_DIR, ".env"), os.path.join(paths.DATA_DIR, ".env")]
        _from_env_file = {}
        for file_path in dict.fromkeys(env_files):   # the same folder when running from source
            _from_env_file.update(_parse_env_file(file_path))
        first_run = not os.path.exists(path())
        _values = _read_file()
        if first_run and _from_env_file:
            # First start with this settings system: keep what the user already configured in .env.
            imported = {k: v for k, v in _from_env_file.items() if k in BY_KEY and v}
            _values.update(imported)
            if not _values.get("LLM_BACKEND") and _values.get("GROQ_API_KEY"):
                _values["LLM_BACKEND"] = "auto"   # someone with a key keeps the online AI they were using
            if not paths.FROZEN:
                # Upgrading a copy that ran from source: its weather panel always showed Ramat Gan; keep that.
                _values.setdefault("WEATHER_CITY", "Ramat Gan, Israel")
            try:
                _write_file(_values)
            except OSError as e:
                print(f"Could not save the settings file: {e}", flush=True)
        _apply()


def _effective(key: str) -> str:
    if key in _process_env and key in os.environ:
        return os.environ[key]
    if key in _values:
        return _values[key]
    if key in _from_env_file:
        return _from_env_file[key]
    item = BY_KEY.get(key)
    return item["default"] if item else ""


def _apply() -> None:
    for key in set(BY_KEY) | set(_from_env_file) | set(_values):
        if key in _process_env:
            continue
        value = _effective(key)
        if value == "" and key not in BY_KEY:
            continue
        os.environ[key] = value


def get(key: str) -> str:
    with _lock:
        return _effective(key)


def validate(key: str, value) -> str:
    """The cleaned value, or raises ValueError with a message fit to show the user."""
    item = BY_KEY.get(key)
    if item is None:
        raise ValueError(f"unknown setting {key!r}")
    value = "" if value is None else str(value).strip()
    if len(value) > 500:
        raise ValueError(f"{item['label']} is too long")
    if item["type"] == "choice" and value not in [c[0] for c in item["choices"]]:
        raise ValueError(f"{item['label']}: choose one of the listed options")
    if item["type"] == "toggle" and value not in ("on", "off"):
        raise ValueError(f"{item['label']} must be on or off")
    if any(ch in value for ch in "\r\n\0"):
        raise ValueError(f"{item['label']} can't contain line breaks")
    return value


def update(changes: dict) -> dict:
    """Validate and save several settings at once. Returns {"saved": [...], "restart": bool}; raises ValueError (and
    saves nothing) if any value is invalid."""
    changes = {key: value for key, value in (changes or {}).items()
               # public_view() shows a stored secret as "set"; sending that back means "unchanged", not the word "set"
               if not (BY_KEY.get(key, {}).get("type") == "secret" and value == "set")}
    cleaned = {key: validate(key, value) for key, value in changes.items()}
    with _lock:
        before = {key: _effective(key) for key in cleaned}
        _values.update(cleaned)
        _write_file(_values)
        _process_env.difference_update(cleaned)   # a value chosen in Settings now beats the startup environment
        _apply()
        changed = [key for key in cleaned if before[key] != cleaned[key]]
    return {"saved": changed, "restart": any(BY_KEY[k].get("restart") for k in changed)}


def public_view() -> dict:
    """What the Settings screen needs: the schema and current values, with secrets reduced to "is it set"."""
    with _lock:
        values = {}
        for item in SCHEMA:
            value = _effective(item["key"])
            values[item["key"]] = ("set" if value else "") if item["type"] == "secret" else value
        return {"schema": SCHEMA, "values": values, "file": path()}
