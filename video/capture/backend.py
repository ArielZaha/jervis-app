"""The real Jarvis engine (app.py), made safe to film.

It is the same code that runs behind the window, started the way the window starts it. Three things differ, so that
recording never touches the computer it runs on or anyone's accounts:

  * acting on the computer is recorded instead of done: starting programs, AppleScript, opening web pages, driving
    Spotify (tests/sandbox.py does this for the test suite; the network stays on here, for weather and place lookups)
  * there is no microphone and no voice. A spoken phrase is handed to the main loop through the same door the
    microphone uses (listen), on request: GET /say?text=...   then /heard when the "speaking" should end.
  * Jarvis's own voice is silent; the "speaking" state lasts until GET /hush (the recorder decides how long).

Nothing here changes what Jarvis answers: every reply in the footage is produced by app.py.

  PORT=18940 CTRL=18941 venv/bin/python video/capture/backend.py
"""
import json
import os
import queue
import runpy
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "video", "cache.nosync", "data")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)

shutil.rmtree(DATA, ignore_errors=True)   # every recording starts from a clean, empty Jarvis: no personal history
os.makedirs(DATA)
os.environ["JARVIS_DATA_DIR"] = DATA
os.environ["CODE_PROJECTS_DIR"] = os.path.join(DATA, "projects")   # code written during a recording stays in the demo folder
import sandbox   # noqa: E402  (sets the test defaults; the ones a film needs differently are put back below)
import requests  # noqa: E402

_real_requests = {name: getattr(requests, name) for name in ("get", "post", "put", "delete", "head")}
_real_session_request = requests.Session.request
sandbox.install()
for name, function in _real_requests.items():   # the network stays: weather, place lookups, pictures
    setattr(requests, name, function)
requests.Session.request = _real_session_request

with open(os.path.join(DATA, "settings.json"), "w", encoding="utf-8") as f:   # not a first start: no welcome screen
    json.dump({"version": 1, "values": {"JARVIS_WAKE_WORD": os.environ.get("DEMO_WAKE", "off")}}, f)

os.environ.pop("GROQ_API_KEY", None)             # the online AI answers, with the key from Settings / .env
os.environ.update({"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""})   # nothing paid: pictures come from the free service
os.environ.update({
    "LLM_BACKEND": os.environ.get("DEMO_AI", "groq"), "JARVIS_NO_AI_SETUP": "1", "JARVIS_AUDIO": "off", "JARVIS_SUPERVISED": "1",
    "JARVIS_WS_PORT": os.environ.get("PORT", "18940"), "JARVIS_WS_TOKEN": "",
    "SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": "",
    "JARVIS_USER_NAME": os.environ.get("DEMO_NAME", ""), "WEATHER_CITY": os.environ.get("DEMO_CITY", "London"),
    "JARVIS_PHONE_CONTROL": os.environ.get("DEMO_PHONE", "off"), "JARVIS_PHONE_PORT": os.environ.get("PHONE_PORT", "18942"),
    "JARVIS_RELAY_URL": os.environ.get("RELAY", ""), "JARVIS_WAKE_WORD": os.environ.get("DEMO_WAKE", "off"),
    "GOOGLE_ACCOUNT_LEARNING": "", "GOOGLE_ACCOUNT_PERSONAL": "",
})

voice = queue.Queue()            # phrases "said" to Jarvis
heard = threading.Event()        # the phrase has been said
hush = threading.Event()         # Jarvis has finished saying his reply
state = {"speaking": False, "said": []}


def patch(main) -> None:
    def listen(passive=False):
        try:
            text = voice.get(timeout=0.25)
        except queue.Empty:
            return None
        heard.clear()
        if not passive:               # asleep, he listens for his name without showing it: the window stays "Sleeping"
            main.send_status("listening")
        heard.wait(timeout=60)
        if not passive:
            main.send_status("thinking")
        return text

    def speak(text):
        if not text or not str(text).strip():
            return
        state["said"].append(str(text).strip())
        hush.clear()
        state["speaking"] = True
        main.send_status("speaking")
        main.interrupt_speech.clear()
        deadline = time.time() + 90
        while time.time() < deadline and not hush.is_set() and not main.interrupt_speech.is_set():
            time.sleep(0.03)
        state["speaking"] = False
        main.send_status("idle")

    main.listen, main.speak = listen, speak

    # Computer control never really starts while filming. The request, the question on screen and the click on Allow
    # are all real; what would follow (Jarvis looking at the screen and moving the mouse) is held back here.
    ask_for_real = main.ask_control_question

    def ask_then_hold(question, timeout=90.0):
        answer = ask_for_real(question, timeout)
        state["control_answer"] = answer
        while True:
            time.sleep(1)

    main.ask_control_question = ask_then_hold

    # A stand-in for the Spotify app: it "starts playing" once Jarvis has searched it, as the real app does.
    import spotify_local
    player = {"playing": False}
    track = os.environ.get("DEMO_TRACK", "No Surprises by Radiohead")
    keys_for_real = spotify_local._mac_keys

    def keys(*pressed):
        keys_for_real(*pressed)
        if pressed == ("shift", "enter"):
            player["playing"] = True

    spotify_local._mac_keys = keys
    spotify_local._mac_now = lambda: ("playing", "spotify:track:demo", track) if player["playing"] else ("paused", "", "")
    spotify_local.running = lambda: True

    # A stand-in for the browser: the new Google Doc "takes" the text, as it does when Chrome is really there.
    import documents
    documents._paste_into_new_google_doc = lambda: True
    documents.update = lambda app_key, ref, title, body: ref
    print("demo backend: voice and speech are staged; actions are recorded, not done", flush=True)


def wait_and_patch() -> None:
    while True:
        main = sys.modules.get("__main__")
        if main is not None and hasattr(main, "greet_on_startup") and hasattr(main, "main_loop"):
            patch(main)
            return
        time.sleep(0.02)


class Control(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        main = sys.modules.get("__main__")
        out = {"ok": True}
        if url.path == "/say":
            voice.put(query.get("text", ""))
        elif url.path == "/heard":
            heard.set()
        elif url.path == "/hush":
            hush.set()
        elif url.path == "/state":
            out.update(speaking=state["speaking"], said=state["said"][-3:], actions=sandbox.actions[-40:])
        elif url.path == "/ui":      # a message to the window, exactly as the engine sends them
            main.send_ui_update_once(json.loads(query["json"]))
        elif url.path == "/call":    # run one of the engine's own functions by name (staging a state it really has)
            result = getattr(main, query["fn"])(*json.loads(query.get("args", "[]")))
            out["result"] = result if isinstance(result, (str, int, float, bool, type(None), list, dict)) else str(result)
        elif url.path == "/pair":    # what "connect my phone" shows: the link in the QR code
            main.start_phone_pairing()
            out.update(main.latest_ui_updates.get("phone_pairing", {}).get("data", {}))
        elif url.path == "/doc":     # the document Jarvis last wrote (the film sets it as a page)
            out.update(doc=getattr(main, "last_document", None))
        elif url.path == "/quit":
            threading.Timer(0.2, lambda: os._exit(0)).start()
        body = json.dumps(out, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


threading.Thread(target=wait_and_patch, daemon=True).start()
control = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("CTRL", "18941"))), Control)
threading.Thread(target=control.serve_forever, daemon=True).start()
sys.argv = [os.path.join(ROOT, "app.py")]
runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
