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
    [envelope] = sent
    assert phone_crypto.decrypt(key, envelope) == {"type": "session_ready"}


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
