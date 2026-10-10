"""Phone -> Jarvis: a small, allowlisted remote-command (and, once connected, voice) channel.

This is deliberately separate from the trusted local connection the Electron window uses (which stays bound to
127.0.0.1 with its own per-launch secret, see app.py's WS_HOST/WS_TOKEN): a phone is a different trust level, so it
gets its own server, its own port, and its own pairing/authentication, and can only ever call a fixed, small set of
existing Jarvis tools (PHONE_COMMANDS) or send voice — never a raw shell, never arbitrary code.

Two different flows use this module, for two different jobs:

  1. Pairing (PairingSession/try_pair) — first-ever trust between a phone and this computer. The user says
     "connect my phone"; on "yes" a short-lived numeric code is shown, the phone opens this computer's local
     address in its own browser (a small page this same server hands out) and enters the code: that code only
     ever works over the same Wi-Fi. A device token AND an end-to-end encryption key (phone_crypto.py) are issued
     once and stored (the token hashed, the key in the clear — see DeviceRegistry) in devices.json; the phone
     keeps both. One-time per phone.
     The QR code shown with it also carries a one-time 256-bit key (PairingSession.secret, try_pair_secure): the
     phone's always-on app (served by the relay) pairs with that from anywhere, the request and the answer both
     sealed with the key, so the relay in between learns nothing (phone_session.py, _pair_secure). Only someone
     who can see this computer's screen has the key; it is single use and expires with the code.

  2. Sessions (PhoneSession/begin_session/decide_session/attach_session) — every "connect my phone" after that.
     Instead of a code to type, every already-paired phone gets a push notification with Confirmed/Not Confirmed
     buttons (push.py); tapping one opens confirm.html, a small page that answers decide_session using nothing
     but the session id and secret already in its own link — no device credentials, no prior sync needed, just to
     confirm or reject. From there, confirm.html can optionally go on to the full phone_client.html app, which
     attaches a live session with the real device token from step 1 (attach_session) — this is the same
     relay-aware flow whether the phone is on this Wi-Fi or anywhere else, see relay_client.py.

Direct, same-Wi-Fi connections (handle_phone_client in app.py) run this module's LAN server directly. Everything
reached through relay_client.py — needed once the phone isn't on the same network — is end-to-end encrypted with
the attached device's key, since a relay is a middlebox: see phone_crypto.py for why and relay/server.py for what
the relay itself actually is (a dumb, secret-free router, so it never has anything worth compromising).

Nothing here decides whether an action is safe to expose remotely — app.py wires this module to the specific,
already-existing tool functions it chooses to allow, exactly as it already does for voice and chat.
"""
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

import paths
import phone_visuals
import phone_crypto

DEVICES_FILE = paths.data("phone_devices.json")
PAIR_CODE_TTL = 5 * 60          # seconds a pairing code stays valid
MAX_PAIR_ATTEMPTS = 8           # wrong codes allowed before pairing must be restarted (guards a 6-digit code)
IDEMPOTENCY_TTL = 60 * 60       # how long a command's result is remembered, to answer a resend without repeating it
COMMAND_TIMEOUT = 30            # seconds a single command may take before it's reported as timed out
SESSION_TTL = 2 * 60            # seconds a "connect my phone" session request stays open before it's forgotten
MAX_SESSION_DECIDE_ATTEMPTS = 8  # guards the session secret the same way MAX_PAIR_ATTEMPTS guards the pairing code


def lan_address() -> str:
    """This computer's address on the local network (never 127.0.0.1), best guess."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))   # nothing is actually sent; this only asks the OS which interface would be used
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def is_private_address(ip: str) -> bool:
    """Whether `ip` is on a local/private network — the phone-control server refuses everything else outright,
    since this phase is explicitly LAN-only (a public-looking caller means something is misconfigured, e.g. an
    accidental router port-forward, not a real use case yet)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


