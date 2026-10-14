"""relay_client.py: the relay-specific transport around phone_session.PhoneSessionRouter — computer id, conn_id
namespacing (so a relay reconnect only cleans up relay connections, never a concurrent local one), and turning the
relay's connId-multiplexed "frame"/"decide"/"phone_disconnected" messages into calls on the shared router. The
protocol itself (attach, encrypted commands, voice) is exercised directly in test_phone_session.py; this file only
checks relay_client.py's own wiring around it.
"""
import asyncio
import json

import pytest

import phone_control
import phone_crypto
import phone_session
import relay_client


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def server(tmp_path):
    registry = phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))
    return phone_control.PhoneControlServer(execute=lambda t, p: "did it", registry=registry)


@pytest.fixture
def router(server):
    return phone_session.PhoneSessionRouter(server, lambda pcm, rate: "", lambda text, session_id: None)


def _client(router):
    return relay_client.RelayClient("wss://relay.example/", router, is_enabled=lambda: True,
                                    get_vapid_key=lambda: "test-vapid-key",
                                    get_local_address=lambda: "http://192.168.1.50:8766")


def test_computer_id_persists_across_instances(tmp_path, router, monkeypatch):
    monkeypatch.setattr(relay_client, "IDENTITY_FILE", str(tmp_path / "relay_identity.json"))
    first = _client(router).computer_id
    second = _client(router).computer_id
    assert first == second
    assert len(first) > 16   # meaningfully random, not a placeholder


def test_a_decide_message_reaches_the_shared_server(router):
    client = _client(router)
    session = router.phone_server.begin_session()

    async def scenario():
        client._loop = asyncio.get_event_loop()
        await client._on_message(json.dumps({"type": "decide", "sessionId": session.id, "secret": session.secret,
                                             "decision": "confirm"}))

    _run(scenario())
    assert session.state == "approved"


def test_get_page_context_replies_with_the_requestid_key_and_local_address(router):
    client = _client(router)
    sent = []

    async def fake_send(text):
        sent.append(json.loads(text))

    client._send = fake_send

    async def scenario():
        client._loop = asyncio.get_event_loop()
        await client._on_message(json.dumps({"type": "get_page_context", "requestId": "r1"}))

    _run(scenario())
    assert sent == [{"type": "page_context", "requestId": "r1", "vapidKey": "test-vapid-key",
                     "localAddress": "http://192.168.1.50:8766"}]


def test_a_frame_attaches_through_the_shared_router_with_a_relay_prefixed_connid(router):
    client = _client(router)
    sent = []

    async def fake_send(text):
        sent.append(json.loads(text))

    client._send = fake_send
    device_id, token, key = router.phone_server.registry.add("Phone")
    session = router.phone_server.begin_session()
    router.phone_server.decide_session(session.id, session.secret, True)

    async def scenario():
        client._loop = asyncio.get_event_loop()
        await client._on_message(json.dumps({"type": "frame", "connId": "abc123",
                                             "payload": {"type": "session_attach", "sessionId": session.id,
                                                        "deviceId": device_id, "token": token}}))
        await asyncio.sleep(0.05)

    _run(scenario())
    assert "relay:abc123" in router._conns
    frame, info_frame = sent   # session_ready, then session_info (history, names) right behind it
    assert frame["type"] == "frame" and frame["connId"] == "abc123"
    assert phone_crypto.decrypt(key, frame["payload"]) == {"type": "session_ready"}
    assert phone_crypto.decrypt(key, info_frame["payload"])["type"] == "session_info"


def test_phone_disconnected_forgets_only_that_relay_connection(router):
    client = _client(router)
    router._conns["relay:abc123"] = {"key": phone_crypto.new_key(), "device_id": "d", "session_id": "s",
                                     "voice": None, "schedule_send": lambda o: None, "schedule_end": None}
    router._conns["local:xyz"] = dict(router._conns["relay:abc123"])

    async def scenario():
        client._loop = asyncio.get_event_loop()
        await client._on_message(json.dumps({"type": "phone_disconnected", "connId": "abc123"}))

    _run(scenario())
    assert "relay:abc123" not in router._conns
    assert "local:xyz" in router._conns


def test_a_reconnect_attempt_forgets_only_relay_connections(router, monkeypatch):
    """run_forever() clears every stale relay:-prefixed connection before each (re)connect attempt, since a fresh
    relay connection means the relay minted fresh connIds too — but must never touch a concurrent local: one."""
    router._conns["relay:old"] = {"key": phone_crypto.new_key(), "device_id": "d", "session_id": "s",
                                  "voice": None, "schedule_send": lambda o: None, "schedule_end": None}
    router._conns["local:keep"] = dict(router._conns["relay:old"])
    client = _client(router)

    attempts = 0

    class _StopLoop(Exception):
        pass

    class _FakeConnect:
        def __init__(self, *a, **kw):
            nonlocal attempts
            attempts += 1

        async def __aenter__(self):
            raise _StopLoop   # bail out right after forget_matching() has run, instead of reconnecting forever

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(relay_client.websockets, "connect", _FakeConnect)

    with pytest.raises(_StopLoop):
        _run(client.run_forever())

    assert attempts == 1
    assert "relay:old" not in router._conns
    assert "local:keep" in router._conns


def test_deliver_reply_and_end_session_delegate_to_the_router(router, monkeypatch):
    calls = []
    monkeypatch.setattr(router, "deliver_reply", lambda session_id, text: calls.append(("reply", session_id, text)))
    monkeypatch.setattr(router, "end_session", lambda session_id: calls.append(("end", session_id)))
    client = _client(router)

    client.deliver_reply("s1", "hello")
    client.end_session("s1")

    assert calls == [("reply", "s1", "hello"), ("end", "s1")]
