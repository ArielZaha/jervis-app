"""The real backend process, started the way the window starts it, driven over the window connection."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import pytest
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "e2e-secret"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    port = _free_port()
    data = tmp_path_factory.mktemp("data")
    env = {**os.environ, "JERVIS_SUPERVISED": "1", "JERVIS_WS_PORT": str(port), "JERVIS_WS_TOKEN": TOKEN,
           "JERVIS_DATA_DIR": str(data), "JERVIS_AUDIO": "off", "JERVIS_NO_AI_SETUP": "1", "GROQ_API_KEY": "",
           "PYTHONUNBUFFERED": "1"}
    env.pop("JERVIS_ALLOW_ORIGINS", None)
    process = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.3)
    else:
        process.kill()
        pytest.fail("backend did not start")
    yield port, data
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


async def _talk(port, token, messages, want, timeout=20, origin=None):
    url = f"ws://127.0.0.1:{port}/" + (f"?token={token}" if token else "")
    headers = {"Origin": origin} if origin else None
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        for m in messages:
            await ws.send(json.dumps(m))
        end = time.time() + timeout
        while time.time() < end:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.time()))
            if want(msg):
                return msg
    return None


def run(coro):
    return asyncio.run(coro)


def test_connection_without_the_secret_is_refused(backend):
    port, _ = backend
    with pytest.raises(websockets.ConnectionClosed):
        run(_talk(port, "", [{"type": "text", "text": "what time is it"}], lambda m: m.get("sender") == "ai", 5))
    with pytest.raises(websockets.ConnectionClosed):
        run(_talk(port, "wrong", [{"type": "get_settings"}], lambda m: True, 5))


def test_web_pages_are_refused_even_with_the_secret(backend):
    port, _ = backend
    with pytest.raises(websockets.ConnectionClosed):
        run(_talk(port, TOKEN, [{"type": "get_settings"}], lambda m: True, 5, origin="https://example.com"))


def test_typed_command_is_answered(backend):
    port, data = backend
    reply = run(_talk(port, TOKEN, [{"type": "text", "text": "set a timer for 3 minutes"}],
                      lambda m: m.get("sender") == "ai"))
    assert reply and "3 minutes" in reply["text"]
    assert os.path.exists(data / "timers.json")          # written to the data folder, not the app folder
    transcript = "".join(open(os.path.join(data, "transcripts", f)).read() for f in os.listdir(data / "transcripts"))
    assert "set a timer for 3 minutes" in transcript


def test_settings_round_trip_and_validation(backend):
    port, data = backend
    view = run(_talk(port, TOKEN, [{"type": "get_settings"}], lambda m: m.get("type") == "settings"))
    assert view and any(item["key"] == "LLM_BACKEND" for item in view["schema"])
    saved = run(_talk(port, TOKEN, [{"type": "set_settings", "values": {"JERVIS_KEEP_TRANSCRIPTS": "off"}}],
                      lambda m: m.get("type") in ("settings_saved", "settings_error")))
    assert saved == {"type": "settings_saved", "saved": ["JERVIS_KEEP_TRANSCRIPTS"], "restart": False}
    bad = run(_talk(port, TOKEN, [{"type": "set_settings", "values": {"JERVIS_COMPUTER_CONTROL": "always"}}],
                    lambda m: m.get("type") in ("settings_saved", "settings_error")))
    assert bad["type"] == "settings_error"


def test_ai_question_during_setup_gets_a_clear_answer(backend):
    """No AI yet (setup skipped in this test): the answer explains instead of failing silently."""
    port, _ = backend
    reply = run(_talk(port, TOKEN, [{"type": "text", "text": "what is the capital of France"}],
                      lambda m: m.get("sender") == "ai", timeout=40))
    assert reply and reply["text"]
    assert "Traceback" not in reply["text"]


def test_the_engine_stops_when_its_window_is_gone(tmp_path):
    """If the window is ended without stopping the engine (Task Manager, a crash, an installer), the engine must not
    keep running and listening with nothing on screen."""
    window = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])   # stands in for the window
    port = _free_port()
    env = {**os.environ, "JERVIS_SUPERVISED": "1", "JERVIS_WS_PORT": str(port), "JERVIS_WS_TOKEN": TOKEN,
           "JERVIS_DATA_DIR": str(tmp_path), "JERVIS_AUDIO": "off", "JERVIS_NO_AI_SETUP": "1", "GROQ_API_KEY": "",
           "JERVIS_PARENT_PID": str(window.pid)}
    engine = subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.3)
        assert engine.poll() is None, "the engine didn't start"
        window.kill()
        window.wait()
        engine.wait(timeout=15)   # raises if it keeps running
    finally:
        for process in (engine, window):
            if process.poll() is None:
                process.kill()
