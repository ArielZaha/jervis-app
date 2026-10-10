"""Jarvis's relay: a small, secret-free router so a paired phone can reach Jarvis from anywhere, not just the same
Wi-Fi. Deployed separately from the app itself (see README.md in this folder) — this is the one piece of Jarvis
infrastructure that has to run somewhere other than the user's own computer, since home routers aren't reachable
from the open internet by default and something has to sit in the middle for both sides to connect out to.

On purpose, this process knows nothing worth stealing:
  - No device tokens, no pairing codes, no encryption keys ever pass through here in a form this code reads. Every
    payload it forwards between a computer and a phone is an opaque, end-to-end-encrypted blob once a session is
    attached (see phone_crypto.py on the Jarvis side) — this relay just moves bytes by connection id.
  - It keeps no state on disk and nothing survives a restart; a dropped connection just means each side reconnects
    (both relay_client.py and phone_client.html already retry with backoff).
  - The one thing it does interpret is routing: which computerId a phone wants, and which connId a message is for.
    A `computerId` is a long random value (relay_client.py mints one per install) — knowing it lets a stranger open
    a connection that LOOKS like a phone to that computer, but Jarvis's own pairing/session checks (phone_control.py)
    are what actually decide whether anything happens with it, exactly as they already do for a local connection.

Protocol (JSON text frames over one WebSocket per side):
  computer -> relay (once, on connect):  {"type": "hello", "role": "computer", "computerId": "..."}
  phone    -> relay (once, on connect):  {"type": "hello", "role": "phone", "computerId": "..."}
  relay -> either, after a good hello:   {"type": "hello_ok", "connId": "..."}   (connId only for the phone)
  relay -> computer, a phone showed up:  {"type": "phone_connected", "connId": "..."}
  relay -> computer, a phone left:       {"type": "phone_disconnected", "connId": "..."}
  relay -> phone, computer isn't here:   {"type": "offline"}
  phone -> relay, anything else:         forwarded to the computer as {"type": "frame", "connId", "payload": <msg>}
  computer -> relay, to reach one phone: {"type": "frame", "connId": "...", "payload": <msg>}, forwarded as <msg>
  relay -> computer, serving a page:     {"type": "get_page_context", "requestId": "..."}
  computer -> relay, its reply:          {"type": "page_context", "requestId": "...", "vapidKey", "localAddress"}

Plus two plain HTTP endpoints (GET, not POST — the `websockets` library this reuses, same one app.py's local phone
server already uses, can't read a request body, only a query string):
  - /decide?computerId=&sessionId=&secret=&decision=confirm|reject — a service worker answering a push
    notification's action button can only make a simple fetch(), often before any WebSocket of its own is open
    (see phone_sw.js). The secret is short-lived and single-use (phone_control.PhoneSession), so it appearing in a
    URL — and thus potentially in the relay platform's own access logs — is a bounded, accepted exposure, not a
    standing credential.
  - /?computerId=... — serves the same phone_client.html/phone_sw.js the local phone server does (phone_control.py),
    a stable link that works regardless of the computer's local IP — mainly for enabling push notifications on an
    already-paired phone without needing the same Wi-Fi. Fetches two things live from that computer over its
    already-open connection above, rather than baking either into the relay itself: its public VAPID key (there is
    no one key — every install generates its own; see push.py), and its current local address, shown to a phone
    that turns out not to be recognized here yet (phone_client.html's syncToOtherOrigin never got a chance to run
    — e.g. this is the very first time this phone has ever reached this relay) so it has a real link to the one
    place that can fix that, instead of a dead end. This still can't be used to pair a brand-new phone: that step
    deliberately stays local-only (phone_control.py's module docstring explains why), and everything an
    already-paired phone does through this page past loading it is authenticated with that phone's own device key
    (see phone_session.py's PhoneSessionRouter._handle_device_message) — this relay still never sees a token or a
    key, just which device a message is addressed to.
"""
import asyncio
import json
import logging
import os
import secrets
from urllib.parse import parse_qs, urlsplit

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("relay")

