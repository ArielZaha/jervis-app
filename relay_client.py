"""Jarvis's side of the relay connection (see relay/server.py): one persistent outbound WebSocket, opened whenever
phone control is on and a relay is configured (Settings, Computer control, "Relay address" — JARVIS_RELAY_URL),
that lets an already-paired phone reach this computer from anywhere, not just the same Wi-Fi.

The actual session protocol (attach, encrypted commands, voice, disconnect) lives in phone_session.py, shared with
app.py's local LAN phone server — this module is only the relay-specific transport around it: the outbound
connection, reconnect-with-backoff, and translating the relay's connId-multiplexed "frame" messages into that
shared router's calls.
"""
import asyncio
import json
import secrets

import websockets

import paths
import phone_session

IDENTITY_FILE = paths.data("relay_identity.json")
RECONNECT_MIN = 1
RECONNECT_MAX = 5    # kept short: while this side is reconnecting, every phone just sees "Jarvis isn't reachable"
PING_INTERVAL = 10   # a link that died silently (laptop sleep, Wi-Fi change) is noticed within ~20s, not ~40s


def load_or_create_computer_id() -> str:
    """A long random id for this Jarvis install, used only for relay routing — see relay/server.py's docstring for
    why that's safe to treat as non-secret (it isn't a credential; pairing/session checks are)."""
    try:
        with open(IDENTITY_FILE, encoding="utf-8") as f:
            existing = json.load(f).get("computerId")
            if existing:
                return existing
    except (OSError, ValueError):
        pass
    computer_id = secrets.token_urlsafe(24)
    try:
        with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
            json.dump({"computerId": computer_id}, f)
    except OSError:
        pass
    return computer_id


class RelayClient:
    """One outbound connection to the relay, reconnected with backoff for as long as it's wanted. `router` is the
    phone_session.PhoneSessionRouter app.py shares with the local phone server, so a "connect my phone" session
    works identically whether the phone ends up attaching here or over the LAN — see phone_session.py."""

    def __init__(self, relay_url: str, router: "phone_session.PhoneSessionRouter", is_enabled, get_vapid_key,
                 get_local_address):
        self.relay_url = relay_url
        self.computer_id = load_or_create_computer_id()
        self.router = router
        self.is_enabled = is_enabled     # () -> bool ; lets Settings turn this off without restarting the backend
        self.get_vapid_key = get_vapid_key           # () -> str ; this install's own notification key (push.py)
        self.get_local_address = get_local_address   # () -> str ; this computer's current http://lan-ip:port
        self._ws = None
        self._loop = None
        self._tasks = set()   # in-flight _on_message tasks, held so they aren't garbage-collected mid-run

    def deliver_reply(self, session_id: str, text: str) -> None:
        self.router.deliver_reply(session_id, text)

    def end_session(self, session_id: str) -> None:
        self.router.end_session(session_id)

    def _relay_conn_id(self, conn_id: str) -> str:
        return f"relay:{conn_id}"

    async def _send(self, text: str) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(text)
            except websockets.exceptions.ConnectionClosed:
                pass

    def _schedule_send(self, conn_id: str):
        def send(obj) -> None:
            loop = self._loop
            if loop is not None:
                payload = json.dumps({"type": "frame", "connId": conn_id, "payload": obj})
                asyncio.run_coroutine_threadsafe(self._send(payload), loop)
        return send

    def _schedule_end(self, conn_id: str):
        def end() -> None:
            loop = self._loop
            if loop is not None:
                payload = json.dumps({"type": "end_conn", "connId": conn_id})
                asyncio.run_coroutine_threadsafe(self._send(payload), loop)
        return end

    # ---------- the connection loop ----------
    async def run_forever(self) -> None:
        self._loop = asyncio.get_event_loop()
        delay = RECONNECT_MIN
        while True:
            if not self.relay_url or not self.is_enabled():
                await asyncio.sleep(5)
                continue
            self.router.forget_matching(lambda c: c.startswith("relay:"))   # a fresh relay connection means
            try:                                                            # every old relay connId is dead
                async with websockets.connect(self.relay_url, max_size=phone_session.VOICE_MAX_BYTES + 4096,
                                              ping_interval=PING_INTERVAL, ping_timeout=PING_INTERVAL) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({"type": "hello", "role": "computer", "computerId": self.computer_id}))
                    delay = RECONNECT_MIN
                    async for message in ws:
                        # Its own task, not awaited inline: a phone command runs in an executor and can take
                        # seconds, and every other phone's attach, /decide and page load would queue behind it.
                        # Tasks still start in arrival order, so one phone's attach/voice frames stay in sequence.
                        task = asyncio.ensure_future(self._on_message(message))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
            except (websockets.exceptions.WebSocketException, OSError):
                pass
            self._ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    async def _on_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        kind = data.get("type")
        if kind == "decide":
            self.router.phone_server.decide_session(str(data.get("sessionId") or ""), str(data.get("secret") or ""),
                                                     data.get("decision") == "confirm")
        elif kind == "get_page_context":
            # The relay is serving the phone page (relay/server.py) and needs two things only this computer knows:
            # its own notification key (no single key to bake into the relay — every install generates its own,
            # see push.py) and its current local address, so a phone that isn't recognized on the relay's origin
            # yet (never completed the one-time local<->relay sync — see phone_client.html's syncToOtherOrigin)
            # has a real link back to the one place that sync can actually start from, instead of being stuck.
            await self._send(json.dumps({"type": "page_context", "requestId": str(data.get("requestId") or ""),
                                         "vapidKey": self.get_vapid_key(),
                                         "localAddress": self.get_local_address()}))
        elif kind == "phone_disconnected":
            self.router.forget(self._relay_conn_id(str(data.get("connId") or "")))
        elif kind == "frame":
            raw_conn_id = str(data.get("connId") or "")
            if not raw_conn_id:
                return
            conn_id = self._relay_conn_id(raw_conn_id)
            await self.router.on_frame(conn_id, data.get("payload"), self._schedule_send(raw_conn_id),
                                       self._schedule_end(raw_conn_id))


def run_relay_client(client: "RelayClient") -> None:
    """Started on its own daemon thread alongside run_phone_server, same shape (see app.py)."""
    asyncio.run(client.run_forever())
