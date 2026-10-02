"""Phone control wired into Jervis: the "connect my phone" trigger, the mandatory confirmation, the allowlisted
command dispatch, and the real wire protocol end to end (a genuine websocket client talking to handle_phone_client).

Runs in the sandbox (tests/sandbox.py): every tool a phone command could reach records an action instead of
touching the real computer.
"""
import asyncio
import json
import threading
import time

import pytest
import websockets

import phone_control
import phone_crypto
import push
import sandbox

app = None


@pytest.fixture(autouse=True, scope="module")
def sandboxed():
    global app
    sandbox.install()
    import app as imported
    app = imported
    yield
    sandbox.uninstall()


@pytest.fixture(autouse=True)
def clean(sandboxed, monkeypatch, tmp_path):
    sandbox.reset()
    app.pending_control_question = None
    app._control_questions.clear()
    while not app.announcements.empty():
        app.announcements.get_nowait()
    sent = []
    monkeypatch.setattr(app, "send_ui_update_once", lambda payload: sent.append(payload))
    monkeypatch.setattr(app, "send_ui_update",
                        lambda data_type, data: sent.append({"type": data_type, "data": data}))
    monkeypatch.setenv("JERVIS_PHONE_CONTROL", "on")
    fresh_registry = phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))
    monkeypatch.setattr(app.phone_server, "registry", fresh_registry)
    monkeypatch.setattr(app.phone_server, "_pairing", None)
    monkeypatch.setattr(app.phone_server, "_session", None)
    monkeypatch.setattr(app.phone_server, "_results", {})
    monkeypatch.setattr(app, "push_store", push.SubscriptionStore(path=str(tmp_path / "subs.json")))
    monkeypatch.setattr(app.session_router, "_conns", {})
    yield sent


# ---------- allowlisted dispatch ----------
def test_dispatch_runs_the_matching_existing_tool():
    result = app._dispatch_phone_command("OPEN_APPLICATION", {"app_name": "Chrome"})
    assert isinstance(result, str)
    assert any("chrome" in a.lower() for a in sandbox.actions)


def test_dispatch_refuses_anything_not_allowlisted():
    with pytest.raises(ValueError):
        app._dispatch_phone_command("DELETE_EVERYTHING", {})
    with pytest.raises(ValueError):
        app._dispatch_phone_command("use_computer", {"task": "do anything"})


def test_dispatch_requires_its_payload_field():
    with pytest.raises(ValueError):
        app._dispatch_phone_command("OPEN_APPLICATION", {})
    with pytest.raises(ValueError):
        app._dispatch_phone_command("PLAY_SONG", {"song_name": "   "})


def test_pause_music_needs_no_payload():
    app._dispatch_phone_command("PAUSE_MUSIC", {})   # must not raise


# ---------- recognizing the trigger phrase ----------
@pytest.mark.parametrize("said", [
    "connect my phone", "Jervis, connect my phone", "pair my phone", "connect to my phone",
    "let my phone control this computer", "control my computer from my phone",
])
def test_phone_pair_phrases_are_recognized(said):
    assert app.is_phone_pair_command(said)


@pytest.mark.parametrize("said", [
    "call my phone", "my phone is dead", "connect to the printer", "control my mood",
    "disconnect my phone", "disconnect the phone session",
])
def test_ordinary_sentences_are_not_mistaken_for_pairing(said):
    assert not app.is_phone_pair_command(said)


# ---------- the confirm-then-pair flow ----------
def test_pairing_is_refused_outright_when_the_feature_is_off(monkeypatch):
    monkeypatch.setenv("JERVIS_PHONE_CONTROL", "off")
    reply = app.start_phone_pairing()
    assert "off" in reply.lower()
    assert not app.phone_server.pairing_open()


def test_declining_the_confirmation_never_opens_pairing():
    reply = app.start_phone_pairing()
    assert "connect your phone" in reply
    ask_id = app.pending_control_question["id"]
    assert app.answer_control_question(ask_id, False)
    for _ in range(100):
        if app.pending_control_question is None or app.pending_control_question["id"] != ask_id:
            break
        time.sleep(0.01)
    assert not app.phone_server.pairing_open()


