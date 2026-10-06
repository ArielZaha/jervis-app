"""phone_session.PhoneSessionRouter: the session protocol shared by the local LAN phone server (app.py's
handle_phone_client) and the relay transport (relay_client.py) — attach, encrypted commands, voice, disconnect.
Driven directly here with fake (plain, synchronous) schedule_send/schedule_end callbacks, exactly the contract a
real transport provides — no real websocket or event loop needed, since the router itself never does any loop
scheduling; that's each transport's own job (see test_relay_client.py for the relay one).
"""
import asyncio
import base64

import pytest

import phone_control
import phone_crypto
import phone_session


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def server(tmp_path):
    registry = phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))
    calls = []

    def execute(command_type, payload):
        calls.append((command_type, payload))
        return "did it"

    s = phone_control.PhoneControlServer(execute=execute, registry=registry)
    s.calls = calls
    return s


def _router(server, transcribe=None, deliver=None):
    return phone_session.PhoneSessionRouter(
        server, transcribe or (lambda pcm, rate: ""), deliver or (lambda text, session_id: None))


def _recorder():
    sent = []
    return sent, sent.append


def test_attaching_without_an_approved_session_sends_session_error(server):
    router = _router(server)
    sent, send = _recorder()
    device_id, token, _key = server.registry.add("Phone")
    session = server.begin_session()   # never decided

    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id,
                                    "deviceId": device_id, "token": token}, send))

    assert sent == [{"type": "session_error", "message": "That connection request is no longer valid."}]
    assert "conn-1" not in router._conns


def test_attaching_an_approved_session_sends_an_encrypted_session_ready(server):
    router = _router(server)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)

    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id,
                                    "deviceId": device_id, "token": token}, send))

    assert "conn-1" in router._conns
    assert router._conns["conn-1"]["key"] == key
    ready, info = sent
    assert phone_crypto.decrypt(key, ready) == {"type": "session_ready"}
    assert phone_crypto.decrypt(key, info)["type"] == "session_info"


def test_auto_attach_skips_the_approval_dance_for_an_already_paired_device(server):
    """The saved-bookmark reconnect (phone_client.html's connectSession(null)): no "connect my phone" push, no
    session_id handed to the phone beforehand — just the device's own credentials, which is already proof enough."""
    router = _router(server)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")

    _run(router.on_frame("conn-1", {"type": "auto_attach", "deviceId": device_id, "token": token}, send))

    assert "conn-1" in router._conns
    assert router._conns["conn-1"]["key"] == key
    ready, info = sent
    assert phone_crypto.decrypt(key, ready) == {"type": "session_ready"}
    assert phone_crypto.decrypt(key, info)["type"] == "session_info"
    assert server.current_session_id() is not None   # a real session now exists, same as a tapped notification


def test_auto_attach_with_bad_credentials_sends_session_error(server):
    router = _router(server)
    sent, send = _recorder()

    _run(router.on_frame("conn-1", {"type": "auto_attach", "deviceId": "nope", "token": "nope"}, send))

    assert "conn-1" not in router._conns
    assert sent == [{"type": "session_error", "code": "unpaired",
                     "message": "This phone isn't paired anymore. Pair again."}]


def test_a_command_frame_is_decrypted_run_and_the_result_re_encrypted(server):
    router = _router(server)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id,
                                    "deviceId": device_id, "token": token}, send))
    sent.clear()

    envelope = phone_crypto.encrypt(key, {"type": "command", "commandId": "c1", "commandType": "OPEN_APPLICATION",
                                          "payload": {"app_name": "Chrome"}})
    _run(router.on_frame("conn-1", envelope, send))

    assert server.calls == [("OPEN_APPLICATION", {"app_name": "Chrome"})]
    [reply] = sent
    decrypted = phone_crypto.decrypt(key, reply)
    assert decrypted == {"type": "result", "commandId": "c1", "status": "SUCCEEDED", "message": "did it"}


def test_a_frame_encrypted_with_the_wrong_key_is_silently_dropped(server):
    router = _router(server)
    sent, send = _recorder()
    device_id, token, _key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id,
                                    "deviceId": device_id, "token": token}, send))
    sent.clear()

    wrong_envelope = phone_crypto.encrypt(phone_crypto.new_key(), {"type": "command", "commandId": "c1",
                                                                    "commandType": "PAUSE_MUSIC"})
    _run(router.on_frame("conn-1", wrong_envelope, send))

    assert server.calls == []
    assert sent == []


