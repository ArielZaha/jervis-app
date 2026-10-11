"""First-run setup of the local AI: the parts that decide what to download, and what happens when downloads go wrong.

Downloads are served by a tiny local HTTP server, so these run offline and fast.
"""
import hashlib
import http.server
import os
import threading

import pytest

import local_ai
import paths


def test_model_name_matching():
    has = local_ai.LocalAI._has
    assert has(["llama3.2:latest"], "llama3.2")
    assert has(["qwen2.5vl:3b", "llama3.2:latest"], "qwen2.5vl:3b")
    assert not has(["llama3.2:1b"], "llama3.2")          # a different size is not the model asked for
    assert not has(["llama3.2:latest"], "qwen2.5vl:3b")


def test_vision_only_with_enough_memory(monkeypatch):
    class Memory:
        def __init__(self, gb):
            self.total = gb * 1024 ** 3
    monkeypatch.delenv("JARVIS_LOCAL_VISION", raising=False)
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(8))
    assert not local_ai.wants_vision()          # 8 GB: measured to swap for minutes
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(15.7))
    assert local_ai.wants_vision()              # a "16 GB" machine
    monkeypatch.setenv("JARVIS_LOCAL_VISION", "on")
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(8))
    assert local_ai.wants_vision()              # the user's choice wins
    monkeypatch.setenv("JARVIS_LOCAL_VISION", "off")
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(64))
    assert not local_ai.wants_vision()


def test_pinned_builds_cover_windows_and_mac(monkeypatch):
    manager = local_ai.LocalAI()
    for system, machine, expected in (("Windows", "AMD64", "ollama-windows-amd64.zip"),
                                      ("Windows", "ARM64", "ollama-windows-arm64.zip"),
                                      ("Darwin", "arm64", "ollama-darwin.tgz"),
                                      ("Darwin", "x86_64", "ollama-darwin.tgz")):
        monkeypatch.setattr(local_ai.platform, "system", lambda s=system: s)
        monkeypatch.setattr(local_ai.platform, "machine", lambda m=machine: m)
        name, size, sha = manager._asset()
        assert name == expected and size > 0 and len(sha) == 64
    monkeypatch.setattr(local_ai.platform, "system", lambda: "Plan9")
    with pytest.raises(local_ai.SetupError) as e:
        manager._asset()
    assert "ollama.com" in e.value.hint   # tells the user what they can do


# ---------- downloads, against a local server ----------
PAYLOAD = os.urandom(300_000)


class _Server(http.server.BaseHTTPRequestHandler):
    drop_first = False   # simulate a connection that breaks halfway

    def do_GET(self):
        start = 0
        if self.headers.get("Range"):
            start = int(self.headers["Range"].split("=")[1].split("-")[0])
        body = PAYLOAD[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if _Server.drop_first and not start:
            _Server.drop_first = False
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/file"
    httpd.shutdown()


def test_interrupted_download_resumes(server, tmp_path, monkeypatch):
    monkeypatch.setattr(local_ai.time, "sleep", lambda s: None)
    _Server.drop_first = True
    manager = local_ai.LocalAI()
    target = tmp_path / "engine.part"
    manager._download(server, str(target), len(PAYLOAD), "engine", "Downloading")
    assert target.read_bytes() == PAYLOAD   # the second request continued from where the first broke off


def test_damaged_engine_download_is_deleted(tmp_path, monkeypatch):
    """A download whose checksum doesn't match is never unpacked or run."""
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    manager = local_ai.LocalAI()
    good = hashlib.sha256(b"the real engine").hexdigest()
    monkeypatch.setattr(manager, "_asset", lambda: ("ollama-darwin.tgz", len(b"tampered bytes!"), good))
    monkeypatch.setattr(manager, "_check_disk", lambda need: None)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "ollama-darwin.tgz").write_bytes(b"tampered bytes!")   # already "downloaded", but wrong
    with pytest.raises(local_ai.SetupError) as e:
        manager._download_engine()
    assert "damaged" in e.value.message
    assert not (runtime / "ollama-darwin.tgz").exists()


def test_not_enough_disk_space_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(local_ai.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024 ** 3})())
    with pytest.raises(local_ai.SetupError) as e:
        local_ai.LocalAI()._check_disk(5 * 1024 ** 3)
    assert "5.0 GB" in e.value.message and "1.0 GB" in e.value.message
    assert "Free up" in e.value.hint


# ---------- LLM_BACKEND=groq: the local AI is closed and its memory given back ----------
class _FakeProcess:
    def __init__(self, pid, name, username="me", children=(), stubborn=False):
        self.pid, self.info, self._children, self.stubborn = pid, {"name": name, "username": username}, children, stubborn
        self.terminated = self.killed = False

    def children(self, recursive=False):
        return list(self._children)

    def username(self):
        return self.info["username"]

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def alive(self):
        return not (self.killed or (self.terminated and not self.stubborn))