class DeviceRegistry:
    """Paired phones, saved as id -> {name, token_hash, key_b64, paired_at, last_seen}. Only a hash of the pairing
    token is ever kept, the same way a password would be, so reading devices.json never hands out a working
    credential for LAN pairing. The per-device encryption key (key_b64) is the one exception: it must be kept in
    the clear here, because Jarvis needs to decrypt with it, not just check it — see phone_crypto.py for what it's
    for (end-to-end encryption of anything routed through the public relay). It never leaves this file and the
    one phone it was issued to; devices.json is gitignored and local to this computer like every other personal
    file (see paths.py)."""

    def __init__(self, path: str = DEVICES_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._devices = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                self._devices = json.load(f).get("devices", {})
        except (OSError, ValueError):
            self._devices = {}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"devices": self._devices}, f)
        except OSError:
            pass

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def add(self, name: str) -> tuple:
        """Registers a newly paired device. Returns (device_id, token, key) — the token and key are handed to the
        phone once, right here: the token is never stored or logged in plain text again (only its hash is kept),
        and the key is this device's end-to-end encryption key for relay-routed traffic (phone_crypto.py)."""
        device_id = secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        key = phone_crypto.new_key()
        with self._lock:
            self._devices[device_id] = {"name": (name or "Phone").strip()[:60] or "Phone",
                                        "token_hash": self._hash(token), "key_b64": phone_crypto.key_to_b64(key),
                                        "paired_at": time.time(), "last_seen": time.time()}
            self._save()
        return device_id, token, key

    def key_for(self, device_id: str):
        """This device's end-to-end encryption key (bytes), or None if it isn't paired / predates this field."""
        with self._lock:
            device = self._devices.get(device_id)
        key_b64 = device.get("key_b64") if device else None
        return phone_crypto.key_from_b64(key_b64) if key_b64 else None

    def authenticate(self, device_id: str, token: str):
        """The device's record if `token` is genuinely its own, else None."""
        with self._lock:
            device = self._devices.get(device_id)
            valid = bool(device) and hmac.compare_digest(device["token_hash"], self._hash(token))
            if valid:
                device["last_seen"] = time.time()
                self._save()
        return device if valid else None

    def touch(self, device_id: str) -> bool:
        """Records a sighting of a device whose identity the caller already proved some other way (see
        PhoneControlServer.begin_and_approve_session's `proven`). False if it isn't paired (any more)."""
        with self._lock:
            device = self._devices.get(device_id or "")
            if device:
                device["last_seen"] = time.time()
                self._save()
        return bool(device)

    def name_of(self, device_id: str) -> str:
        with self._lock:
            device = self._devices.get(device_id or "")
        return device["name"] if device else ""

    def list(self) -> list:
        with self._lock:
            return [{"id": k, "name": v["name"], "pairedAt": v["paired_at"], "lastSeen": v["last_seen"]}
                    for k, v in self._devices.items()]

    def revoke(self, device_id: str = None) -> int:
        """Removes one paired device (by id), or every paired device when none is given. Returns how many."""
        with self._lock:
            if device_id:
                removed = 1 if self._devices.pop(device_id, None) else 0
            else:
                removed = len(self._devices)
                self._devices.clear()
            self._save()
        return removed


class PairingSession:
    """One open invitation to pair a phone: a short numeric code, valid briefly, usable a limited number of times
    before it must be reissued. Only one is ever open at a time — starting a new one replaces the last."""

    def __init__(self, code: str):
        self.code = code
        # For pairing through the relay (the phone's always-on app): a one-time AES-256 key shown only inside the
        # QR code on this computer's screen. Whoever can seal a request with it has seen that screen; the relay in
        # the middle never has it (it travels in the link's #fragment, which browsers don't send to any server).
        self.secret = secrets.token_bytes(32)
        self.expires_at = time.time() + PAIR_CODE_TTL
        self.attempts = 0

    def expired(self) -> bool:
        return time.time() > self.expires_at or self.attempts >= MAX_PAIR_ATTEMPTS

    def check(self, code: str) -> bool:
        self.attempts += 1
        return not self.expired() and hmac.compare_digest(code, self.code)


