"""The phone-session protocol, shared by the two ways a phone can reach Jervis once "connect my phone" has been
confirmed: directly over the local LAN (app.py's handle_phone_client — exactly like PHONE_COMMANDS already works,
just extended) or through a relay (relay_client.py) for reaching it from anywhere else. Both are just different
ways to deliver the same encrypted frames to and from the same phone; this module owns the actual protocol
(attach, encrypted commands, voice, disconnect) once, so neither transport reimplements it.

It also owns one thing that isn't part of a session at all: PhoneSessionRouter._handle_device_message, an already-
paired device registering for push notifications (or unregistering) with nothing more than its own device key as
proof — no session, no approval needed, since a notification only ever informs (see push.py). This is what lets
the relay serve a stable link for that one-time step (relay/server.py) without needing a live "connect my phone"
approval dance just to turn notifications on.

See phone_control.py's module docstring for the pairing-vs-session story, and phone_crypto.py for why frames are
encrypted at the application layer at all (a relay is a middlebox that would otherwise see everything in transit;
the local LAN path isn't, but reusing one protocol for both is simpler, and the local path was already implicitly
trusted the same way PHONE_COMMANDS over it always has been).
"""
import asyncio
import base64
import io
import threading
import time

import phone_crypto

VOICE_MAX_SECONDS = 20          # a push-to-talk phrase longer than this is almost certainly a stuck button
VOICE_MAX_BYTES = 4 * 1024 * 1024
# A pre-session, device-key-authenticated message (see PhoneSessionRouter._handle_device_message) — distinguished
# from a session_attach (plaintext, has "type") by shape alone: {"deviceId": "...", "n": "...", "ct": "..."}.
DEVICE_MESSAGE_ENVELOPE = frozenset({"deviceId", "n", "ct"})