@pytest.fixture
def machine(monkeypatch):
    """A stand-in computer: its running programs and what an Ollama on it holds in memory."""
    state = {"processes": [], "loaded": {}, "unloaded": [], "asked": []}

    class Reply:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def get(url, timeout=None):
        state["asked"].append(url)
        base = url.rsplit("/api/", 1)[0]
        if base not in state["loaded"]:
            raise local_ai.requests.ConnectionError("nothing there")
        return Reply({"models": [{"name": n, "size": size} for n, size in state["loaded"][base].items()]})

    def post(url, json=None, timeout=None):
        base = url.rsplit("/api/", 1)[0]
        assert json["keep_alive"] == 0
        state["loaded"][base].pop(json["model"])
        state["unloaded"].append(json["model"])
        return Reply({})

    monkeypatch.setattr(local_ai.requests, "get", get)
    monkeypatch.setattr(local_ai.requests, "post", post)
    monkeypatch.setattr(local_ai.psutil, "Process", lambda: _FakeProcess(1, "python"))
    monkeypatch.setattr(local_ai.psutil, "process_iter", lambda attrs=None: [p for p in state["processes"] if p.alive()])
    monkeypatch.setattr(local_ai.psutil, "wait_procs",
                        lambda procs, timeout=None: ([p for p in procs if not p.alive()], [p for p in procs if p.alive()]))
    monkeypatch.setattr(local_ai.time, "sleep", lambda s: None)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    return state


def test_release_unloads_the_model_and_closes_every_ollama_program(machine):
    runner = _FakeProcess(30, "llama-server")
    machine["processes"] = [_FakeProcess(10, "Ollama"), _FakeProcess(20, "ollama", children=[runner]), runner,
                            _FakeProcess(40, "Spotify"), _FakeProcess(50, "ollama", username="someone else")]
    machine["loaded"] = {local_ai.USER_OLLAMA_URL: {"llama3.2:latest": 2548417166}}
    result = local_ai.release()
    assert result == {"freed": 2548417166, "stopped": 3, "left": 0}
    assert machine["unloaded"] == ["llama3.2:latest"]
    closed = {p.pid for p in machine["processes"] if p.terminated}
    assert closed == {10, 20, 30}                      # not other programs, and not another person's Ollama
    assert "2.4 GB" in local_ai.release_summary(result)


def test_release_forces_a_program_that_ignores_being_asked(machine):
    machine["processes"] = [_FakeProcess(20, "ollama.exe", stubborn=True)]
    result = local_ai.release()
    assert machine["processes"][0].killed and result["stopped"] == 1 and result["left"] == 0


def test_release_with_nothing_running_says_so(machine):
    result = local_ai.release()
    assert result == {"freed": 0, "stopped": 0, "left": 0}
    assert "nothing to close" in local_ai.release_summary(result)


def _reopening(machine, monkeypatch, times):
    """Ollama comes back right after being closed, `times` times (an app relaunching itself, a system service)."""
    real_wait, left = local_ai.psutil.wait_procs, [times]

    def wait_then_reopen(procs, timeout=None):
        done = real_wait(procs, timeout)
        if procs and left[0] > 0 and not any(p.alive() for p in machine["processes"]):
            left[0] -= 1
            machine["processes"].append(_FakeProcess(99 + left[0], "ollama"))
        return done
    monkeypatch.setattr(local_ai.psutil, "wait_procs", wait_then_reopen)


def test_release_closes_an_ollama_that_reopens_itself_once(machine, monkeypatch):
    machine["processes"] = [_FakeProcess(20, "ollama")]
    machine["loaded"] = {local_ai.USER_OLLAMA_URL: {"llama3.2:latest": 2 * 1024 ** 3}}
    _reopening(machine, monkeypatch, times=1)
    result = local_ai.release()
    assert result["left"] == 0 and "again" not in local_ai.release_summary(result)


def test_release_reports_an_ollama_the_system_keeps_starting(machine, monkeypatch):
    machine["processes"] = [_FakeProcess(20, "ollama")]
    machine["loaded"] = {local_ai.USER_OLLAMA_URL: {"llama3.2:latest": 2 * 1024 ** 3}}
    _reopening(machine, monkeypatch, times=5)
    result = local_ai.release()
    assert result["stopped"] == 1 and result["left"] == 1 and result["freed"] == 2 * 1024 ** 3
    assert "started Ollama again" in local_ai.release_summary(result)


def test_release_never_touches_an_ollama_on_another_computer(machine, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://192.168.1.50:11434")
    machine["loaded"] = {"http://192.168.1.50:11434": {"llama3.2:latest": 1}}
    local_ai.release()
    assert machine["unloaded"] == [] and not any("192.168" in url for url in machine["asked"])
