"""Pairing through the relay (the phone's always-on app): "Connect my phone" shows a QR code carrying a one-time
key; the phone seals its request with it and the computer seals the new credentials back. Whatever sits in between
(the relay) sees only envelopes it can't open. Driven on the router directly, as test_phone_session.py does."""
import asyncio
import time

import pytest

import phone_control
import phone_crypto
import phone_session
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


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def world(tmp_path):
    registry = phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))
    server = phone_control.PhoneControlServer(execute=lambda *a: "ok", registry=registry)
    paired = []

    def on_secure_pair(secret, name, replaces):
        result = server.try_pair_secure(secret, name, replaces=replaces)
        if result is None:
            return None
        device_id, token, key = result
        paired.append(device_id)
        return {"deviceId": device_id, "token": token, "key": phone_crypto.key_to_b64(key), "deviceName": name,
                "computerId": "computer-1", "relayUrl": "wss://relay.example/", "ai": {"apiKey": "the-ai-key"}}

    router = phone_session.PhoneSessionRouter(server, lambda pcm, rate: "", lambda text, session_id: None,
                                              on_secure_pair=on_secure_pair)
    return {"server": server, "router": router, "paired": paired, "registry": registry}


def _ask(world, secret, age=0, **fields):
    sent = []
    request = {"type": "pair", "deviceName": "iPhone", "ts": (time.time() - age) * 1000, **fields}
    _run(world["router"].on_frame("relay:c1", {"type": "pair_secure", "envelope": phone_crypto.encrypt(secret, request)},
                                  sent.append))
    return sent


def test_the_phone_pairs_with_the_key_from_the_qr_code_and_everything_travels_sealed(world):
    server = world["server"]
    server.begin_pairing()
    secret = server.pairing_secret()
    sent = _ask(world, secret)
    assert [m["type"] for m in sent] == ["paired_secure"]
    # what the relay sees: an envelope, with no token, key or AI key readable in it
    assert set(sent[0]["envelope"]) == {"n", "ct"} and "the-ai-key" not in str(sent[0])
    answer = phone_crypto.decrypt(secret, sent[0]["envelope"])
    assert answer["type"] == "paired" and answer["deviceId"] == world["paired"][0] and answer["ai"]["apiKey"] == "the-ai-key"
    # the credentials are real: this device can authenticate, and its key is the one stored for it
    assert world["registry"].authenticate(answer["deviceId"], answer["token"])["name"] == "iPhone"
    assert phone_crypto.key_to_b64(world["registry"].key_for(answer["deviceId"])) == answer["key"]


def test_the_key_is_single_use(world):
    server = world["server"]
    server.begin_pairing()
    secret = server.pairing_secret()
    assert _ask(world, secret)[0]["type"] == "paired_secure"
    again = _ask(world, secret)
    assert again[0]["type"] == "pair_error" and len(world["paired"]) == 1


@pytest.mark.parametrize("how", ["another key", "no pairing open", "an old request", "expired"])
def test_nothing_else_pairs(world, how, monkeypatch):
    server = world["server"]
    if how != "no pairing open":
        server.begin_pairing()
    secret = server.pairing_secret()
    if how == "another key":
        sent = _ask(world, phone_crypto.new_key())
    elif how == "no pairing open":
        sent = _ask(world, phone_crypto.new_key())
    elif how == "an old request":
        sent = _ask(world, secret, age=3600)
    else:
        monkeypatch.setattr(phone_control, "PAIR_CODE_TTL", 0)
        server._pairing.expires_at = time.time() - 1
        sent = _ask(world, secret)
    assert [m["type"] for m in sent] == ["pair_error"] and world["paired"] == []
    assert "token" not in str(sent) and world["registry"].list() == []


def test_guessing_closes_the_pairing_like_wrong_codes_do(world):
    server = world["server"]
    server.begin_pairing()
    secret = server.pairing_secret()
    for _ in range(phone_control.MAX_PAIR_ATTEMPTS):
        _ask(world, phone_crypto.new_key())
    assert server.pairing_secret() is None
    assert _ask(world, secret)[0]["type"] == "pair_error"   # even the right key, now: a fresh "Connect my phone" is needed


def test_pairing_again_replaces_this_phones_old_record(world):
    server = world["server"]
    old_id, old_token, _ = world["registry"].add("iPhone")
    server.begin_pairing()
    _ask(world, server.pairing_secret(), previousDeviceId=old_id, previousToken=old_token)
    assert world["registry"].authenticate(old_id, old_token) is None and len(world["registry"].list()) == 1


def test_the_qr_leads_to_the_always_on_app_only_when_the_relay_is_reachable(monkeypatch):
    sent = {}
    monkeypatch.setenv("JARVIS_PHONE_CONTROL", "on")
    monkeypatch.setattr(app, "send_ui_update", lambda kind, data: sent.update({kind: data}))
    monkeypatch.setattr(app, "RELAY_URL", "wss://relay.example/")
    monkeypatch.setattr(app.relay, "_ws", None)
    app.start_phone_pairing()
    assert sent["phone_pairing"]["secure"] is False and sent["phone_pairing"]["pairUrl"].startswith("http://")
    monkeypatch.setattr(app.relay, "_ws", object())
    reply = app.start_phone_pairing()
    info = sent["phone_pairing"]
    assert info["secure"] is True and "Scan in the Jarvis app" in reply
    link, fragment = info["pairUrl"].split("#")
    assert link == f"https://relay.example/?computerId={app.relay.computer_id}"
    # the key rides only in the fragment (which no server receives), and it is this pairing's own
    key = fragment.removeprefix("pair=")
    assert phone_crypto.key_from_b64(key + "=" * (-len(key) % 4)) == app.phone_server.pairing_secret()
    assert info["localPairUrl"].startswith("http://") and info["code"] in info["localPairUrl"]