def decode_audio_to_pcm16(container_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Whatever container the phone's MediaRecorder produced (webm/opus on Chrome/Android, mp4/aac on Safari/iOS,
    ...) decoded to raw 16-bit mono PCM at `sample_rate`, via the same PyAV that faster-whisper already depends on
    (see stt_local.py) — already bundled, nothing new to install."""
    import av
    pcm = bytearray()
    with av.open(io.BytesIO(container_bytes)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        for packet in container.demux(stream):
            for frame in packet.decode():
                for resampled in resampler.resample(frame):
                    pcm += bytes(resampled.planes[0])[:resampled.samples * 2]
        for resampled in resampler.resample(None):   # flush: the last few samples otherwise stay buffered
            pcm += bytes(resampled.planes[0])[:resampled.samples * 2]
    return bytes(pcm)


class PhoneSessionRouter:
    """Owns every attached session's live state (conn_id -> device/key/session_id/voice buffer) and the protocol
    for it, independent of how a conn_id's bytes actually travel.

    A transport calls `on_frame(conn_id, payload, schedule_send, schedule_end)` for each message it receives from
    a phone on that connection:
      - `schedule_send(obj)`: a plain, thread-safe function that delivers `obj` (a JSON-able dict) back to that
        phone however the transport does that (a direct websocket.send for the local server, a relay-routed frame
        for relay_client.py) — thread-safe because deliver_reply()/end_session() below are called from the main
        command loop's own thread, not whichever asyncio loop the connection actually lives on.
      - `schedule_end(*)`: same idea, for proactively ending the connection from this side (used when a "connect
        my phone" session is ended by something other than the phone closing its own connection, e.g. "disconnect
        my phone" spoken at the computer).
    """

    def __init__(self, phone_server, transcribe_pcm16, deliver_voice_text,
                 on_push_subscribe=None, on_push_unsubscribe=None):
        self.phone_server = phone_server
        self.transcribe_pcm16 = transcribe_pcm16
        self.deliver_voice_text = deliver_voice_text
        self.on_push_subscribe = on_push_subscribe       # (subscription: dict) -> None, e.g. push_store.add
        self.on_push_unsubscribe = on_push_unsubscribe   # (endpoint: str) -> None, e.g. push_store.remove
        self._conns = {}   # conn_id -> {"device_id","key","session_id","voice","schedule_send","schedule_end"}

    def forget(self, conn_id) -> None:
        self._conns.pop(conn_id, None)

    def forget_matching(self, predicate) -> None:
        """Drops every connection whose conn_id satisfies `predicate` — for a transport to clean up its own
        entries (e.g. relay_client.py, on reconnecting to the relay) without touching another transport's."""
        for conn_id in [c for c in self._conns if predicate(c)]:
            self._conns.pop(conn_id, None)

    def deliver_reply(self, session_id: str, text: str) -> None:
        """A reply to something a phone said, once the main loop has worked one out (app.py calls this from the
        three places a turn's reply is finalized — see PhoneVoiceInput)."""
        conn_id = self.phone_server.active_session_conn(session_id)
        state = self._conns.get(conn_id) if conn_id else None
        if state:
            state["schedule_send"](phone_crypto.encrypt(state["key"], {"type": "reply", "text": text}))

    def end_session(self, session_id: str) -> None:
        conn_id = self.phone_server.active_session_conn(session_id)
        self.phone_server.end_session(session_id)
        if conn_id:
            state = self._conns.pop(conn_id, None)
            if state and state.get("schedule_end"):
                state["schedule_end"]()

    async def on_frame(self, conn_id, payload, schedule_send, schedule_end=None) -> None:
        if not isinstance(payload, dict):
            return
        state = self._conns.get(conn_id)
        if state is None:
            if payload.get("type") == "session_attach":
                await self._attach(conn_id, payload, schedule_send, schedule_end)
            elif DEVICE_MESSAGE_ENVELOPE <= payload.keys():
                await self._handle_device_message(payload, schedule_send)
            # else: nothing else is meaningful before a session is attached
            return
        message = phone_crypto.decrypt(state["key"], payload)
        if message is None:
            return
        await self._on_decrypted(conn_id, state, message)

    async def _handle_device_message(self, payload: dict, schedule_send) -> None:
        """A message an already-paired device can send without a "connect my phone" session at all — right now
        just registering for push notifications (see relay/server.py's docstring on why this exists: a stable
        relay link for that one-time step, instead of the phone's local Wi-Fi address). Proof it's really that
        device is the envelope decrypting at all: only that device's own key, handed to it at pairing, could have
        produced it — no separate token needed (unlike attach_session, this never gets a schedule_end/conn_id
        registered in self._conns; it's answered once and forgotten, not a live connection)."""
        key = self.phone_server.registry.key_for(str(payload.get("deviceId") or ""))
        if key is None:
            return
        message = phone_crypto.decrypt(key, payload)
        if message is None:
            return
        kind = message.get("type")
        if kind == "push_subscribe" and self.on_push_subscribe:
            subscription = message.get("subscription")
            if isinstance(subscription, dict) and subscription.get("endpoint"):
                self.on_push_subscribe(subscription)
                schedule_send(phone_crypto.encrypt(key, {"type": "subscribed"}))
        elif kind == "push_unsubscribe" and self.on_push_unsubscribe:
            endpoint = str(message.get("endpoint") or "")
            if endpoint:
                self.on_push_unsubscribe(endpoint)

    async def _attach(self, conn_id, payload: dict, schedule_send, schedule_end) -> None:
        key = self.phone_server.attach_session(str(payload.get("sessionId") or ""),
                                                str(payload.get("deviceId") or ""), str(payload.get("token") or ""),
                                                conn_id)
        if key is None:
            schedule_send({"type": "session_error", "message": "That connection request is no longer valid."})
            return
        self._conns[conn_id] = {"device_id": str(payload.get("deviceId") or ""), "key": key,
                                "session_id": str(payload.get("sessionId") or ""), "voice": None,
                                "schedule_send": schedule_send, "schedule_end": schedule_end}
        schedule_send(phone_crypto.encrypt(key, {"type": "session_ready"}))

    async def _on_decrypted(self, conn_id, state: dict, message: dict) -> None:
        kind = message.get("type")
        if kind == "command":
            command_id = str(message.get("commandId") or "")
            if not command_id:
                return
            # run_command's own dispatch (app.py's _dispatch_phone_command) already rejects an unknown commandType
            # with a FAILED result, exactly as the local PHONE_COMMANDS path does — nothing to duplicate here.
            result = await asyncio.get_event_loop().run_in_executor(
                None, self.phone_server.run_command, state["device_id"], command_id,
                str(message.get("commandType") or ""), message.get("payload") or {})
            state["schedule_send"](phone_crypto.encrypt(state["key"],
                                                        {"type": "result", "commandId": command_id, **result}))
        elif kind == "voice_start":
            state["voice"] = {"chunks": [], "bytes": 0, "started": time.time()}
        elif kind == "voice_chunk" and state.get("voice") is not None:
            try:
                chunk = base64.b64decode(message.get("data") or "")
            except (ValueError, TypeError):
                return
            voice = state["voice"]
            if time.time() - voice["started"] > VOICE_MAX_SECONDS or voice["bytes"] + len(chunk) > VOICE_MAX_BYTES:
                state["voice"] = None   # drop an oversized/stuck recording rather than let it grow unbounded
                return
            voice["chunks"].append(chunk)
            voice["bytes"] += len(chunk)
        elif kind == "voice_end" and state.get("voice") is not None:
            voice = state.pop("voice")
            audio = b"".join(voice["chunks"])
            if audio:
                threading.Thread(target=self._transcribe_and_deliver, daemon=True, name="phone-voice",
                                 args=(audio, state["session_id"])).start()
        elif kind == "disconnect":
            self.end_session(state["session_id"])

    def _transcribe_and_deliver(self, audio_bytes: bytes, session_id: str) -> None:
        """Runs in its own thread (decode + transcription are both real CPU work) — never on an asyncio loop."""
        try:
            pcm = decode_audio_to_pcm16(audio_bytes)
            text = self.transcribe_pcm16(pcm, 16000) if pcm else ""
        except Exception as e:
            print(f"Phone voice couldn't be understood: {e}", flush=True)
            text = ""
        if text:
            self.deliver_voice_text(text, session_id)
        else:
            self.deliver_reply(session_id, "Sorry, I didn't catch that.")