class PhoneSession:
    """One "connect my phone" request, from the notification Jarvis sends every already-paired phone through to
    a live, encrypted, relay-routed connection. Two separate secrets do two separate jobs, on purpose:

      - `secret` only proves "whoever is answering received the push notification" (arrival of a Web Push payload
        is itself authenticated/encrypted by the browser's push service and VAPID — see push.py). That's enough
        to know a real notification was tapped, but not which paired phone it was, so it alone only ever moves the
        session from "pending" to "approved"/"rejected" (decide()).
      - Attaching an actual live connection (attach()) needs a real, already-paired device's token — the same
        credential DeviceRegistry.authenticate already checks for local commands — which is what a device's
        end-to-end key then gets looked up from. A leaked push secret alone can approve a session that never gets
        a real device attached to it; it can't fake being a paired phone.

    Only one is ever open at a time, like PairingSession — a second "connect my phone" replaces the first."""

    def __init__(self, session_id: str, secret: str):
        self.id = session_id
        self.secret = secret
        self.state = "pending"           # pending -> approved|rejected ; approved -> active (once attached)
        self.device_id = None            # set once a real paired device attaches
        self.conn_id = None              # which relay connection this session is currently live on
        self.created_at = time.time()
        self.expires_at = time.time() + SESSION_TTL
        self.attempts = 0
        self.decided_event = threading.Event()   # set on decide_session(); start_phone_session() waits on it

    def expired(self) -> bool:
        if self.state == "active":       # no TTL once genuinely connected — ends on disconnect, not on a clock
            return False
        return time.time() > self.expires_at or self.attempts >= MAX_SESSION_DECIDE_ATTEMPTS

    def check_secret(self, secret: str) -> bool:
        self.attempts += 1
        return not self.expired() and hmac.compare_digest(secret or "", self.secret)


