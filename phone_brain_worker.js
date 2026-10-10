// Jarvis's brain on the phone. Runs in a worker of the phone app (phone_client.html): Python itself (Pyodide), with
// the very modules Jarvis uses on the computer loaded into it (the list is BRAIN in phone_visuals.py), so a graph, a
// worked equation, a route on the globe, a planet, the weather or a timer is read and answered here exactly as on
// the computer, with no computer needed. See phone_brain.py for what it answers and what it leaves to the app.
//
// The app posts {id, text, settings}; this posts back {id, result} (phone_brain.handle's answer), or {id, error}.
// Once, when everything is loaded: {ready: true}, or {failed: "why"} if this phone's browser can't run it.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const SOURCES = ["typos.py", "functions.py", "equations.py", "graphs.py", "geo.py", "earth.py", "planets.py", "timers.py",
                 "forecast.py", "music.py", "phone_brain.py"];
const DATA = ["geo_data/countries_50m.json", "geo_data/places_10m.json"];

// What the modules expect around them on the computer, in their phone form: where bundled files are, and the
// internet (the browser's own, asked synchronously, which a worker may do without freezing the app).
const SHIMS = {
  "paths.py": `import os
DATA_DIR = "/brain/data"
def resource(*parts): return os.path.join("/brain", *parts)
def data(*parts): return os.path.join(DATA_DIR, *parts)
def data_dir(*parts):
    path = os.path.join(DATA_DIR, *parts)
    os.makedirs(path, exist_ok=True)
    return path
`,
  "osal.py": "IS_MAC = False\nIS_WINDOWS = False\n",
  "requests.py": `import json as _json
from urllib.parse import urlencode
from js import XMLHttpRequest

class RequestException(Exception): pass
class Timeout(RequestException): pass
class ConnectionError(RequestException): pass
class HTTPError(RequestException): pass

class exceptions:
    RequestException, Timeout, ConnectionError, HTTPError = RequestException, Timeout, ConnectionError, HTTPError

class _Response:
    def __init__(self, status, text):
        self.status_code, self.text, self.ok = status, text, 200 <= status < 400
        self.content = text.encode("utf-8")
    def json(self): return _json.loads(self.text)
    def raise_for_status(self):
        if not self.ok: raise HTTPError(f"HTTP {self.status_code}")

def get(url, params=None, headers=None, timeout=10, **_ignored):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    request = XMLHttpRequest.new()
    request.open("GET", url, False)
    try:
        request.timeout = int(float(timeout) * 1000)
    except Exception:
        pass
    for name, value in (headers or {}).items():
        if name.lower() not in ("user-agent", "accept-language"):   # the browser sends its own
            request.setRequestHeader(name, value)
    try:
        request.send()
    except Exception as e:
        raise ConnectionError(str(e))
    if request.status == 0:
        raise ConnectionError("no answer")
    return _Response(request.status, request.responseText)
`,
};

let python = null;
const text = async (path) => {
  const answer = await fetch(path);
  if (!answer.ok) throw new Error(`${path}: ${answer.status}`);
  return answer.text();
};

const starting = (async () => {
  importScripts(PYODIDE + "pyodide.js");
  // the Python sources and the map data come from Jarvis's own address, alongside the engine from its CDN
  const [py, sources, data] = await Promise.all([
    loadPyodide({ indexURL: PYODIDE }),
    Promise.all(SOURCES.map((name) => text("/brain/" + name))),
    Promise.all(DATA.map((name) => text("/brain/" + name))),
  ]);
  py.FS.mkdirTree("/brain/geo_data");
  py.FS.mkdirTree("/brain/data");
  for (const [name, source] of Object.entries(SHIMS)) py.FS.writeFile("/brain/" + name, source);
  SOURCES.forEach((name, i) => py.FS.writeFile("/brain/" + name, sources[i]));
  DATA.forEach((name, i) => py.FS.writeFile("/brain/" + name, data[i]));
  // time zones, for "sunrise in Tokyo" in Tokyo's own time (without them it is said in UTC, and says so)
  try { await py.loadPackage("tzdata"); } catch (e) { console.warn("Jarvis's brain: no time zone data", e); }
  py.runPython(`
import sys, json
sys.path.insert(0, "/brain")
import phone_brain
def _answer(text, settings):
    return json.dumps(phone_brain.handle(text, json.loads(settings)), default=str)
`);
  python = py;
})();
starting.then(() => postMessage({ ready: true }), (e) => postMessage({ failed: String(e && e.message || e) }));

onmessage = async (event) => {
  const { id, text: said, settings } = event.data || {};
  try {
    await starting;
    const answer = python.globals.get("_answer")(String(said || ""), JSON.stringify(settings || {}));
    postMessage({ id, result: JSON.parse(answer) });
  } catch (e) {
    postMessage({ id, error: String(e && e.message || e) });
  }
};