def test_confirming_opens_pairing_and_announces_the_code(clean):
    sent = clean
    reply = app.start_phone_pairing()
    assert "connect your phone" in reply
    ask_id = app.pending_control_question["id"]
    assert app.answer_control_question(ask_id, True)
    for _ in range(200):
        if app.phone_server.pairing_open():
            break
        time.sleep(0.01)
    assert app.phone_server.pairing_open()
    announced = app.announcements.get(timeout=2)
    assert announced == "Scan the QR code on your screen with your phone to connect."   # short and clear, on purpose
    pairing_update = next(p for p in sent if p.get("type") == "phone_pairing")["data"]
    assert "http://" in pairing_update["address"] and str(app.PHONE_WS_PORT) in pairing_update["address"]
    # the code travels inside pairUrl too, so scanning the QR code alone is the whole step (see phone_client.html)
    assert pairing_update["pairUrl"] == pairing_update["address"] + "/?code=" + pairing_update["code"]


def test_asking_to_connect_a_phone_pushes_a_real_notification(monkeypatch):
    """Even before pairing, a phone that already turned notifications on should be told Jervis is asking —
    the whole reason this was built: reaching the phone doesn't require the page to be open."""
    calls = []
    monkeypatch.setattr(push, "send_to_all",
                        lambda store, title, body, **kw: calls.append((store, title, body)) or 1)
    app.start_phone_pairing()
    for _ in range(200):
        if calls:
            break
        time.sleep(0.01)
    assert calls and calls[0][0] is app.push_store
    assert "connect your phone" in calls[0][2]


def test_asking_to_connect_a_phone_texts_when_twilio_is_configured(monkeypatch):
    monkeypatch.setattr(app.sms, "configured", lambda: True)
    calls = []
    monkeypatch.setattr(app.sms, "send", lambda body: calls.append(body) or "")
    app.start_phone_pairing()
    for _ in range(200):
        if calls:
            break
        time.sleep(0.01)
    assert calls and "connect your phone" in calls[0]


def test_no_text_is_attempted_when_twilio_is_not_configured(monkeypatch):
    monkeypatch.setattr(app.sms, "configured", lambda: False)
    calls = []
    monkeypatch.setattr(app.sms, "send", lambda body: calls.append(body) or "")
    app.start_phone_pairing()
    time.sleep(0.1)
    assert calls == []


def test_yes_after_a_phone_confirmation_gives_the_phone_specific_reply():
    app.open_control_question("Do you want to talk to Jarvis on your phone as well?", kind="phone")
    reply = app.handle_control_voice("yes")
    assert reply == "Okay, pairing your phone now."


def test_yes_after_a_computer_control_confirmation_still_gives_the_original_reply():
    app.open_control_question("Can I use your mouse and keyboard?", kind="computer")
    reply = app.handle_control_voice("yes")
    assert "Move the mouse" in reply


# ---------- sessions: "connect my phone" once a phone is already paired (needs a relay configured) ----------
def _pair_a_phone():
    return app.phone_server.registry.add("Ariel's iPhone")


def test_connect_my_phone_starts_a_session_once_a_phone_is_paired(monkeypatch):
    """The old code-to-type flow is only ever for the first-ever phone — see phone_control.py's module docstring."""
    _pair_a_phone()
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 1)
    reply = app.start_phone_pairing()
    assert reply == "I've sent a connection request to your phone."
    assert not app.phone_server.pairing_open()   # the old code-based flow never opened


def test_starting_a_session_without_a_relay_configured_still_works_locally(monkeypatch):
    """No relay deployed yet shouldn't block "connect my phone" for an already-paired phone on this Wi-Fi —
    confirm.html's own /decide is always relative to wherever it's served from, so the push payload doesn't even
    need to say which transport this is; same payload either way. See session_transport_url() for the separate,
    optional "Open Jervis" live-session link, which is the only part that still cares."""
    _pair_a_phone()
    monkeypatch.setattr(app, "RELAY_URL", "")
    calls = []
    monkeypatch.setattr(push, "send_to_all", lambda store, title, body, **kw: calls.append(kw) or 1)
    reply = app.start_phone_session()
    assert reply == "I've sent a connection request to your phone."
    assert "relayUrl" not in calls[0]["data"]


def test_starting_a_session_pushes_confirm_and_reject_actions(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda store, title, body, **kw: calls.append((title, body, kw)) or 1)
    _pair_a_phone()
    reply = app.start_phone_session()
    assert reply == "I've sent a connection request to your phone."
    assert len(calls) == 1
    title, body, kw = calls[0]
    assert body == "Jervis wants to connect to this computer."
    actions = {a["action"] for a in kw["actions"]}
    assert actions == {"confirm", "reject"}
    # confirm.html needs exactly these three — nothing transport-specific (no relayUrl): see its own docstring
    assert kw["data"] == {"computerId": app.relay.computer_id, "sessionId": kw["data"]["sessionId"],
                          "secret": kw["data"]["secret"]}


