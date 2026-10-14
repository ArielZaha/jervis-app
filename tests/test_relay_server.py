"""relay/server.py in isolation: the routing protocol between a "computer" connection and any number of "phone"
connections, and the plain-HTTP /decide endpoint a service worker's fetch() reaches it through. No Jarvis app code
is involved — this is the one piece of Jarvis infrastructure that runs somewhere other than the user's computer
(see relay/README.md), so it's tested as its own small protocol, the same way phone_control.py is tested without
a real websocket in test_phone_control.py and with one in test_phone_app.py.
"""
import asyncio
import json
import os
import sys

import pytest
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "relay"))
import server as relay_server  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    relay_server.computers.clear()
    relay_server.phone_owner.clear()
    relay_server.phone_sockets.clear()
    relay_server.computer_conns.clear()
    relay_server.pending_page_context.clear()
    # server.py assumes phone_client.html/phone_sw.js/confirm.html sit right next to it — true inside the Docker
    # image the Dockerfile builds (it COPYs them in alongside server.py), not when running straight from source.
    monkeypatch.setattr(relay_server, "PHONE_PAGE_PATH", os.path.join(REPO_ROOT, "phone_client.html"))
    monkeypatch.setattr(relay_server, "SERVICE_WORKER_PATH", os.path.join(REPO_ROOT, "phone_sw.js"))
    monkeypatch.setattr(relay_server, "CONFIRM_PAGE_PATH", os.path.join(REPO_ROOT, "confirm.html"))
    yield


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve(port):
    return websockets.serve(relay_server.handler, "127.0.0.1", port, process_request=relay_server.process_request)


def _drive(coro):
    return asyncio.run(coro)


async def _recv_json(ws):
    return json.loads(await ws.recv())


def test_a_phone_reaching_an_offline_computer_is_told_so():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
                await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "nobody-here"}))
                assert await _recv_json(phone) == {"type": "offline"}

    _drive(scenario())


def test_a_computer_then_a_phone_connect_and_are_introduced():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                assert await _recv_json(computer) == {"type": "hello_ok"}

                async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
                    await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "abc123"}))
                    hello_ok = await _recv_json(phone)
                    assert hello_ok["type"] == "hello_ok" and hello_ok["connId"]

                    introduced = await _recv_json(computer)
                    assert introduced == {"type": "phone_connected", "connId": hello_ok["connId"]}

    _drive(scenario())


def test_messages_are_routed_both_ways_by_connid():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()   # hello_ok

                async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
                    await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "abc123"}))
                    hello_ok = await _recv_json(phone)
                    conn_id = hello_ok["connId"]
                    await computer.recv()   # phone_connected

                    await phone.send(json.dumps({"type": "session_attach", "sessionId": "s1"}))
                    frame = await _recv_json(computer)
                    assert frame == {"type": "frame", "connId": conn_id,
                                     "payload": {"type": "session_attach", "sessionId": "s1"}}

                    await computer.send(json.dumps({"type": "frame", "connId": conn_id,
                                                    "payload": {"type": "session_ready"}}))
                    assert await _recv_json(phone) == {"type": "session_ready"}

    _drive(scenario())


def test_a_phone_disconnecting_tells_the_computer():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()

                phone = await websockets.connect(f"ws://127.0.0.1:{port}/")
                await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "abc123"}))
                hello_ok = await _recv_json(phone)
                await computer.recv()   # phone_connected
                await phone.close()

                gone = await _recv_json(computer)
                assert gone == {"type": "phone_disconnected", "connId": hello_ok["connId"]}

    _drive(scenario())


def test_end_conn_from_the_computer_closes_that_phones_connection():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()

                phone = await websockets.connect(f"ws://127.0.0.1:{port}/")
                await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "abc123"}))
                hello_ok = await _recv_json(phone)
                conn_id = hello_ok["connId"]
                await computer.recv()   # phone_connected

                await computer.send(json.dumps({"type": "end_conn", "connId": conn_id}))
                with pytest.raises(websockets.exceptions.ConnectionClosed):
                    await phone.recv()   # the relay closed it, not the phone itself

                # the computer is NOT told phone_disconnected for a hangup it asked for itself — it already knows
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(computer.recv(), timeout=0.2)

    _drive(scenario())


def test_end_conn_for_a_different_computers_connid_is_ignored():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer_a, \
                      websockets.connect(f"ws://127.0.0.1:{port}/") as computer_b:
                await computer_a.send(json.dumps({"type": "hello", "role": "computer", "computerId": "aaa"}))
                await computer_a.recv()
                await computer_b.send(json.dumps({"type": "hello", "role": "computer", "computerId": "bbb"}))
                await computer_b.recv()

                async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
                    await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "aaa"}))
                    hello_ok = await _recv_json(phone)
                    await computer_a.recv()   # phone_connected

                    # computer B tries to end a connId that belongs to computer A's phone — must be refused
                    await computer_b.send(json.dumps({"type": "end_conn", "connId": hello_ok["connId"]}))
                    await phone.send(json.dumps({"type": "still_here"}))
                    frame = await _recv_json(computer_a)
                    assert frame["payload"] == {"type": "still_here"}   # the connection is still very much alive

    _drive(scenario())


