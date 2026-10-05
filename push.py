"""Real phone notifications (Web Push): reaches a phone even when Jervis's page isn't open, through the browser's
own push service (Apple's for Safari, Google's for Chrome/Android, Mozilla's for Firefox — whichever the phone's
browser already uses for every other site's notifications). No server of Jervis's own is involved in delivery.

A VAPID key pair (generated once, kept in vapid_key.pem) signs every push so the browser's push service can tell it
really came from this Jervis. Each phone that turns notifications on sends back a "subscription" (an endpoint URL
plus two keys, not a secret that grants any access to Jervis — it only lets something be pushed *to* that phone),
kept in push_subscriptions.json, gitignored like every other personal file here.

iOS note, unavoidable: Safari only delivers web push to a page added to the Home Screen (iOS 16.4+); a plain
browser tab can't receive one. Nothing on this side can work around that — it's Apple's own platform rule.
"""
import json
import threading
import time

import paths

VAPID_FILE = paths.data("vapid_key.pem")
SUBSCRIPTIONS_FILE = paths.data("push_subscriptions.json")
# Required by the Web Push spec (an "audience" contact for the push service to reach if it needs to complain about
# this key being misused) — not a real inbox, never emailed by anything here.
VAPID_CLAIMS = {"sub": "mailto:jervis-app@example.invalid"}
PUSH_TTL = 120       # seconds a push service keeps trying a sleeping phone — matches phone_control.SESSION_TTL
PUSH_TIMEOUT = 5     # seconds to wait on one push service before giving up on that phone

_vapid_lock = threading.Lock()
_vapid_instance = None


def available() -> bool:
    try:
        import pywebpush  # noqa: F401
        return True
    except ImportError:
        return False


def _vapid():
    global _vapid_instance
    with _vapid_lock:
        if _vapid_instance is None:
            from py_vapid import Vapid02
            import os
            if os.path.exists(VAPID_FILE):
                _vapid_instance = Vapid02.from_file(VAPID_FILE)
            else:
                _vapid_instance = Vapid02()
                _vapid_instance.generate_keys()
                _vapid_instance.save_key(VAPID_FILE)
        return _vapid_instance


def public_key_b64() -> str:
    """The public half, base64url-encoded the way a browser's PushManager.subscribe() wants it
    (applicationServerKey) — safe to hand to any page; it's not a secret, only the private key is."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import b64urlencode
    raw = _vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return b64urlencode(raw)


class SubscriptionStore:
    """Phones that asked to be notified, whether or not they've paired yet — a notification only ever *informs*,
    it never grants Jervis any capability, so this list intentionally isn't gated behind pairing."""

    def __init__(self, path: str = SUBSCRIPTIONS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._subs = {}   # endpoint -> subscription_info dict
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                self._subs = json.load(f).get("subscriptions", {})
        except (OSError, ValueError):
            self._subs = {}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"subscriptions": self._subs}, f)
        except OSError:
            pass

    def add(self, subscription_info: dict) -> None:
        endpoint = subscription_info.get("endpoint")
        if not endpoint:
            return
        with self._lock:
            self._subs[endpoint] = subscription_info
            self._save()

    def remove(self, endpoint: str) -> None:
        with self._lock:
            if self._subs.pop(endpoint, None) is not None:
                self._save()

    def list(self) -> list:
        with self._lock:
            return list(self._subs.values())


def send_to_all(store: SubscriptionStore, title: str, body: str, tag: str = "", actions: list = None,
                data: dict = None) -> int:
    """Pushes a notification to every phone that turned them on. A subscription the push service reports as gone
    (the browser was uninstalled, notifications were revoked, ...) is quietly removed instead of retried forever.
    Returns how many phones actually received it.

    `actions` (e.g. [{"action": "confirm", "title": "Confirmed"}, {"action": "reject", "title": "Not Confirmed"}])
    becomes the notification's action buttons — see phone_sw.js's notificationclick handler, which is the only
    thing that reads them. `data` is handed to the service worker as-is (e.g. the session id and secret a button
    press needs to answer with, see app.py's start_phone_session) — never anything secret-worth-hiding beyond what
    a short-lived, single-use session secret already is (see phone_control.PhoneSession)."""
    if not available():
        return 0
    from pywebpush import webpush, WebPushException
    payload = json.dumps({"title": title, "body": body, "tag": tag or "jervis", "at": time.time(),
                          "actions": actions or [], "data": data or {}})
    vapid = _vapid()
    results = []

    def send_one(subscription_info: dict) -> None:
        try:
            # Urgency high: without it Android's Doze may hold a "normal" push for minutes. A real TTL: pywebpush's
            # default of 0 means "deliver this instant or drop it", which silently loses pushes to a sleeping phone.
            # A timeout: one slow push service must not stall the others (they're sent in parallel below anyway).
            webpush(subscription_info=subscription_info, data=payload, vapid_private_key=vapid,
                    vapid_claims=dict(VAPID_CLAIMS), ttl=PUSH_TTL, timeout=PUSH_TIMEOUT,
                    headers={"Urgency": "high"})
            results.append(True)
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):   # the push service says this subscription no longer exists
                store.remove(subscription_info.get("endpoint", ""))
            else:
                print(f"Push notification failed: {e}", flush=True)
        except Exception as e:
            print(f"Push notification failed: {e}", flush=True)

    threads = [threading.Thread(target=send_one, args=(s,), daemon=True, name="push-send") for s in store.list()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(PUSH_TIMEOUT + 2)
    return len(results)