def test_voice_chunks_are_buffered_and_handed_off_on_voice_end(server, monkeypatch):
    """voice_end hands the accumulated audio to a background thread (so a slow decode/transcription never blocks
    the caller's event loop) — captured here instead of racing the real thread, for a deterministic test."""
    handed_off = []
    monkeypatch.setattr(phone_session.threading, "Thread",
                        lambda target, args, **kw: type("T", (), {"start": lambda self: handed_off.append(args)})())
    router = _router(server)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))

    async def scenario():
        await router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "voice_start"}), send)
        chunk_a = base64.b64encode(b"first-chunk-").decode("ascii")
        chunk_b = base64.b64encode(b"second-chunk").decode("ascii")
        await router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "voice_chunk", "data": chunk_a}), send)
        await router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "voice_chunk", "data": chunk_b}), send)
        await router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "voice_end"}), send)

    _run(scenario())
    assert handed_off == [(b"first-chunk-second-chunk", session.id)]
    assert router._conns["conn-1"].get("voice") is None   # the buffer is cleared (popped) once handed off


def test_transcribe_and_deliver_delivers_the_transcribed_text(server, monkeypatch):
    monkeypatch.setattr(phone_session, "decode_audio_to_pcm16", lambda audio_bytes, sample_rate=16000: b"\x00\x00" * 100)
    delivered = []
    router = _router(server, transcribe=lambda pcm, rate: "play some jazz",
                     deliver=lambda text, session_id: delivered.append((text, session_id)))
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, lambda obj: None))

    router._transcribe_and_deliver(b"some encoded audio bytes", session.id)

    assert delivered == [("play some jazz", session.id)]


def test_transcribe_and_deliver_falls_back_to_sorry_when_nothing_was_heard(server, monkeypatch):
    monkeypatch.setattr(phone_session, "decode_audio_to_pcm16", lambda audio_bytes, sample_rate=16000: b"")
    router = _router(server, transcribe=lambda pcm, rate: "should never be called on empty pcm")
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))
    sent.clear()

    router._transcribe_and_deliver(b"silence", session.id)

    [envelope] = sent
    assert phone_crypto.decrypt(key, envelope) == {"type": "reply", "text": "Sorry, I didn't catch that."}


def test_transcribe_and_deliver_fails_closed_when_decoding_raises(server, monkeypatch):
    def boom(audio_bytes, sample_rate=16000):
        raise ValueError("not a real audio container")
    monkeypatch.setattr(phone_session, "decode_audio_to_pcm16", boom)
    router = _router(server, transcribe=lambda pcm, rate: "should never be reached")
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))
    sent.clear()

    router._transcribe_and_deliver(b"garbage", session.id)   # must not raise out of what's really a thread target

    [envelope] = sent
    assert phone_crypto.decrypt(key, envelope) == {"type": "reply", "text": "Sorry, I didn't catch that."}


# ---------- pre-session, device-key-authenticated messages (no "connect my phone" session needed at all) ----------
# Right now just push_subscribe/push_unsubscribe — see relay/server.py's docstring for why this exists: a stable
# relay link for enabling notifications, instead of needing the phone on the same Wi-Fi as the computer.

def test_a_device_message_registers_a_push_subscription(server):
    subscribed = []
    router = _router(server)
    router.on_push_subscribe = subscribed.append
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")

    envelope = phone_crypto.encrypt(key, {"type": "push_subscribe",
                                          "subscription": {"endpoint": "https://push.example/xyz"}})
    _run(router.on_frame("conn-1", {**envelope, "deviceId": device_id}, send))

    assert subscribed == [{"endpoint": "https://push.example/xyz"}]
    assert "conn-1" not in router._conns   # answered once and forgotten, not a live/attached connection
    [reply] = sent
    assert phone_crypto.decrypt(key, reply) == {"type": "subscribed"}


def test_a_device_message_unsubscribes(server):
    unsubscribed = []
    router = _router(server)
    router.on_push_unsubscribe = unsubscribed.append
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")

    envelope = phone_crypto.encrypt(key, {"type": "push_unsubscribe", "endpoint": "https://push.example/xyz"})
    _run(router.on_frame("conn-1", {**envelope, "deviceId": device_id}, send))

    assert unsubscribed == ["https://push.example/xyz"]
    assert sent == []   # unsubscribe has nothing to confirm back


def test_a_device_message_from_an_unknown_device_is_dropped(server):
    subscribed = []
    router = _router(server)
    router.on_push_subscribe = subscribed.append
    sent, send = _recorder()
    key = phone_crypto.new_key()   # never registered with this server

    envelope = phone_crypto.encrypt(key, {"type": "push_subscribe", "subscription": {"endpoint": "x"}})
    _run(router.on_frame("conn-1", {**envelope, "deviceId": "no-such-device"}, send))

    assert subscribed == []
    assert sent == []


def test_a_device_message_encrypted_with_the_wrong_key_is_dropped(server):
    subscribed = []
    router = _router(server)
    router.on_push_subscribe = subscribed.append
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    wrong_envelope = phone_crypto.encrypt(phone_crypto.new_key(),
                                          {"type": "push_subscribe", "subscription": {"endpoint": "x"}})

    _run(router.on_frame("conn-1", {**wrong_envelope, "deviceId": device_id}, send))

    assert subscribed == []
    assert sent == []