class PhoneControlServer:
    """Owns pairing state and command dispatch. app.py builds one of these with `execute`, the callback that
    actually runs an allowed command through Jarvis's existing tools, and drives it from a websockets server (see
    run_phone_server in app.py) plus a small confirm-then-pair flow triggered by a spoken/typed request."""

    def __init__(self, execute, registry: DeviceRegistry = None):
        self.execute = execute             # (command_type, payload) -> str  (the human-readable result)
        self.registry = registry or DeviceRegistry()
        self._pairing = None
        self._session = None               # the one open "connect my phone" request, if any (see PhoneSession)
        self._lock = threading.Lock()
        self._results = {}                 # (device_id, command_id) -> (result, until) — for a resent command

    # ---------- pairing (first-ever trust between this phone and this computer; always local, see app.py) ----------
    def begin_pairing(self) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock:
            self._pairing = PairingSession(code)
        return code

    def pairing_open(self) -> bool:
        with self._lock:
            return self._pairing is not None and not self._pairing.expired()

    def current_pairing_code(self):
        """The code for the pairing currently open, if any — lets the local page offer the Confirmed/Not Confirmed
        tap to a phone that opened this computer's bare address directly (bookmarked, typed, or just reopened)
        without the code actually in its URL, as long as a "connect my phone" request is genuinely in progress
        right now. Same trust boundary as the QR link itself: same Wi-Fi only (server.py never calls this), and
        still a real tap to confirm — this only saves re-finding the link, not the confirmation step."""
        with self._lock:
            return self._pairing.code if self._pairing is not None and not self._pairing.expired() else None

    def pairing_secret(self):
        """The open pairing's one-time key (bytes), or None when no pairing is open."""
        with self._lock:
            return self._pairing.secret if self._pairing is not None and not self._pairing.expired() else None

    def note_bad_pairing_attempt(self) -> None:
        """A request that wasn't sealed with the open pairing's key: counted like a wrong code."""
        with self._lock:
            if self._pairing is not None:
                self._pairing.attempts += 1

    def try_pair_secure(self, secret: bytes, device_name: str, replaces: tuple = None):
        """(device_id, token, key) for a request proven to be sealed with the open pairing's own key (the caller
        decrypted it with `secret`), else None. Single use, exactly like try_pair."""
        with self._lock:
            session = self._pairing
            if session is None or session.expired() or not hmac.compare_digest(secret, session.secret):
                return None
            self._pairing = None
        if replaces and replaces[0] and self.registry.authenticate(*replaces) is not None:
            self.registry.revoke(replaces[0])
        return self.registry.add(device_name)

    def try_pair(self, code: str, device_name: str, replaces: tuple = None):
        """(device_id, token, key) on a correct, still-open code, else None.

        `replaces`: (device_id, token) this same phone was paired with before, if it still has them — a phone
        scanning "connect my phone" again then swaps its old record for the new one instead of leaving a stale
        duplicate behind. Only ever honored with that record's own valid token, so one phone can't unpair another."""
        with self._lock:
            session = self._pairing
        if session is None or not session.check(code):
            return None
        with self._lock:
            self._pairing = None   # one phone per code: pairing another needs a fresh confirmation + code
        if replaces and replaces[0] and self.registry.authenticate(*replaces) is not None:
            self.registry.revoke(replaces[0])
        return self.registry.add(device_name)

    # ---------- sessions ("connect my phone", every time after the first — see PhoneSession) ----------
    def begin_session(self) -> "PhoneSession":
        session = PhoneSession(session_id=secrets.token_urlsafe(12), secret=secrets.token_urlsafe(24))
        with self._lock:
            self._session = session
        return session

    def begin_and_approve_session(self, device_id: str, token: str = None, proven: bool = False):
        """An already-paired phone reconnecting on its own — the saved bookmark, not a "connect my phone" push —
        skips the approval dance entirely: the device token itself, proven once here, is already a stronger proof
        than a push notification's tap ever was. Returns the pre-approved session, or None if the credentials
        don't belong to a real paired device.

        proven=True: the caller already verified the device another way — over the relay, a fresh envelope only
        that device's own key could have produced (see phone_session.verify_attach_proof), so its token never has
        to travel through the relay at all."""
        if proven:
            if not self.registry.touch(device_id):
                return None
        elif self.registry.authenticate(device_id, token or "") is None:
            return None
        session = self.begin_session()
        with self._lock:
            if self._session is session:   # not replaced by a different request while authenticate() ran
                session.state = "approved"
                session.decided_event.set()
        return session

    def decide_session(self, session_id: str, secret: str, approve: bool) -> bool:
        """A phone tapped Confirmed/Not Confirmed on the notification. True if this session_id/secret pair was the
        genuinely open one (whether approved or rejected) — false for anything stale, wrong, or already decided."""
        with self._lock:
            session = self._session
            if session is None or session.id != session_id or session.state != "pending":
                return False
            if not session.check_secret(secret):
                return False
            session.state = "approved" if approve else "rejected"
            session.decided_event.set()
        return True

    def attach_session(self, session_id: str, device_id: str, token: str, conn_id: str, proven: bool = False):
        """A phone whose owner just approved the session opened a live connection and proved it's one of the
        already-paired devices. Returns the device's end-to-end key on success, else None — a wrong/expired
        session, a session nobody approved yet, or credentials that don't belong to a real paired device.

        Deliberately doesn't ask for the session secret again here (only decide_session does): that secret's one
        job is proving a genuine push notification was tapped, and it would otherwise have to travel in the URL
        the service worker opens the phone's page with (window.open can't carry a request body) — leaving it out
        of the URL keeps it out of browser history. The device token, which never appears in a URL, is already a
        real credential on its own (the same one LAN pairing already relies on); a short-lived, high-entropy
        session_id plus that token is enough.

        Also allows re-attaching a session that's already "active" (a network blip, not a real disconnect), but
        only to the same device that originally attached it — a brief reconnect shouldn't need a fresh notification
        and tap, but it must still be that same phone, not a different paired one riding the same session_id."""
        with self._lock:
            session = self._session
            if session is None or session.id != session_id:
                return None
            if session.state not in ("approved", "active"):
                return None
            if session.state == "active" and session.device_id != device_id:
                return None
        if not (self.registry.touch(device_id) if proven else self.registry.authenticate(device_id, token)):
            return None
        key = self.registry.key_for(device_id)
        if key is None:
            return None
        with self._lock:
            if self._session is not session or session.state not in ("approved", "active"):
                return None   # decided again, or replaced, while authenticate() was running
            session.state = "active"
            session.device_id = device_id
            session.conn_id = conn_id
        return key

    def end_session(self, session_id: str) -> None:
        with self._lock:
            if self._session is not None and self._session.id == session_id:
                self._session = None

    def current_session_id(self):
        """The open or active session's id, if there is one — for "disconnect my phone" to end whichever one is
        current without the caller needing to have kept track of it themselves."""
        with self._lock:
            return self._session.id if self._session is not None else None

    def active_session_conn(self, session_id: str):
        """The relay connId this active session is currently live on, or None."""
        with self._lock:
            session = self._session
            if session is not None and session.id == session_id and session.state == "active":
                return session.conn_id
        return None

    # ---------- commands ----------
    def _remembered(self, device_id: str, command_id: str):
        entry = self._results.get((device_id, command_id))
        if entry and entry[1] > time.time():
            return entry[0]
        return None

    def run_command(self, device_id: str, command_id: str, command_type: str, payload: dict) -> dict:
        """Executes an allowed command once per (device, commandId), remembering the outcome so a retransmitted
        message gets the same answer back instead of doing the thing twice. Held under the one lock for its whole
        duration — including two phone commands arriving at the very same instant, not just a resend — so nothing
        genuinely two-executes; the cost is that commands run one at a time, which is a fine trade for how rarely
        more than one phone is actually issuing commands at once."""
        with self._lock:
            remembered = self._remembered(device_id, command_id)
            if remembered is not None:
                return remembered
            try:
                message = self.execute(command_type, payload or {})
                result = {"status": "SUCCEEDED", "message": message}
            except Exception as e:
                result = {"status": "FAILED", "message": str(e)}
            self._results[(device_id, command_id)] = (result, time.time() + IDEMPOTENCY_TTL)
            self._prune()
            return result

    def _prune(self) -> None:
        now = time.time()
        stale = [k for k, (_, until) in self._results.items() if until <= now]
        for k in stale:
            self._results.pop(k, None)