PORT = int(os.environ.get("PORT") or 8080)
MAX_MESSAGE = 512 * 1024         # a few seconds of phone audio per chunk; generous, small enough to bound memory
IDLE_PING_INTERVAL = 25          # keeps idle connections alive through typical load-balancer/NAT timeouts (~60s)
PAGE_CONTEXT_TIMEOUT = 5.0       # how long a page load waits for the computer to answer get_page_context
_HERE = os.path.dirname(os.path.abspath(__file__))
PHONE_PAGE_PATH = os.path.join(_HERE, "phone_client.html")
SERVICE_WORKER_PATH = os.path.join(_HERE, "phone_sw.js")
CONFIRM_PAGE_PATH = os.path.join(_HERE, "confirm.html")
MANIFEST_PATH = os.path.join(_HERE, "phone_manifest.webmanifest")
AGENT_PATH = os.path.join(_HERE, "phone_agent.js")
# The phone app's graphs, globe and planets: the computer window's own drawing code and imagery, copied in by the
# Dockerfile. The same fixed list as phone_visuals.py (tests/test_phone_visuals.py checks they agree).
VISUAL_SCRIPTS = ("sphere_gl.js", "graph.js", "earth.js", "planet.js")
VISUAL_IMAGES = (
    "vendor/earth/blue_marble_5400.jpg", "vendor/earth/clouds_2048.jpg", "vendor/earth/night_lights_3600.jpg",
    "vendor/earth/earth_atmos_2048.jpg",
    "vendor/planets/2k_sun.jpg", "vendor/planets/2k_mercury.jpg", "vendor/planets/2k_venus_surface.jpg",
    "vendor/planets/2k_mars.jpg", "vendor/planets/2k_jupiter.jpg", "vendor/planets/2k_saturn.jpg",
    "vendor/planets/2k_saturn_ring_alpha.png", "vendor/planets/2k_uranus.jpg", "vendor/planets/2k_neptune.jpg",
    "vendor/planets/2k_moon.jpg",
)
VISUAL_FILES = {f"/{n}": (n, "text/javascript; charset=utf-8", "no-cache") for n in VISUAL_SCRIPTS}
VISUAL_FILES.update({f"/{n}": (n, "image/png" if n.endswith(".png") else "image/jpeg", "public, max-age=604800")
                     for n in VISUAL_IMAGES})
ICON_DIR = os.path.join(_HERE, "phone_icons")
# Same fixed list as phone_control.ICON_FILES (this file deploys on its own, so it can't import that module).
ICON_FILES = frozenset({"icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png",
                        "favicon-64.png"})

computers = {}            # computerId -> websocket
phone_owner = {}          # connId -> computerId
phone_sockets = {}        # connId -> websocket
computer_conns = {}       # computerId -> set of connId
pending_page_context = {}  # requestId -> asyncio.Future, resolved when the matching page_context reply arrives


def _new_conn_id() -> str:
    return secrets.token_urlsafe(9)


async def _send(ws, obj) -> bool:
    try:
        await ws.send(json.dumps(obj))
        return True
    except websockets.exceptions.ConnectionClosed:
        return False


async def _forget_phone(conn_id: str, *, tell_computer: bool) -> None:
    ws = phone_sockets.pop(conn_id, None)
    computer_id = phone_owner.pop(conn_id, None)
    if computer_id:
        computer_conns.get(computer_id, set()).discard(conn_id)
        if tell_computer:
            computer_ws = computers.get(computer_id)
            if computer_ws is not None:
                await _send(computer_ws, {"type": "phone_disconnected", "connId": conn_id})
    if ws is not None:
        try:
            await ws.close()
        except websockets.exceptions.ConnectionClosed:
            pass


async def _forget_computer(computer_id: str) -> None:
    if computers.get(computer_id) is not None:
        computers.pop(computer_id, None)
    for conn_id in list(computer_conns.pop(computer_id, ())):
        ws = phone_sockets.pop(conn_id, None)
        phone_owner.pop(conn_id, None)
        if ws is not None:
            await _send(ws, {"type": "offline"})
            try:
                await ws.close()
            except websockets.exceptions.ConnectionClosed:
                pass


async def _handle_computer(websocket, computer_id: str) -> None:
    if not computer_id or len(computer_id) > 128:
        await websocket.close(1008, "bad computerId")
        return
    previous = computers.get(computer_id)
    if previous is not None:
        await previous.close(1008, "replaced by a new connection")   # e.g. the app restarted
    computers[computer_id] = websocket
    computer_conns.setdefault(computer_id, set())
    await _send(websocket, {"type": "hello_ok"})
    log.info("computer online: %s", computer_id[:8])
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except (ValueError, TypeError):
                continue
            if await _handle_computer_control_message(computer_id, data):
                continue
            conn_id = str(data.get("connId") or "")
            if phone_owner.get(conn_id) != computer_id:
                continue
            if data.get("type") == "frame":
                phone_ws = phone_sockets.get(conn_id)
                if phone_ws is not None:
                    await _send(phone_ws, data.get("payload"))
            elif data.get("type") == "end_conn":
                # The computer ended this session on purpose (e.g. "disconnect my phone") — closing the phone's
                # socket here is what actually tells it, through the ordinary WebSocket close event it already
                # handles; tell_computer=False because it already knows, it's the one that asked.
                await _forget_phone(conn_id, tell_computer=False)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if computers.get(computer_id) is websocket:
            await _forget_computer(computer_id)
            log.info("computer offline: %s", computer_id[:8])