def test_a_device_message_with_no_subscribe_callback_configured_is_a_silent_no_op(server):
    router = _router(server)   # on_push_subscribe defaults to None
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    envelope = phone_crypto.encrypt(key, {"type": "push_subscribe", "subscription": {"endpoint": "x"}})

    _run(router.on_frame("conn-1", {**envelope, "deviceId": device_id}, send))   # must not raise
    assert sent == []


def test_disconnect_message_ends_the_session(server):
    router = _router(server)
    sent, send = _recorder()
    ended = []
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send, schedule_end=lambda: ended.append(1)))
    assert server.current_session_id() == session.id

    _run(router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "disconnect"}), send))
    assert server.current_session_id() is None
    assert "conn-1" not in router._conns
    assert ended == [1]   # the phone-initiated case still ends the transport too, see PhoneSessionRouter.end_session


def test_a_text_message_is_delivered_like_transcribed_voice_would_be(server):
    """The phone's typed chat box (phone_client.html's sendChatText): same destination as a voice recording once
    transcribed (deliver_voice_text), just without the audio round trip — it's already text."""
    delivered = []
    router = _router(server, deliver=lambda text, session_id: delivered.append((text, session_id)))
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))

    _run(router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "text", "text": "what's the weather"}), send))

    assert delivered == [("what's the weather", session.id)]


def test_an_empty_or_whitespace_text_message_delivers_nothing(server):
    delivered = []
    router = _router(server, deliver=lambda text, session_id: delivered.append((text, session_id)))
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))

    _run(router.on_frame("conn-1", phone_crypto.encrypt(key, {"type": "text", "text": "   "}), send))

    assert delivered == []


def test_deliver_reply_reaches_the_attached_connection(server):
    router = _router(server)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("conn-1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                    "token": token}, send))
    sent.clear()

    router.deliver_reply(session.id, "Playing jazz now.")

    [envelope] = sent
    assert phone_crypto.decrypt(key, envelope) == {"type": "reply", "text": "Playing jazz now."}


def test_deliver_reply_with_no_attached_connection_is_a_silent_no_op(server):
    router = _router(server)
    router.deliver_reply("no-such-session", "hello?")   # must not raise


def test_forget_matching_only_drops_matched_connections(server):
    router = _router(server)
    device_id, token, _key = server.registry.add("Phone")
    session = server.begin_session()
    server.decide_session(session.id, session.secret, True)
    _run(router.on_frame("relay:1", {"type": "session_attach", "sessionId": session.id, "deviceId": device_id,
                                     "token": token}, lambda obj: None))
    router._conns["local:1"] = dict(router._conns["relay:1"])   # a second, independent connection to protect

    router.forget_matching(lambda c: c.startswith("relay:"))

    assert "relay:1" not in router._conns
    assert "local:1" in router._conns


def test_decoding_a_real_encoded_clip_roundtrips_to_pcm():
    pytest.importorskip("av")
    import io

    import av
    import numpy as np

    sample_rate = 48000
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False))
           ).astype(np.float32)
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="webm")
    stream = container.add_stream("libopus", rate=sample_rate)
    frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="flt", layout="mono")
    frame.rate = sample_rate
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()

    pcm = phone_session.decode_audio_to_pcm16(buf.getvalue(), sample_rate=16000)
    assert len(pcm) > 0
    assert abs(len(pcm) / 2 / 16000 - 0.5) < 0.05   # about half a second of 16kHz mono s16 audio, give or take


# ---------- relay attach without the token ever passing through the relay ----------
def test_auto_attach_with_a_fresh_key_proof_attaches_without_a_token(server):
    import time
    router = _router(server)
    sent, send = _recorder()
    device_id, _token, key = server.registry.add("Phone")
    proof = phone_crypto.encrypt(key, {"type": "attach", "deviceId": device_id, "ts": time.time() * 1000})

    _run(router.on_frame("conn-1", {"type": "auto_attach", "deviceId": device_id, "proof": proof}, send))

    assert "conn-1" in router._conns
    assert phone_crypto.decrypt(key, sent[0]) == {"type": "session_ready"}