def test_starting_a_session_with_no_reachable_phone_shows_a_qr_code(clean, monkeypatch):
    sent = clean
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 0)
    _pair_a_phone()
    reply = app.start_phone_session()
    assert "couldn't reach" in reply.lower()
    assert "qr code" in reply.lower()   # no link to open by hand — see index.html/panels.js's phonePairingLayer
    # the whole fix: a scannable link to the actual address, not just "open its Jervis page" with nothing to open —
    # and with a relay configured, that's the relay's own stable link (https, with this install's computerId),
    # not a local IP that can change or require the same Wi-Fi
    pairing_update = next(p for p in sent if p.get("type") == "phone_pairing")["data"]
    assert pairing_update["pairUrl"] == f"https://relay.example/?computerId={app.relay.computer_id}"


def test_starting_a_session_with_no_reachable_phone_uses_the_local_address_without_a_relay(clean, monkeypatch):
    sent = clean
    monkeypatch.setattr(app, "RELAY_URL", "")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 0)
    _pair_a_phone()
    app.start_phone_session()
    pairing_update = next(p for p in sent if p.get("type") == "phone_pairing")["data"]
    assert "http://" in pairing_update["pairUrl"] and str(app.PHONE_WS_PORT) in pairing_update["pairUrl"]


def test_confirming_a_session_announces_connected(monkeypatch):
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 1)
    _pair_a_phone()
    app.start_phone_session()
    session = app.phone_server._session
    assert app.phone_server.decide_session(session.id, session.secret, True) is True
    announced = app.announcements.get(timeout=2)
    assert announced == "Your phone is connected."


def test_rejecting_a_session_announces_cancelled(monkeypatch):
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 1)
    _pair_a_phone()
    app.start_phone_session()
    session = app.phone_server._session
    assert app.phone_server.decide_session(session.id, session.secret, False) is True
    announced = app.announcements.get(timeout=2)
    assert announced == "Connection cancelled."


@pytest.mark.parametrize("said", ["disconnect my phone", "disconnect the phone session", "end the phone session"])
def test_disconnect_phrases_are_recognized_and_dispatched(said, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "disconnect_phone_session", lambda: calls.append(1) or "Disconnected.")
    assert app.handle_direct_command(said) == "Disconnected."
    assert calls == [1]


def test_disconnect_with_no_active_session():
    assert "No phone is connected" in app.disconnect_phone_session()


def test_disconnect_ends_the_current_session(monkeypatch):
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(push, "send_to_all", lambda *a, **kw: 1)
    _pair_a_phone()
    app.start_phone_session()
    session_id = app.phone_server.current_session_id()
    assert session_id is not None
    reply = app.disconnect_phone_session()
    assert reply == "Disconnected."
    assert app.phone_server.current_session_id() is None


# ---------- listing / forgetting paired phones ----------
def test_list_and_forget_paired_phones():
    assert "No phones" in app.list_paired_phones()
    app.phone_server.registry.add("Ariel's iPhone")
    assert "Ariel's iPhone" in app.list_paired_phones()
    forgotten = app.forget_paired_phones()
    assert "1" in forgotten
    assert app.phone_server.registry.list() == []


# ---------- the real wire protocol ----------
def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _run_server_and(port, coro):
    app.phone_server_loop = asyncio.get_event_loop()   # lets session_router reach a local phone (see app.py)
    async with websockets.serve(app.handle_phone_client, "127.0.0.1", port, process_request=app.local_process_request):
        return await coro


def _drive(port, coro):
    return asyncio.run(_run_server_and(port, coro))


def test_pairing_and_a_command_over_a_real_websocket():
    port = _free_port()
    app.phone_server.begin_pairing()
    code = app.phone_server._pairing.code

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "pair", "code": code, "deviceName": "Test Phone"}))
            paired = json.loads(await ws.recv())
            assert paired["type"] == "paired" and paired["deviceName"] == "Test Phone"
            await ws.send(json.dumps({"type": "command", "commandId": "c1", "commandType": "OPEN_APPLICATION",
                                      "payload": {"app_name": "Chrome"}}))
            result = json.loads(await ws.recv())
            assert result["status"] == "SUCCEEDED"
            return paired

    _drive(port, client())
    assert any("chrome" in a.lower() for a in sandbox.actions)


