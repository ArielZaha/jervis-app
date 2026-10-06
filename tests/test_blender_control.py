"""The Blender bridge: the request/response file protocol and the code dispatcher (blender_bridge.process_one),
tested without a real Blender — see blender_bridge.py and blender_control.py."""
import json
import os

import pytest

import blender_bridge
import blender_control


def test_process_one_captures_a_result_variable():
    response = blender_bridge.process_one({"id": 1, "code": "RESULT = 'created a cube'"}, {})
    assert response == {"id": 1, "ok": True, "output": "created a cube", "error": ""}


def test_process_one_falls_back_to_printed_output():
    response = blender_bridge.process_one({"id": 2, "code": "print('hello from blender')"}, {})
    assert response["ok"] is True
    assert response["output"] == "hello from blender"


def test_process_one_reports_an_exception_without_raising():
    response = blender_bridge.process_one({"id": 3, "code": "1 / 0"}, {})
    assert response["ok"] is False
    assert "ZeroDivisionError" in response["error"]


def test_process_one_namespace_persists_across_calls():
    """A later command ("make it wooden") must see what an earlier one left behind."""
    namespace = {}
    blender_bridge.process_one({"id": 1, "code": "chair = 'Chair'"}, namespace)
    response = blender_bridge.process_one({"id": 2, "code": "RESULT = chair + ' is now wooden'"}, namespace)
    assert response == {"id": 2, "ok": True, "output": "Chair is now wooden", "error": ""}


def test_process_one_uses_whatever_bpy_the_namespace_provides():
    """process_one itself never imports bpy — only what install() put in the namespace is available, which is what
    makes it testable without a real Blender (see blender_bridge.install())."""

    class FakeObjects(list):
        def new(self, name):
            self.append(name)
            return name

    class FakeBpy:
        data = type("Data", (), {"objects": FakeObjects()})()

    namespace = {"bpy": FakeBpy()}
    response = blender_bridge.process_one(
        {"id": 1, "code": "bpy.data.objects.new('Cube')\nRESULT = str(list(bpy.data.objects))"}, namespace)
    assert response["ok"] is True
    assert "Cube" in response["output"]


def test_poll_processes_a_new_request_and_ignores_a_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(blender_bridge, "BRIDGE_DIR", str(tmp_path))
    monkeypatch.setattr(blender_bridge, "REQUEST_FILE", str(tmp_path / "request.json"))
    monkeypatch.setattr(blender_bridge, "RESPONSE_FILE", str(tmp_path / "response.json"))
    blender_bridge._last_id = None
    blender_bridge._namespace.clear()
    blender_bridge._namespace["__name__"] = "jarvis_blender"

    blender_bridge._write_json_atomic(blender_bridge.REQUEST_FILE, {"id": 1, "code": "RESULT = 'pong'"})
    blender_bridge.poll()
    with open(blender_bridge.RESPONSE_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"id": 1, "ok": True, "output": "pong", "error": ""}

    # overwrite the response to prove a repeat of the same request id is *not* reprocessed
    blender_bridge._write_json_atomic(blender_bridge.RESPONSE_FILE, {"sentinel": True})
    blender_bridge.poll()
    with open(blender_bridge.RESPONSE_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"sentinel": True}


def test_bridge_run_sends_a_request_and_waits_for_the_matching_response(tmp_path, monkeypatch):
    monkeypatch.setattr(blender_bridge, "BRIDGE_DIR", str(tmp_path))
    monkeypatch.setattr(blender_bridge, "REQUEST_FILE", str(tmp_path / "request.json"))
    monkeypatch.setattr(blender_bridge, "RESPONSE_FILE", str(tmp_path / "response.json"))

    def fake_blender_process():
        # stands in for Blender's own timer loop: process whatever the bridge just wrote, once.
        with open(blender_bridge.REQUEST_FILE, encoding="utf-8") as f:
            request = json.load(f)
        blender_bridge._write_json_atomic(blender_bridge.RESPONSE_FILE, blender_bridge.process_one(request, {}))

    bridge = blender_control.BlenderBridge()
    import threading
    import time as time_module

    def responder():
        for _ in range(100):
            if os.path.exists(blender_bridge.REQUEST_FILE):
                fake_blender_process()
                return
            time_module.sleep(0.02)
    thread = threading.Thread(target=responder, daemon=True)
    thread.start()
    response = bridge.run("RESULT = 'pong'", timeout=5)
    thread.join(timeout=1)
    assert response == {"id": 1, "ok": True, "output": "pong", "error": ""}


def test_bridge_ping_true_only_when_pong_comes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(blender_bridge, "BRIDGE_DIR", str(tmp_path))
    monkeypatch.setattr(blender_bridge, "REQUEST_FILE", str(tmp_path / "request.json"))
    monkeypatch.setattr(blender_bridge, "RESPONSE_FILE", str(tmp_path / "response.json"))
    bridge = blender_control.BlenderBridge()
    monkeypatch.setattr(bridge, "run", lambda code, timeout=20: {"ok": True, "output": "pong"})
    assert bridge.ping() is True
    monkeypatch.setattr(bridge, "run", lambda code, timeout=20: {"ok": False, "output": "", "error": "x"})
    assert bridge.ping() is False
    monkeypatch.setattr(bridge, "run", lambda code, timeout=20: {"ok": False, "output": "", "error": "timed out"})
    assert bridge.ping() is False


def test_ensure_bridge_reuses_a_responsive_session_bridge():
    session = type("S", (), {"blender": None})()
    responsive = type("B", (), {"ping": lambda self, timeout=3.0: True})()
    session.blender = responsive
    assert blender_control.ensure_bridge(session, confirm=lambda q: False) is responsive


def test_ensure_bridge_asks_before_restarting_an_unresponsive_blender(monkeypatch):
    session = type("S", (), {"blender": None})()
    unresponsive = type("B", (), {"ping": lambda self, timeout=3.0: False})()
    session.blender = unresponsive
    monkeypatch.setattr(blender_control, "blender_running", lambda: True)
    monkeypatch.setattr(blender_control, "RESTART_GRACE_SECONDS", 0)
    monkeypatch.setattr(blender_control, "BlenderBridge", lambda: unresponsive)
    asked = []

    def confirm(question):
        asked.append(question)
        return False
    assert blender_control.ensure_bridge(session, confirm=confirm) is None
    assert asked and "restart" in asked[0].lower()


def test_ensure_bridge_launches_fresh_without_asking_when_blender_is_not_running(monkeypatch):
    session = type("S", (), {"blender": None})()
    monkeypatch.setattr(blender_control, "blender_running", lambda: False)
    launched = []
    monkeypatch.setattr(blender_control, "launch_with_bridge", lambda confirm_seconds=60: launched.append(1) or "bridge")
    asked = []
    result = blender_control.ensure_bridge(session, confirm=lambda q: asked.append(q))
    assert result == "bridge" and launched and not asked