async def _handle_computer_control_message(computer_id: str, data: dict) -> bool:
    """page_context replies aren't tied to a connId (no phone is attached yet — this answers a page load, see
    _fetch_page_context) so they're handled separately from the connId-routed frame/end_conn messages above.
    Returns True if this message was one of these (so the caller doesn't also try to route it by connId)."""
    if data.get("type") != "page_context":
        return False
    request_id = str(data.get("requestId") or "")
    future = pending_page_context.get(request_id)
    if future is not None and not future.done():
        future.set_result({"vapidKey": str(data.get("vapidKey") or ""),
                           "localAddress": str(data.get("localAddress") or "")})
    return True


async def _handle_phone(websocket, computer_id: str) -> None:
    computer_ws = computers.get(computer_id)
    if not computer_id or computer_ws is None:
        await _send(websocket, {"type": "offline"})
        await websocket.close(1000, "computer offline")
        return
    conn_id = _new_conn_id()
    phone_sockets[conn_id] = websocket
    phone_owner[conn_id] = computer_id
    computer_conns.setdefault(computer_id, set()).add(conn_id)
    await _send(websocket, {"type": "hello_ok", "connId": conn_id})
    await _send(computer_ws, {"type": "phone_connected", "connId": conn_id})
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except (ValueError, TypeError):
                continue
            current = computers.get(computer_id)
            if current is None:
                await _send(websocket, {"type": "offline"})
                break
            await _send(current, {"type": "frame", "connId": conn_id, "payload": data})
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await _forget_phone(conn_id, tell_computer=True)


async def handler(websocket) -> None:
    try:
        first = await asyncio.wait_for(websocket.recv(), timeout=15)
        data = json.loads(first)
    except (asyncio.TimeoutError, ValueError, TypeError, websockets.exceptions.ConnectionClosed):
        await websocket.close(1008, "expected a hello")
        return
    if data.get("type") != "hello" or data.get("role") not in ("computer", "phone"):
        await websocket.close(1008, "expected a hello")
        return
    computer_id = str(data.get("computerId") or "")
    if data["role"] == "computer":
        await _handle_computer(websocket, computer_id)
    else:
        await _handle_phone(websocket, computer_id)


def _http_response(status: int, content: bytes, content_type: str, cache_control: str = "no-store"):
    from websockets.datastructures import Headers
    from websockets.http11 import Response
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(content))
    headers["Cache-Control"] = cache_control
    return Response(status, "OK" if status == 200 else "Error", headers, content)


async def _fetch_page_context(computer_id: str) -> dict:
    """Two things only the connected computer itself knows, asked for live over its already-open connection:
      - its public notification key (no single key to bake in here — every Jarvis install generates its own,
        see push.py); empty if unavailable, in which case the page just won't offer to turn notifications on
        (see phone_client.html's refreshNotifyCard, same as the local phone server's own page already handles).
      - its current local address, so a phone that was never recognized on *this* origin (never completed the
        one-time local<->relay sync — see phone_client.html's syncToOtherOrigin) has a real link back to the one
        place that sync can start from, instead of being stuck with no way forward (see setUpNotificationsViaRelay).
    Both come back empty if the computer is offline or doesn't answer in time; the page still loads either way."""
    computer_ws = computers.get(computer_id)
    empty = {"vapidKey": "", "localAddress": ""}
    if computer_ws is None:
        return empty
    request_id = secrets.token_urlsafe(9)
    future = asyncio.get_event_loop().create_future()
    pending_page_context[request_id] = future
    try:
        if not await _send(computer_ws, {"type": "get_page_context", "requestId": request_id}):
            return empty
        return await asyncio.wait_for(future, PAGE_CONTEXT_TIMEOUT)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return empty
    finally:
        pending_page_context.pop(request_id, None)


def _icon_name_for(path: str):
    """The installed app's icons: /icons/<name> (the manifest) or iOS's own /apple-touch-icon.png lookup."""
    if path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        return "apple-touch-icon.png"
    if path == "/favicon.ico":
        return "favicon-64.png"
    name = path[len("/icons/"):] if path.startswith("/icons/") else ""
    return name if name in ICON_FILES else None