def test_a_computer_reconnecting_tells_every_attached_phone_its_offline():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            computer1 = await websockets.connect(f"ws://127.0.0.1:{port}/")
            await computer1.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
            await computer1.recv()

            async with websockets.connect(f"ws://127.0.0.1:{port}/") as phone:
                await phone.send(json.dumps({"type": "hello", "role": "phone", "computerId": "abc123"}))
                await phone.recv()   # hello_ok

                computer2 = await websockets.connect(f"ws://127.0.0.1:{port}/")
                await computer2.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer2.recv()

                assert await _recv_json(phone) == {"type": "offline"}
                await computer2.close()
            await computer1.close()

    _drive(scenario())


def test_decide_forwards_to_the_computer_and_returns_200():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()

                import urllib.request
                url = (f"http://127.0.0.1:{port}/decide?computerId=abc123&sessionId=s1&secret=sec1"
                      "&decision=confirm")
                response = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=5))
                assert response.status == 200

                delivered = await _recv_json(computer)
                assert delivered == {"type": "decide", "sessionId": "s1", "secret": "sec1", "decision": "confirm"}

    _drive(scenario())


async def _get(port, path):
    import urllib.request

    def fetch():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
            return resp.status, resp.read()

    return await asyncio.get_event_loop().run_in_executor(None, fetch)


def test_sw_js_is_served():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            status, body = await _get(port, "/sw.js")
            assert status == 200
            assert b"notificationclick" in body

    _drive(scenario())


def test_the_confirm_page_is_served():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            status, body = await _get(port, "/confirm?sessionId=s1&secret=sec1")
            assert status == 200
            assert b"Confirmed" in body and b"Not Confirmed" in body

    _drive(scenario())


def test_the_phone_page_is_served_without_a_computerid_and_has_empty_placeholders():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            status, body = await _get(port, "/")
            assert status == 200
            assert b'const RELAY_COMPUTER_ID = "";' in body
            assert b'const VAPID_PUBLIC_KEY = "";' in body
            assert b'const LOCAL_ADDRESS = "";' in body

    _drive(scenario())


def test_the_phone_page_fetches_live_context_from_an_online_computer():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()

                async def answer():
                    request = await _recv_json(computer)
                    assert request["type"] == "get_page_context"
                    await computer.send(json.dumps({"type": "page_context", "requestId": request["requestId"],
                                                    "vapidKey": "real-vapid-key",
                                                    "localAddress": "http://192.168.1.50:8766"}))

                answerer = asyncio.create_task(answer())
                status, body = await _get(port, "/?computerId=abc123")
                await answerer
                assert status == 200
                assert b'const RELAY_COMPUTER_ID = "abc123";' in body
                assert b'const VAPID_PUBLIC_KEY = "real-vapid-key";' in body
                assert b'const LOCAL_ADDRESS = "http://192.168.1.50:8766";' in body

    _drive(scenario())


def test_the_phone_page_knows_it_was_served_by_the_relay_even_with_a_real_computerid():
    """Regression: __SERVED_BY_RELAY__ is its own placeholder, not inferred by comparing the (now-substituted)
    RELAY_COMPUTER_ID against its own raw placeholder text again — str.replace() replaces every occurrence, so
    that comparison used to see the real id on both sides and silently read as "not served by the relay" on
    exactly the success path (a real, known computerId) where it mattered most."""
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            status, body = await _get(port, "/?computerId=abc123")
            assert status == 200
            assert b'const RELAY_COMPUTER_ID = "abc123";' in body
            assert b'const SERVED_BY_RELAY = "1" === "1";' in body

    _drive(scenario())


def test_the_phone_page_still_loads_with_empty_context_when_the_computer_never_answers(monkeypatch):
    monkeypatch.setattr(relay_server, "PAGE_CONTEXT_TIMEOUT", 0.3)
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            async with websockets.connect(f"ws://127.0.0.1:{port}/") as computer:
                await computer.send(json.dumps({"type": "hello", "role": "computer", "computerId": "abc123"}))
                await computer.recv()
                # the computer never replies to get_page_context — the page load must not hang forever on it
                status, body = await _get(port, "/?computerId=abc123")
                assert status == 200
                assert b'const RELAY_COMPUTER_ID = "abc123";' in body
                assert b'const VAPID_PUBLIC_KEY = "";' in body
                assert b'const LOCAL_ADDRESS = "";' in body

    _drive(scenario())


def test_the_phone_page_loads_with_empty_context_for_an_unknown_computerid():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            status, body = await _get(port, "/?computerId=nobody-here")
            assert status == 200
            assert b'const RELAY_COMPUTER_ID = "nobody-here";' in body
            assert b'const VAPID_PUBLIC_KEY = "";' in body

    _drive(scenario())


def test_decide_for_an_offline_computer_returns_503():
    port = _free_port()

    async def scenario():
        async with await _serve(port):
            import urllib.error
            import urllib.request
            url = f"http://127.0.0.1:{port}/decide?computerId=nobody&sessionId=s1&secret=sec1&decision=confirm"
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: urllib.request.urlopen(url, timeout=5))
                assert False, "expected an HTTP error"
            except urllib.error.HTTPError as e:
                assert e.code == 503

    _drive(scenario())
