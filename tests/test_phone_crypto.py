"""phone_crypto.py: the AES-GCM envelope relay-routed phone traffic is wrapped in (see phone_control.py's module
docstring for why — the relay is a middlebox, TLS alone only protects each leg of the connection, not the payload
from the relay process itself)."""
import phone_crypto


def test_a_roundtrip_returns_the_original_object():
    key = phone_crypto.new_key()
    envelope = phone_crypto.encrypt(key, {"type": "command", "commandType": "PLAY_SONG"})
    assert phone_crypto.decrypt(key, envelope) == {"type": "command", "commandType": "PLAY_SONG"}


def test_the_wrong_key_fails_closed_not_open():
    key = phone_crypto.new_key()
    wrong_key = phone_crypto.new_key()
    envelope = phone_crypto.encrypt(key, {"type": "command"})
    assert phone_crypto.decrypt(wrong_key, envelope) is None


def test_a_tampered_ciphertext_is_rejected():
    key = phone_crypto.new_key()
    envelope = phone_crypto.encrypt(key, {"amount": 1})
    tampered = dict(envelope, ct=envelope["ct"][:-4] + ("A" * 4))
    assert phone_crypto.decrypt(key, tampered) is None


def test_two_keys_are_never_the_same():
    assert phone_crypto.new_key() != phone_crypto.new_key()


def test_a_malformed_envelope_is_rejected_not_raised():
    key = phone_crypto.new_key()
    assert phone_crypto.decrypt(key, {}) is None
    assert phone_crypto.decrypt(key, {"n": "not-base64!!", "ct": "also-not"}) is None


def test_key_base64_roundtrips():
    key = phone_crypto.new_key()
    assert phone_crypto.key_from_b64(phone_crypto.key_to_b64(key)) == key
