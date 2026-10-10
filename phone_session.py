"""The phone-session protocol, shared by the two ways a phone can reach Jarvis once "connect my phone" has been
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
# How far a relay auto_attach proof's timestamp may be from this computer's clock (see verify_attach_proof): wide
# enough for a phone whose clock is a little off, narrow enough that a captured proof is soon worthless.
ATTACH_PROOF_WINDOW = 10 * 60


def verify_attach_proof(key: bytes, proof, device_id: str) -> bool:
    """A relay-routed auto_attach proves it's the paired phone without its token ever passing through the relay:
    `proof` must be an envelope only that device's own key could have produced, naming that device and a recent
    time. A relay replaying one it saw can at most re-open a session it still can't read or write (every frame
    after attaching is encrypted with that same key) — never act as the phone."""
    message = phone_crypto.decrypt(key, proof) if isinstance(proof, dict) else None
    if not isinstance(message, dict) or message.get("type") != "attach" or message.get("deviceId") != device_id:
        return False
    try:
        sent_at = float(message.get("ts")) / 1000   # the phone's Date.now(), in milliseconds
    except (TypeError, ValueError):
        return False
    return abs(time.time() - sent_at) <= ATTACH_PROOF_WINDOW


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


_computer_name_cache = []


def _computer_name() -> str:
    """A friendly name for this computer, shown in the phone app's header ("Connected · Ariel's MacBook Air").
    On a Mac the network hostname is an ASCII-mangled version of the real name (a Hebrew name comes out as
    "h-mhsb-..."), so the name the user actually gave it is asked for instead. Looked up once."""
    if _computer_name_cache:
        return _computer_name_cache[0]
    import platform
    import subprocess
    import sys
    name = ""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True, timeout=2)
            name = (result.stdout or "").strip() if result.returncode == 0 else ""
        elif sys.platform == "win32":
            import os
            name = os.environ.get("COMPUTERNAME", "")
    except Exception:
        name = ""
    name = (name if isinstance(name, str) else "") or platform.node().split(".")[0]
    # macOS wraps the user's own name in bidi isolate marks (U+2066-2069); the phone isolates it itself
    name = "".join(ch for ch in name if ch not in "\u2066\u2067\u2068\u2069\u200e\u200f")
    _computer_name_cache.append(name.strip()[:40] or "your computer")
    return _computer_name_cache[0]


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
                 on_push_subscribe=None, on_push_unsubscribe=None, get_history=None, on_presence=None,
                 get_vapid_key=None, get_ai_config=None, on_phone_turn=None, on_secure_pair=None):
        self.phone_server = phone_server
        self.transcribe_pcm16 = transcribe_pcm16
        self.deliver_voice_text = deliver_voice_text
        self.on_push_subscribe = on_push_subscribe       # (subscription: dict) -> None, e.g. push_store.add
        self.on_push_unsubscribe = on_push_unsubscribe   # (endpoint: str) -> None, e.g. push_store.remove
        self.get_history = get_history       # () -> list of chat messages, sent to a phone right after it attaches
        self.on_presence = on_presence       # (names: list[str]) -> None, whenever the set of attached phones changes
        self.get_vapid_key = get_vapid_key   # () -> str, so an installed app can turn notifications on in-session
        self.get_ai_config = get_ai_config   # () -> dict, what the phone app's own Jarvis agent needs (mobile/)
        # (secret, device_name, replaces) -> the paired answer (dict) or None: pairing through the relay, see _pair_secure
        self.on_secure_pair = on_secure_pair
        self.on_phone_turn = on_phone_turn   # (user, reply, device_name) -> None, a turn handled on the phone itself
        self._conns = {}   # conn_id -> {"device_id","key","session_id","voice","schedule_send","schedule_end"}
        self._presence = None

    def connected_device_names(self) -> list:
        names = {self.phone_server.registry.name_of(s["device_id"]) for s in list(self._conns.values())}
        return sorted(n for n in names if n)

    def _presence_changed(self) -> None:
        """Tells the computer side (app.py) which phones are attached right now, only when that actually changes
        — a reconnect that replaces one connection with another for the same phone is not news."""
        names = self.connected_device_names()
        if names != self._presence:
            self._presence = names
            if self.on_presence:
                try:
                    self.on_presence(names)
                except Exception as e:
                    print(f"Phone presence update failed: {e!r}", flush=True)

    def forget(self, conn_id) -> None:
        if self._conns.pop(conn_id, None) is not None:
            self._presence_changed()

    def is_attached(self, conn_id) -> bool:
        """Whether `conn_id` has already attached a session — a transport uses this to tell a first "session_attach"
        / "auto_attach" frame (still dispatched on its own) from everything that follows it on the same connection
        (text, voice, commands, disconnect — plaintext for a local session, an envelope for a relayed one), which
        must always reach on_frame regardless of what kind of frame it looks like."""
        return conn_id in self._conns

    def forget_matching(self, predicate) -> None:
        """Drops every connection whose conn_id satisfies `predicate` — for a transport to clean up its own
        entries (e.g. relay_client.py, on reconnecting to the relay) without touching another transport's."""
        for conn_id in [c for c in self._conns if predicate(c)]:
            self._conns.pop(conn_id, None)
        self._presence_changed()

    def deliver_reply(self, session_id: str, text: str, request_id: str = "") -> None:
        """A reply to something a phone said, once the main loop has worked one out (app.py calls this from the
        three places a turn's reply is finalized — see PhoneVoiceInput). `request_id`: the phone app's own id for
        the request, when it sent one, so its run_on_computer tool gets exactly this answer back."""
        self.send(session_id, {"type": "reply", "text": text, **({"requestId": request_id} if request_id else {})})

    def send(self, session_id: str, message: dict) -> None:
        """Delivers an arbitrary message (status updates, chat mirrors, ...) to the phone attached to this
        session, if any — the general case deliver_reply is a shorthand for."""
        conn_id = self.phone_server.active_session_conn(session_id)
        state = self._conns.get(conn_id) if conn_id else None
        if state:
            self._send(state, message)

    def _send(self, state: dict, message: dict) -> None:
        """Local (same-Wi-Fi) connections are sent in the clear — see phone_crypto.py's own docstring on why, and
        _attach/_auto_attach's `local` flag for where this is decided. Only relay-routed traffic is encrypted."""
        state["schedule_send"](message if state["local"] else phone_crypto.encrypt(state["key"], message))

    def end_session(self, session_id: str) -> None:
        conn_id = self.phone_server.active_session_conn(session_id)
        self.phone_server.end_session(session_id)
        if conn_id:
            state = self._conns.pop(conn_id, None)
            if state:
                # Said first, so the app knows this was meant (e.g. "disconnect my phone" at the computer) and
                # waits for the user instead of reconnecting by itself the moment the connection closes.
                try:
                    self._send(state, {"type": "session_ended"})
                except Exception:
                    pass
            if state and state.get("schedule_end"):
                state["schedule_end"]()
            self._presence_changed()

    async def on_frame(self, conn_id, payload, schedule_send, schedule_end=None, local: bool = False) -> None:
        if not isinstance(payload, dict):
            return
        state = self._conns.get(conn_id)
        if state is None:
            if payload.get("type") == "session_attach":
                await self._attach(conn_id, payload, schedule_send, schedule_end, local)
            elif payload.get("type") == "auto_attach":
                await self._auto_attach(conn_id, payload, schedule_send, schedule_end, local)
            elif payload.get("type") == "pair_secure":
                self._pair_secure(payload, schedule_send)
            elif DEVICE_MESSAGE_ENVELOPE <= payload.keys():
                await self._handle_device_message(payload, schedule_send)
            # else: nothing else is meaningful before a session is attached
            return
        message = payload if state["local"] else phone_crypto.decrypt(state["key"], payload)
        if message is None:
            return
        await self._on_decrypted(conn_id, state, message)

    def _pair_secure(self, payload: dict, schedule_send) -> None:
        """Pairing through the relay, for the phone's always-on app: the request is an envelope sealed with the open
        pairing's one-time key (from the QR code on this computer's screen), and so is the answer, which carries the
        new device's credentials. The relay passes both along and can read neither. A request that doesn't open
        with that key gets a plain "wrong or expired" and counts as a failed attempt."""
        secret = self.phone_server.pairing_secret()
        message = phone_crypto.decrypt(secret, payload.get("envelope")) if secret else None
        fresh = False
        if isinstance(message, dict) and message.get("type") == "pair":
            try:
                fresh = abs(time.time() - float(message.get("ts")) / 1000) <= ATTACH_PROOF_WINDOW
            except (TypeError, ValueError):
                fresh = False
        if not fresh or not self.on_secure_pair:
            if secret:
                self.phone_server.note_bad_pairing_attempt()
            schedule_send({"type": "pair_error",
                           "message": "That code has expired. On your computer, say “Connect my phone” again."})
            return
        replaces = (str(message.get("previousDeviceId") or ""), str(message.get("previousToken") or ""))
        answer = self.on_secure_pair(secret, str(message.get("deviceName") or ""), replaces)
        if not answer:
            schedule_send({"type": "pair_error",
                           "message": "That code has expired. On your computer, say “Connect my phone” again."})
            return
        schedule_send({"type": "paired_secure", "envelope": phone_crypto.encrypt(secret, {"type": "paired", **answer})})

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

    async def _attach(self, conn_id, payload: dict, schedule_send, schedule_end, local: bool = False) -> None:
        device_id = str(payload.get("deviceId") or "")
        session_id = str(payload.get("sessionId") or "")
        key = self.phone_server.attach_session(session_id, device_id, str(payload.get("token") or ""), conn_id)
        if key is None:
            schedule_send({"type": "session_error", "message": "That connection request is no longer valid."})
            return
        self._finish_attach(conn_id, device_id, session_id, key, schedule_send, schedule_end, local)

    async def _auto_attach(self, conn_id, payload: dict, schedule_send, schedule_end, local: bool = False) -> None:
        """An already-paired phone reconnecting on its own (opening the installed app, the saved bookmark, or
        right after pairing) — no "connect my phone" push/tap needed, since the device's own credentials already
        prove it (see PhoneControlServer.begin_and_approve_session). Same result as _attach from here on, just
        starting from a device's credentials instead of a session a push notification already got approved.

        Proof is either the device token (`token`, the local same-Wi-Fi path, same as pairing itself) or, through
        the relay, an envelope sealed with the device's key (`proof`, see verify_attach_proof) — so the long-lived
        token never has to pass through the relay."""
        device_id = str(payload.get("deviceId") or "")
        token = str(payload.get("token") or "")
        proven = False
        if not token and payload.get("proof") is not None:
            key = self.phone_server.registry.key_for(device_id)
            proven = key is not None and verify_attach_proof(key, payload.get("proof"), device_id)
            if not proven:
                schedule_send({"type": "session_error", "code": "unpaired",
                               "message": "This phone isn't paired anymore. Pair again."})
                return
        session = self.phone_server.begin_and_approve_session(device_id, token, proven=proven)
        if session is None:
            schedule_send({"type": "session_error", "code": "unpaired",
                           "message": "This phone isn't paired anymore. Pair again."})
            return
        key = self.phone_server.attach_session(session.id, device_id, token, conn_id, proven=proven)
        if key is None:
            schedule_send({"type": "session_error", "message": "That didn't work. Try again."})
            return
        # Plaintext only for the web page on this computer's plain-http address, which genuinely can't encrypt (see
        # phone_crypto.py). The native app (mobile/) always can, and asks to ("encrypt"), on the LAN too.
        encrypted = proven or bool(payload.get("encrypt"))
        self._finish_attach(conn_id, device_id, session.id, key, schedule_send, schedule_end, local and not encrypted)

    def _finish_attach(self, conn_id, device_id: str, session_id: str, key, schedule_send, schedule_end,
                       local: bool = False) -> None:
        # Only one session is ever current (PhoneControlServer keeps one): a connection still attached to an
        # older one would otherwise keep looking "connected" while its messages go nowhere. It's told so (and the
        # app then waits for a tap instead of reconnecting by itself — two open phones would otherwise keep taking
        # the session back from each other forever), not closed.
        for stale in [c for c, st in self._conns.items() if st["session_id"] != session_id]:
            stale_state = self._conns.pop(stale, None)
            if stale_state:
                try:
                    self._send(stale_state, {"type": "session_replaced"})
                except Exception:
                    pass
        state = {"device_id": device_id, "key": key, "session_id": session_id, "voice": None,
                 "schedule_send": schedule_send, "schedule_end": schedule_end, "local": local}
        self._conns[conn_id] = state
        self._send(state, {"type": "session_ready"})
        # Everything the phone app needs to look like the same conversation as the computer's window, in one
        # message right behind session_ready (kept separate so session_ready itself stays the bare signal it was).
        info = {"type": "session_info", "deviceName": self.phone_server.registry.name_of(device_id),
                "computerName": _computer_name()}
        try:
            info["history"] = list(self.get_history()) if self.get_history else []
        except Exception:
            info["history"] = []
        try:
            info["vapidKey"] = self.get_vapid_key() if self.get_vapid_key else ""
        except Exception:
            info["vapidKey"] = ""
        self._send(state, info)
        self._presence_changed()

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
            self._send(state, {"type": "result", "commandId": command_id, **result})
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
        elif kind == "voice_cancel":
            state["voice"] = None   # slid away to cancel: whatever was recorded is dropped, never transcribed
        elif kind == "voice_end" and state.get("voice") is not None:
            voice = state.pop("voice")
            audio = b"".join(voice["chunks"])
            if audio:
                threading.Thread(target=self._transcribe_and_deliver, daemon=True, name="phone-voice",
                                 args=(audio, state["session_id"])).start()
        elif kind == "text":
            # A typed message — the phone's chat box, see phone_client.html's sendChatText. Same destination as a
            # transcribed voice recording (deliver_voice_text), just skipping the audio round trip entirely: it's
            # already text.
            text = str(message.get("text") or "").strip()
            if text:
                request_id = str(message.get("requestId") or "")[:64]
                if request_id:   # the phone app's run_on_computer tool: its reply carries this back (see deliver_reply)
                    self.deliver_voice_text(text, state["session_id"], request_id=request_id)
                else:
                    self.deliver_voice_text(text, state["session_id"])
        elif kind == "get_ai_config" and self.get_ai_config:
            # The phone app runs its own Jarvis agent (Phone Mode works with this computer off), with the same AI.
            # Its key only ever goes out over an encrypted session, to a paired device.
            if state["local"]:
                self._send(state, {"type": "ai_config", "error": "encrypted session required"})
            else:
                try:
                    self._send(state, {"type": "ai_config", **self.get_ai_config()})
                except Exception as e:
                    self._send(state, {"type": "ai_config", "error": str(e)})
        elif kind == "phone_turn" and self.on_phone_turn:
            # Something the phone handled itself (Phone Mode): part of the same conversation as everything else.
            user, reply = str(message.get("user") or "").strip()[:4000], str(message.get("reply") or "").strip()[:8000]
            if user or reply:
                self.on_phone_turn(user, reply, self.phone_server.registry.name_of(state["device_id"]))
        elif kind == "ping":
            # The phone app's own heartbeat (phone_client.html): a mobile browser can't see websocket-level pings,
            # and a connection that died silently (Wi-Fi handoff, phone asleep) is otherwise only noticed when the
            # next message fails to arrive. Tiny and app-level, so it works the same over the relay.
            self._send(state, {"type": "pong", "t": message.get("t")})
        elif kind == "push_subscribe" and self.on_push_subscribe:
            # Turning notifications on from inside the installed app (an attached session already proves which
            # phone this is) instead of the separate one-time relay setup page.
            subscription = message.get("subscription")
            if isinstance(subscription, dict) and subscription.get("endpoint"):
                self.on_push_subscribe(subscription)
                self._send(state, {"type": "subscribed"})
        elif kind == "unpair":
            # "Unpair this phone" in the app: the device's record goes for good, so these credentials can never
            # attach again — pairing back needs a fresh QR scan, same as any new phone.
            if state["device_id"]:
                self.phone_server.registry.revoke(state["device_id"])
            self._send(state, {"type": "unpaired"})
            self.end_session(state["session_id"])
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