_CLIENT_PAGE = paths.resource("phone_client.html")
_SERVICE_WORKER = paths.resource("phone_sw.js")
_CONFIRM_PAGE = paths.resource("confirm.html")
_MANIFEST = paths.resource("phone_manifest.webmanifest")
_VISUALS = phone_visuals.files()
_AGENT = paths.resource("phone_agent.js")   # the phone app's own Jarvis (built from mobile/src: npm run build:web)
_ICON_DIR = paths.resource("phone_icons")
# The only icon files ever served — a fixed list, never a path taken from the request (no file browsing).
ICON_FILES = frozenset({"icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png",
                        "favicon-64.png"})
ICON_MAX_AGE = 24 * 60 * 60   # icons may be cached a day; the page itself never is (see _response)


def _response(content: bytes, content_type: str, cache_control: str = "no-store"):
    from websockets.datastructures import Headers
    from websockets.http11 import Response
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(content))
    headers["Cache-Control"] = cache_control
    return Response(200, "OK", headers, content)


def icon_name_for(path: str):
    """The bundled icon a request path refers to, or None. Both /icons/<name> (what the manifest lists) and the
    bare /apple-touch-icon.png iOS asks for on its own when adding to the Home Screen."""
    if path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        return "apple-touch-icon.png"
    if path == "/favicon.ico":
        return "favicon-64.png"
    if path.startswith("/icons/") and path[len("/icons/"):] in ICON_FILES:
        return path[len("/icons/"):]
    return None