def test_a_local_session_attaches_and_runs_a_command_without_a_relay(monkeypatch):
    """The bug this fixes: "connect my phone" used to require a relay even for a phone on the very same Wi-Fi.
    Now, with no relay configured, a session attaches directly to this same local server — no relay needed."""
    monkeypatch.setattr(app, "RELAY_URL", "")
    port = _free_port()

    async def scenario():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as pairing_ws:
            app.phone_server.begin_pairing()
            code = app.phone_server._pairing.code
            await pairing_ws.send(json.dumps({"type": "pair", "code": code, "deviceName": "Test Phone"}))
            paired = json.loads(await pairing_ws.recv())

        assert paired["relayUrl"].startswith("ws://") and str(app.PHONE_WS_PORT) in paired["relayUrl"]
        key = phone_crypto.key_from_b64(paired["key"])
        session = app.phone_server.begin_session()
        assert app.phone_server.decide_session(session.id, session.secret, True)

        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "session_attach", "sessionId": session.id,
                                      "deviceId": paired["deviceId"], "token": paired["token"]}))
            ready = phone_crypto.decrypt(key, json.loads(await ws.recv()))
            assert ready == {"type": "session_ready"}

            command = phone_crypto.encrypt(key, {"type": "command", "commandId": "c1",
                                                  "commandType": "OPEN_APPLICATION", "payload": {"app_name": "Chrome"}})
            await ws.send(json.dumps(command))
            result = phone_crypto.decrypt(key, json.loads(await ws.recv()))
            assert result["type"] == "result" and result["commandId"] == "c1" and result["status"] == "SUCCEEDED"

    _drive(port, scenario())
    assert any("chrome" in a.lower() for a in sandbox.actions)


def test_the_local_decide_endpoint_approves_a_session_over_plain_http():
    port = _free_port()
    session = app.phone_server.begin_session()

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        path = (f"/decide?computerId=x&sessionId={session.id}&secret={session.secret}&decision=confirm")
        writer.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response

    response = _drive(port, client())
    assert b"200" in response.split(b"\r\n", 1)[0]
    assert session.state == "approved"


def test_the_local_decide_endpoint_rejects_a_bad_request():
    port = _free_port()

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /decide?sessionId=x HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response

    response = _drive(port, client())
    assert b"400" in response.split(b"\r\n", 1)[0]


def test_pairing_over_the_wire_tells_the_window_to_close_the_qr_panel(clean):
    sent = clean
    port = _free_port()
    app.phone_server.begin_pairing()
    code = app.phone_server._pairing.code

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "pair", "code": code, "deviceName": "Test Phone"}))
            await ws.recv()

    _drive(port, client())
    paired_update = next(p for p in sent if p.get("type") == "phone_paired")
    assert paired_update["deviceName"] == "Test Phone"


def test_clear_ui_update_removes_only_the_named_entry():
    """The actual fix for "the QR only showed once": phone_pairing used to go through send_ui_update_once, which
    is never replayed to a window that wasn't already open when it was sent — see that function's own docstring.
    It's send_ui_update now (replayed via latest_ui_updates to any window that connects, however late, same
    mechanism "weather"/"mic"/"timers" already rely on), and clear_ui_update (new) removes an entry once there's
    nothing left to show, from the same two call sites phone_paired/phone_notify_enabled already close the panel
    from — this test covers clear_ui_update itself; send_ui_update's one-line body is exercised elsewhere already."""
    app.latest_ui_updates["phone_pairing"] = {"type": "phone_pairing", "data": {"pairUrl": "https://x"}}
    app.latest_ui_updates["mic"] = {"type": "mic", "data": {"ok": True}}
    app.clear_ui_update("phone_pairing")
    assert "phone_pairing" not in app.latest_ui_updates
    assert app.latest_ui_updates["mic"] == {"type": "mic", "data": {"ok": True}}   # unrelated entries untouched
    app.clear_ui_update("phone_pairing")   # clearing an already-absent entry is a no-op, not an error
    del app.latest_ui_updates["mic"]


