"""End-to-end encryption for phone traffic that leaves the local network through the relay (see relay_client.py).

The relay (relay/server.py) is a dumb router hosted on whatever platform the user picked: it forwards frames by
computerId/connId and never sees a device's key, so encrypting here means the relay operator — even a compromised
or instrumented relay — only ever sees opaque bytes, not commands, voice audio, or replies. WSS/TLS already protects
each leg in transit; this protects the payload from the middle hop itself, which the transport alone does not.

A 32-byte key is minted once per device, alongside its pairing token (see phone_control.DeviceRegistry.add), and
handed to the phone over the same trusted local-network pairing step the token already uses. Local (LAN, same-origin
WebSocket) traffic never goes through the relay and is left unencrypted at this layer, same as before — only
relay-routed frames are wrapped.
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12


def new_key() -> bytes:
    return os.urandom(KEY_BYTES)


def key_to_b64(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).decode("ascii")


def key_from_b64(key_b64: str) -> bytes:
    return base64.urlsafe_b64decode(key_b64.encode("ascii"))


def encrypt(key: bytes, obj) -> dict:
    """A JSON-serializable envelope {"n": nonce, "ct": ciphertext}, both base64url, safe to hand to the relay."""
    nonce = os.urandom(NONCE_BYTES)
    plaintext = json.dumps(obj).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return {"n": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ct": base64.urlsafe_b64encode(ciphertext).decode("ascii")}


def decrypt(key: bytes, envelope: dict):
    """The original object, or None if `envelope` isn't genuinely this device's (wrong key, tampered, or not
    actually an envelope) — callers treat that exactly like any other malformed message."""
    try:
        nonce = base64.urlsafe_b64decode(envelope["n"].encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(envelope["ct"].encode("ascii"))
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, KeyError, ValueError, TypeError):
        return None