def serve_static(connection, request, active_pair_code=None):
    """A plain HTTP response for a normal browser GET (the mobile page, its service worker, or the Confirmed/Not
    Confirmed page), or None to let the WebSocket handshake proceed as usual. Nothing else on this computer is
    ever reachable through this: there is no file browsing, only these three fixed files.

    request.path is the *raw* request-line path, query string and all (e.g. "/?code=091468") — never compared
    against directly below; everything here matches on urlsplit(request.path).path instead, which is what the
    QR-code pairing link's /?code=... and the push notification's /confirm?... links both actually are.

    active_pair_code: the caller's PhoneControlServer.current_pairing_code(), if a "connect my phone" pairing is
    open right now — baked into the page so a phone that opened the bare address (a bookmark, typed from memory,
    or just reopened) still gets the Confirmed/Not Confirmed tap, exactly as if the code were in its URL."""
    if request.headers.get("Upgrade"):   # a real WebSocket handshake: let it proceed as usual
        return None
    path = urlsplit(request.path).path
    if path == "/manifest.webmanifest":
        try:
            with open(_MANIFEST, "rb") as f:
                return _response(f.read(), "application/manifest+json", "no-cache")
        except OSError:
            return connection.respond(404, "Not found.")
    if path == "/agent.js":
        try:
            with open(_AGENT, "rb") as f:
                return _response(f.read(), "text/javascript; charset=utf-8", "no-cache")
        except OSError:
            return connection.respond(404, "Not found.")
    visual = _VISUALS.get(path)   # graphs, the globe, planets: the window's own drawing code (phone_visuals.py)
    if visual:
        name, content_type, cache = visual
        try:
            with open(paths.resource(*name.split("/")), "rb") as f:
                return _response(f.read(), content_type, cache)
        except OSError:
            return connection.respond(404, "Not found.")
    icon = icon_name_for(path)
    if icon:
        try:
            with open(f"{_ICON_DIR}/{icon}", "rb") as f:
                return _response(f.read(), "image/png", f"public, max-age={ICON_MAX_AGE}")
        except OSError:
            return connection.respond(404, "Not found.")
    if path == "/sw.js":
        try:
            with open(_SERVICE_WORKER, "rb") as f:
                return _response(f.read(), "text/javascript; charset=utf-8")
        except OSError:
            return connection.respond(500, "The notification helper couldn't be loaded.")
    if path == "/confirm":
        try:
            with open(_CONFIRM_PAGE, encoding="utf-8") as f:
                return _response(f.read().encode("utf-8"), "text/html; charset=utf-8")
        except OSError:
            return connection.respond(500, "The confirmation page couldn't be loaded.")
    if path not in ("/", "/index.html"):
        return connection.respond(404, "Not found.")
    try:
        with open(_CLIENT_PAGE, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return connection.respond(500, "The phone page couldn't be loaded.")
    try:
        import push
        html = html.replace("__VAPID_PUBLIC_KEY__", push.public_key_b64() if push.available() else "")
    except Exception:
        html = html.replace("__VAPID_PUBLIC_KEY__", "")   # notifications just won't be offered; pairing still works
    # __COMPUTER_ID__ and __LOCAL_ADDRESS__ only mean anything when the relay serves this same page
    # (relay/server.py) — reached directly like this, there's exactly one computer to talk to, already at this
    # same address, so neither needs filling in. __SERVED_BY_RELAY__ says so explicitly (see phone_client.html's
    # own comment on why that can't just be inferred from __COMPUTER_ID__ being empty or not).
    html = (html.replace("__COMPUTER_ID__", "").replace("__LOCAL_ADDRESS__", "")
                .replace("__SERVED_BY_RELAY__", "0").replace("__ACTIVE_PAIR_CODE__", active_pair_code or ""))
    return _response(html.encode("utf-8"), "text/html; charset=utf-8")