async def process_request(connection, request):
    """A real WebSocket handshake (an `Upgrade` header) always falls through to `handler` untouched. Otherwise,
    one of three plain-HTTP endpoints — see the module docstring for what each is for and why GET, not POST."""
    if request.headers.get("Upgrade"):
        return None
    path = urlsplit(request.path)

    if path.path == "/decide":
        query = parse_qs(path.query)
        computer_id = (query.get("computerId") or [""])[0]
        session_id = (query.get("sessionId") or [""])[0]
        secret = (query.get("secret") or [""])[0]
        decision = (query.get("decision") or [""])[0]
        if not (computer_id and session_id and secret and decision in ("confirm", "reject")):
            return connection.respond(400, "Bad request.")
        computer_ws = computers.get(computer_id)
        if computer_ws is None:
            return connection.respond(503, "That computer isn't reachable right now.")
        delivered = await _send(computer_ws, {"type": "decide", "sessionId": session_id, "secret": secret,
                                              "decision": decision})
        if not delivered:
            return connection.respond(503, "That computer isn't reachable right now.")
        return connection.respond(200, "OK")

    if path.path == "/manifest.webmanifest":
        try:
            with open(MANIFEST_PATH, "rb") as f:
                return _http_response(200, f.read(), "application/manifest+json", "no-cache")
        except OSError:
            return connection.respond(404, "Not found.")

    if path.path == "/agent.js":
        try:
            with open(AGENT_PATH, "rb") as f:
                return _http_response(200, f.read(), "text/javascript; charset=utf-8", "no-cache")
        except OSError:
            return connection.respond(404, "Not found.")

    visual = VISUAL_FILES.get(path.path)   # graphs, the globe, planets: a fixed list (see phone_visuals.py)
    if visual:
        name, content_type, cache = visual
        try:
            with open(os.path.join(_HERE, *name.split("/")), "rb") as f:
                return _http_response(200, f.read(), content_type, cache)
        except OSError:
            return connection.respond(404, "Not found.")

    icon = _icon_name_for(path.path)
    if icon:
        try:
            with open(os.path.join(ICON_DIR, icon), "rb") as f:
                return _http_response(200, f.read(), "image/png", "public, max-age=86400")
        except OSError:
            return connection.respond(404, "Not found.")

    if path.path == "/sw.js":
        try:
            with open(SERVICE_WORKER_PATH, "rb") as f:
                return _http_response(200, f.read(), "text/javascript; charset=utf-8")
        except OSError:
            return connection.respond(500, "Not available.")

    if path.path == "/confirm":
        try:
            with open(CONFIRM_PAGE_PATH, encoding="utf-8") as f:
                return _http_response(200, f.read().encode("utf-8"), "text/html; charset=utf-8")
        except OSError:
            return connection.respond(500, "Not available.")

    if path.path in ("/", "/index.html"):
        # computerId is only needed to fetch live page context for the notification-setup entry point
        # (notification_setup_url() in app.py always includes it). A "connect my phone" notification's own
        # openWindow target is always a bare /?session=... with no computerId at all — session_attach and
        # everything after use the phone's own already-stored computerId/relayUrl (see phone_client.html), not
        # anything from this page's own URL — so it's fine, and must stay fine, to serve this with nothing.
        computer_id = (parse_qs(path.query).get("computerId") or [""])[0]
        try:
            with open(PHONE_PAGE_PATH, encoding="utf-8") as f:
                html = f.read()
        except OSError:
            return connection.respond(500, "Not available.")
        context = await _fetch_page_context(computer_id) if computer_id else {"vapidKey": "", "localAddress": ""}
        html = (html.replace("__VAPID_PUBLIC_KEY__", context["vapidKey"])
                    .replace("__COMPUTER_ID__", computer_id)
                    .replace("__LOCAL_ADDRESS__", context["localAddress"])
                    .replace("__SERVED_BY_RELAY__", "1")
                    # Pairing never goes through the relay (see phone_control.py's module docstring) — this is
                    # always empty here, never the computer's real pairing code.
                    .replace("__ACTIVE_PAIR_CODE__", ""))
        return _http_response(200, html.encode("utf-8"), "text/html; charset=utf-8")

    return connection.respond(404, "Not found.")


async def _keepalive() -> None:
    """A relay on a platform that idles out quiet connections (common on free tiers) would otherwise drop a phone
    or computer that's connected but simply not talking; a periodic ping is cheaper than losing the session."""
    while True:
        await asyncio.sleep(IDLE_PING_INTERVAL)
        for ws in list(computers.values()) + list(phone_sockets.values()):
            try:
                await ws.ping()
            except websockets.exceptions.ConnectionClosed:
                pass


async def main() -> None:
    asyncio.get_event_loop().create_task(_keepalive())
    async with websockets.serve(handler, "0.0.0.0", PORT, process_request=process_request,
                                max_size=MAX_MESSAGE, ping_interval=None):
        log.info("Jarvis relay listening on :%d", PORT)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