def test_a_phone_can_subscribe_to_notifications_before_pairing(clean):
    """Notifications are opt-in independently of pairing — the pairing confirmation itself needs to reach an
    unpaired phone, so push_subscribe must never require auth first."""
    sent = clean
    port = _free_port()

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "push_subscribe",
                                      "subscription": {"endpoint": "https://push.example/xyz",
                                                       "keys": {"p256dh": "a", "auth": "b"}}}))
            await asyncio.sleep(0.05)   # no reply is sent back; just give the handler a moment to process it

    _drive(port, client())
    assert app.push_store.list() == [{"endpoint": "https://push.example/xyz", "keys": {"p256dh": "a", "auth": "b"}}]
    # Closes the "scan to enable notifications" QR panel (see start_phone_session's fallback), the same way a
    # successful pairing closes its own QR panel with phone_paired.
    assert any(p.get("type") == "phone_notify_enabled" for p in sent)


def test_a_phone_can_unsubscribe():
    port = _free_port()
    app.push_store.add({"endpoint": "https://push.example/xyz", "keys": {"p256dh": "a", "auth": "b"}})

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "push_unsubscribe", "endpoint": "https://push.example/xyz"}))
            await asyncio.sleep(0.05)

    _drive(port, client())
    assert app.push_store.list() == []


def test_reconnecting_with_a_saved_token_authenticates_without_repairing():
    port = _free_port()
    device_id, token, _key = app.phone_server.registry.add("Ariel's iPhone")

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "auth", "deviceId": device_id, "token": token}))
            reply = json.loads(await ws.recv())
            assert reply == {"type": "authed", "deviceName": "Ariel's iPhone"}

    _drive(port, client())


def test_an_unpaired_connection_cannot_send_commands():
    port = _free_port()

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "command", "commandId": "c1", "commandType": "OPEN_APPLICATION",
                                      "payload": {"app_name": "Chrome"}}))
            result = json.loads(await ws.recv())
            assert result["status"] == "FAILED"

    _drive(port, client())
    assert not any("chrome" in a.lower() for a in sandbox.actions)


def test_a_wrong_token_is_refused():
    port = _free_port()
    device_id, _real_token, _key = app.phone_server.registry.add("Phone")

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "auth", "deviceId": device_id, "token": "guessed-wrong"}))
            reply = json.loads(await ws.recv())
            assert reply["type"] == "auth_error"

    _drive(port, client())


def test_a_duplicate_command_id_is_not_executed_twice_over_the_wire():
    port = _free_port()
    device_id, token, _key = app.phone_server.registry.add("Phone")

    async def client():
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(json.dumps({"type": "auth", "deviceId": device_id, "token": token}))
            await ws.recv()
            for _ in range(2):
                await ws.send(json.dumps({"type": "command", "commandId": "same-id",
                                          "commandType": "OPEN_APPLICATION", "payload": {"app_name": "Chrome"}}))
                result = json.loads(await ws.recv())
                assert result["status"] == "SUCCEEDED"

    _drive(port, client())
    assert sum(1 for a in sandbox.actions if "chrome" in a.lower()) == 1


def test_the_mobile_page_is_served_over_plain_http():
    port = _free_port()

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response

    response = _drive(port, client())
    assert b"200" in response.split(b"\r\n", 1)[0]
    assert b"Jervis" in response
    # Served locally, not by the relay — see phone_client.html's own comment on why this is its own placeholder
    # rather than inferred from __COMPUTER_ID__/__LOCAL_ADDRESS__ (str.replace() replaces every occurrence, which
    # used to make that inference silently wrong whenever a real id/address was substituted in).
    assert b'const SERVED_BY_RELAY = "0" === "1";' in response


def test_the_mobile_page_is_served_with_a_query_string_too():
    """The real bug this guards: the QR-pairing link is /?code=091468 — serve_static used to compare the *raw*
    request path (query string and all) against "/" and 404 on anything else, so that link never actually loaded
    the page at all. See phone_control.serve_static's docstring for the fix."""
    port = _free_port()

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /?code=091468&name=Test HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response

    response = _drive(port, client())
    assert b"200" in response.split(b"\r\n", 1)[0]
    assert b"Jervis" in response


def test_the_confirm_page_is_served():
    port = _free_port()

    async def client():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /confirm?sessionId=s1&secret=sec1 HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response

    response = _drive(port, client())
    assert b"200" in response.split(b"\r\n", 1)[0]
    assert b"Confirmed" in response and b"Not Confirmed" in response


def test_a_public_looking_address_is_refused(monkeypatch):
    port = _free_port()
    monkeypatch.setattr(phone_control, "is_private_address", lambda ip: False)

    async def client():
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"type": "auth", "deviceId": "x", "token": "y"}))
                await ws.recv()

    _drive(port, client())
