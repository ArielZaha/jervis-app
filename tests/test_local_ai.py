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
    monkeypatch.delenv("JERVIS_LOCAL_VISION", raising=False)
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(8))
    assert not local_ai.wants_vision()          # 8 GB: measured to swap for minutes
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(15.7))
    assert local_ai.wants_vision()              # a "16 GB" machine
    monkeypatch.setenv("JERVIS_LOCAL_VISION", "on")
    monkeypatch.setattr(local_ai.psutil, "virtual_memory", lambda: Memory(8))
    assert local_ai.wants_vision()              # the user's choice wins
    monkeypatch.setenv("JERVIS_LOCAL_VISION", "off")
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