@pytest.mark.parametrize("mutate", ["stale", "other_device", "wrong_key", "garbage"])
def test_auto_attach_refuses_a_bad_key_proof(server, mutate):
    import time
    router = _router(server)
    sent, send = _recorder()
    device_id, _token, key = server.registry.add("Phone")
    ts = time.time() * 1000 - (60 * 60 * 1000 if mutate == "stale" else 0)
    claimed = "someone-else" if mutate == "other_device" else device_id
    use_key = phone_crypto.new_key() if mutate == "wrong_key" else key
    proof = {"n": "x", "ct": "y"} if mutate == "garbage" else \
        phone_crypto.encrypt(use_key, {"type": "attach", "deviceId": claimed, "ts": ts})

    _run(router.on_frame("conn-1", {"type": "auto_attach", "deviceId": device_id, "proof": proof}, send))

    assert "conn-1" not in router._conns
    assert sent[0]["type"] == "session_error"


def test_presence_is_reported_on_attach_and_on_forget(server):
    seen = []
    router = phone_session.PhoneSessionRouter(server, lambda pcm, rate: "", lambda text, sid: None,
                                              on_presence=seen.append)
    _sent, send = _recorder()
    device_id, token, _key = server.registry.add("Galaxy")
    _run(router.on_frame("conn-1", {"type": "auto_attach", "deviceId": device_id, "token": token}, send))
    router.forget("conn-1")
    assert seen == [["Galaxy"], []]


def test_voice_cancel_drops_the_recording(server):
    transcribed = []
    router = _router(server, transcribe=lambda pcm, rate: transcribed.append(pcm) or "x")
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Phone")
    _run(router.on_frame("c", {"type": "auto_attach", "deviceId": device_id, "token": token}, send))
    for message in ({"type": "voice_start"}, {"type": "voice_chunk", "data": base64.b64encode(b"abc").decode()},
                    {"type": "voice_cancel"}, {"type": "voice_end"}):
        _run(router.on_frame("c", phone_crypto.encrypt(key, message), send))
    assert router._conns["c"]["voice"] is None and transcribed == []


# ---------- the native phone app (mobile/): its own agent, encrypted on the Wi-Fi too ----------
def _attached_router(server, local, encrypt=False, **callbacks):
    router = phone_session.PhoneSessionRouter(server, lambda pcm, rate: "", callbacks.pop("deliver", lambda t, s, **k: None), **callbacks)
    sent, send = _recorder()
    device_id, token, key = server.registry.add("Galaxy")
    _run(router.on_frame("c", {"type": "auto_attach", "deviceId": device_id, "token": token, "encrypt": encrypt}, send, local=local))
    return router, sent, send, key


def test_the_app_can_ask_for_an_encrypted_session_on_the_wifi(server):
    router, sent, _send, key = _attached_router(server, local=True, encrypt=True)
    assert router._conns["c"]["local"] is False
    assert phone_crypto.decrypt(key, sent[0]) == {"type": "session_ready"}
    plain_router, plain_sent, _s, _k = _attached_router(server, local=True)   # the web page on plain http: as before
    assert plain_router._conns["c"]["local"] is True and plain_sent[0] == {"type": "session_ready"}


def test_the_ai_key_only_goes_out_over_an_encrypted_session(server):
    cfg = lambda: {"provider": "groq", "apiKey": "gsk_secret", "model": "m"}
    router, sent, send, key = _attached_router(server, local=True, encrypt=True, get_ai_config=cfg)
    _run(router.on_frame("c", phone_crypto.encrypt(key, {"type": "get_ai_config"}), send, local=True))
    assert phone_crypto.decrypt(key, sent[-1]) == {"type": "ai_config", "provider": "groq", "apiKey": "gsk_secret", "model": "m"}
    plain, plain_sent, plain_send, _k = _attached_router(server, local=True, get_ai_config=cfg)
    _run(plain.on_frame("c", {"type": "get_ai_config"}, plain_send, local=True))
    assert plain_sent[-1] == {"type": "ai_config", "error": "encrypted session required"}
    assert "gsk_secret" not in str(plain_sent)


def test_a_request_id_comes_back_on_its_reply(server):
    delivered = []
    router, sent, send, key = _attached_router(server, local=False, deliver=lambda t, s, **k: delivered.append((t, k)))
    _run(router.on_frame("c", phone_crypto.encrypt(key, {"type": "text", "text": "open youtube", "requestId": "r7"}), send))
    assert delivered == [("open youtube", {"request_id": "r7"})]
    router.deliver_reply(router._conns["c"]["session_id"], "Opened YouTube.", "r7")
    assert phone_crypto.decrypt(key, sent[-1]) == {"type": "reply", "text": "Opened YouTube.", "requestId": "r7"}


def test_a_turn_handled_on_the_phone_is_reported_to_the_computer(server):
    turns = []
    router, sent, send, key = _attached_router(server, local=False, on_phone_turn=lambda u, r, n: turns.append((u, r, n)))
    _run(router.on_frame("c", phone_crypto.encrypt(key, {"type": "phone_turn", "user": "Open Spotify", "reply": "Opened Spotify."}), send))
    assert turns == [("Open Spotify", "Opened Spotify.", "Galaxy")]
