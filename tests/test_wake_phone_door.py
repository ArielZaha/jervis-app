"""Jarvis Wake's phone door (wake/jarvis_wake.py): while Jarvis is closed, opening the Jarvis app on a paired phone
starts him. Driven over a real socket, with launching replaced by a recorder."""
import asyncio
import json
import os
import socket
import sys
import time

import pytest
import websockets

import phone_control

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wake"))
import jarvis_wake as wake  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def door(tmp_path, monkeypatch):
    for name in ("phone_client.html", "phone_sw.js", "phone_manifest.webmanifest", "phone_agent.js"):
        os.symlink(os.path.join(ROOT, name), tmp_path / name)
    os.symlink(os.path.join(ROOT, "phone_icons"), tmp_path / "phone_icons")
    (tmp_path / "settings.json").write_text(json.dumps({"values": {"JARVIS_PHONE_CONTROL": "on"}}))
    device = phone_control.DeviceRegistry(path=str(tmp_path / "phone_devices.json")).add("iPhone")
    config = {"project": str(tmp_path), "electron": "/nonexistent"}
    launches = []
    monkeypatch.setattr(wake, "PHONE_PORT", _free_port())
    monkeypatch.setattr(wake, "launch_jarvis", lambda config, voice=True: launches.append(voice) or True)
    monkeypatch.setattr(wake, "jarvis_running", lambda config: False)
    monkeypatch.setattr(wake, "_last_launch", [0.0])
    d = wake.PhoneDoor(config)
    d.start()
    d.device, d.launches, d.config = device, launches, config
    yield d
    d.stop()


async def _attach(port, device_id, token, **extra):
    async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
        await ws.send(json.dumps({"type": "hello", "role": "phone"}))
        assert json.loads(await ws.recv()) == {"type": "hello_ok"}
        await ws.send(json.dumps({"type": "auto_attach", "deviceId": device_id, "token": token, **extra}))
        return json.loads(await ws.recv())


def _wait_for(predicate, timeout=3):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        time.sleep(0.02)
    return predicate()


def test_opening_the_app_on_a_paired_phone_starts_jarvis_and_frees_the_port(door):
    device_id, token, _ = door.device
    assert asyncio.run(_attach(wake.PHONE_PORT, device_id, token, wake=True)) == {"type": "waking"}
    assert _wait_for(lambda: door.launches == [False])   # started quietly (no "I'm awake" voice greeting)
    assert _wait_for(lambda: not door.open)               # stepped aside for Jarvis's own phone server
    with socket.socket() as s:                            # ...which can now take the port
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", wake.PHONE_PORT))


def test_a_phone_that_is_not_paired_starts_nothing(door):
    device_id, _token, _ = door.device
    reply = asyncio.run(_attach(wake.PHONE_PORT, device_id, "not-the-token", wake=True))
    assert reply["type"] == "wake_refused"   # never "unpaired": a phone must not drop its pairing on our say-so
    time.sleep(0.2)
    assert door.launches == [] and door.open


def test_a_background_reconnect_does_not_restart_a_jarvis_that_was_just_quit(door):
    device_id, token, _ = door.device
    assert asyncio.run(_attach(wake.PHONE_PORT, device_id, token, wake=False)) == {"type": "jarvis_closed"}
    time.sleep(0.2)
    assert door.launches == [] and door.open


def test_repeated_requests_launch_jarvis_only_once(door, monkeypatch):
    assert wake.claim_launch(door.config) is True
    assert wake.claim_launch(door.config) is False   # within AFTER_LAUNCH_GRACE: never two Jarvises


def test_the_phone_app_page_and_icons_are_served_and_nothing_else(door):
    async def get(path):
        reader, writer = await asyncio.open_connection("127.0.0.1", wake.PHONE_PORT)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        data = await reader.read()
        writer.close()
        return data

    page = asyncio.run(get("/"))
    assert b" 200 " in page.split(b"\r\n")[0] and b"__SERVED_BY_RELAY__" not in page and b"Jarvis" in page
    assert b" 200 " in asyncio.run(get("/icons/icon-192.png")).split(b"\r\n")[0]
    assert b" 200 " in asyncio.run(get("/agent.js")).split(b"\r\n")[0]
    assert b" 404 " in asyncio.run(get("/settings.json")).split(b"\r\n")[0]
    assert b" 404 " in asyncio.run(get("/phone_devices.json")).split(b"\r\n")[0]


def test_pairing_checks_read_jarvis_own_files(door, tmp_path):
    device_id, token, _ = door.device
    assert wake.phone_is_paired(door.config, device_id, token)
    assert not wake.phone_is_paired(door.config, device_id, "")
    assert not wake.phone_is_paired(door.config, "someone", token)
    phone_control.DeviceRegistry(path=str(tmp_path / "phone_devices.json")).revoke(device_id)
    assert not wake.phone_is_paired(door.config, device_id, token)   # unpaired in Jarvis -> refused here too
    assert wake.phone_control_on(door.config)
    (tmp_path / "settings.json").write_text(json.dumps({"values": {"JARVIS_PHONE_CONTROL": "off"}}))
    assert not wake.phone_control_on(door.config)
