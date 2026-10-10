"""Jarvis Wake's relay door (wake/jarvis_wake.py): while Jarvis is closed, Wake holds this computer's place on the
relay, so the phone's always-on app can still open Jarvis from anywhere. Driven through the real relay (relay/server.py)
over real sockets, with a real paired device and its real key; only starting Jarvis is replaced by a recorder."""
import asyncio
import json
import os
import sys
import threading
import time

import pytest
import websockets

import phone_control
import phone_crypto

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wake"))
sys.path.insert(0, os.path.join(ROOT, "relay"))
import jarvis_wake as wake  # noqa: E402
import server as relay_server  # noqa: E402

COMPUTER = "computer-under-test"


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def world(tmp_path, monkeypatch):
    for table in (relay_server.computers, relay_server.phone_owner, relay_server.phone_sockets,
                  relay_server.computer_conns, relay_server.pending_page_context):
        table.clear()
    port = _free_port()
    (tmp_path / "settings.json").write_text(json.dumps({"values": {
        "JARVIS_PHONE_CONTROL": "on", "JARVIS_RELAY_URL": f"ws://127.0.0.1:{port}/"}}))
    (tmp_path / "relay_identity.json").write_text(json.dumps({"computerId": COMPUTER}))
    registry = phone_control.DeviceRegistry(path=str(tmp_path / "phone_devices.json"))
    device_id, token, key = registry.add("iPhone")
    device = {"id": device_id, "token": token}
    config = {"project": str(tmp_path), "electron": "/nonexistent"}
    launches, running = [], [False]
    monkeypatch.setattr(wake, "launch_jarvis", lambda config, voice=True: launches.append(voice) or True)
    monkeypatch.setattr(wake, "jarvis_running", lambda config: running[0])
    monkeypatch.setattr(wake, "_last_launch", [0.0])
    monkeypatch.setattr(wake, "CHECK_JARVIS_EVERY", 0.1)

    loop = asyncio.new_event_loop()
    started, stop = threading.Event(), threading.Event()
    finished = {}

    async def serve():
        finished["relay"] = asyncio.get_running_loop().create_future()
        async with websockets.serve(relay_server.handler, "127.0.0.1", port):
            started.set()
            await finished["relay"]

    relay_thread = threading.Thread(target=lambda: loop.run_until_complete(serve()), daemon=True)
    relay_thread.start()
    assert started.wait(5)
    keeper = threading.Thread(target=wake.keep_relay_door, args=(config, stop), daemon=True)
    keeper.start()
    assert _wait_for(lambda: COMPUTER in relay_server.computers), "Wake never signed in to the relay"
    yield {"port": port, "device": device, "key": key, "launches": launches, "running": running, "config": config}
    stop.set()                # the keeper leaves the relay and ends…
    keeper.join(5)
    loop.call_soon_threadsafe(finished["relay"].set_result, None)   # …then this test's relay shuts down
    relay_thread.join(5)


def _wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        time.sleep(0.02)
    return predicate()


def _proof(key, device_id, age_seconds=0):
    return phone_crypto.encrypt(key, {"type": "attach", "deviceId": device_id, "ts": (time.time() - age_seconds) * 1000})


def _knock(port, message):
    async def go():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
            await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": COMPUTER}))
            assert json.loads(await phone.recv())["type"] == "hello_ok"
            await phone.send(json.dumps(message))
            return json.loads(await asyncio.wait_for(phone.recv(), 5))
    return asyncio.run(go())


def test_the_paired_phone_opening_the_app_starts_jarvis(world):
    device = world["device"]
    reply = _knock(world["port"], {"type": "auto_attach", "deviceId": device["id"],
                                   "proof": _proof(world["key"], device["id"]), "wake": True})
    assert reply == {"type": "waking"}
    assert _wait_for(lambda: world["launches"] == [False])   # started, and not with the "woken by voice" greeting
    # …and Wake steps aside, so Jarvis can sign in to the relay himself
    assert _wait_for(lambda: COMPUTER not in relay_server.computers)


@pytest.mark.parametrize("wake_flag", [False, None])
def test_a_phone_that_did_not_ask_never_starts_jarvis(world, wake_flag):
    """Jarvis on the phone ("On this phone"), or the app reconnecting by itself, must not open Jarvis on the computer."""
    device = world["device"]
    message = {"type": "auto_attach", "deviceId": device["id"], "proof": _proof(world["key"], device["id"])}
    if wake_flag is not None:
        message["wake"] = wake_flag
    assert _knock(world["port"], message) == {"type": "jarvis_closed"}
    time.sleep(0.3)
    assert world["launches"] == []


@pytest.mark.parametrize("how", ["another key", "another device's name", "a stale proof", "no proof", "a token instead"])
def test_nothing_else_can_start_jarvis(world, how):
    device = world["device"]
    proof = {"another key": _proof(phone_crypto.new_key(), device["id"]),
             "another device's name": _proof(world["key"], "someone-else"),
             "a stale proof": _proof(world["key"], device["id"], age_seconds=3600),
             "no proof": None, "a token instead": None}[how]
    message = {"type": "auto_attach", "deviceId": device["id"], "proof": proof, "wake": True}
    if how == "a token instead":
        message["token"] = device["token"]   # the token never proves anything through the relay
    reply = _knock(world["port"], message)
    assert reply["type"] == "wake_refused"
    time.sleep(0.3)
    assert world["launches"] == []


def test_a_phone_trying_to_pair_is_told_jarvis_is_closed(world):
    """Pairing needs Jarvis himself (and the code on his screen). With only Wake there, the app hears so at once."""
    envelope = phone_crypto.encrypt(phone_crypto.new_key(), {"type": "pair", "ts": time.time() * 1000})
    assert _knock(world["port"], {"type": "pair_secure", "envelope": envelope}) == {"type": "jarvis_closed"}
    time.sleep(0.3)
    assert world["launches"] == []


def test_wake_leaves_the_relay_to_jarvis_while_he_runs(world):
    world["running"][0] = True
    assert _wait_for(lambda: COMPUTER not in relay_server.computers)
    time.sleep(0.5)
    assert COMPUTER not in relay_server.computers


def test_the_relay_address_follows_jarviss_settings(tmp_path):
    config = {"project": str(tmp_path)}
    assert wake.relay_address(config) == wake.DEFAULT_RELAY          # no settings yet: Jarvis's own default
    (tmp_path / "settings.json").write_text(json.dumps({"values": {"JARVIS_RELAY_URL": ""}}))
    assert wake.relay_address(config) == ""                          # cleared in Settings: same-Wi-Fi only
    import settings
    default = next(item["default"] for item in settings.SCHEMA if item["key"] == "JARVIS_RELAY_URL")
    assert wake.DEFAULT_RELAY == default
