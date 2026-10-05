"""push.py in isolation: VAPID keys, the subscription store, and sending — pywebpush itself is mocked, so no real
network call or real phone is ever involved."""
import pytest

import push


@pytest.fixture
def store(tmp_path):
    return push.SubscriptionStore(path=str(tmp_path / "subs.json"))


def _sub(endpoint="https://push.example/abc", key="p256dh-key", auth="auth-key"):
    return {"endpoint": endpoint, "keys": {"p256dh": key, "auth": auth}}


def test_a_subscription_is_stored_and_listed(store):
    store.add(_sub())
    assert store.list() == [_sub()]


def test_adding_the_same_endpoint_again_replaces_it_not_duplicates(store):
    store.add(_sub())
    store.add(_sub(key="new-key"))
    assert len(store.list()) == 1
    assert store.list()[0]["keys"]["p256dh"] == "new-key"


def test_a_subscription_without_an_endpoint_is_ignored(store):
    store.add({"keys": {"p256dh": "x", "auth": "y"}})
    assert store.list() == []


def test_removing_a_subscription(store):
    store.add(_sub())
    store.remove("https://push.example/abc")
    assert store.list() == []


def test_subscriptions_persist_across_store_instances(tmp_path):
    path = str(tmp_path / "subs.json")
    push.SubscriptionStore(path=path).add(_sub())
    assert push.SubscriptionStore(path=path).list() == [_sub()]


def test_vapid_public_key_is_a_valid_uncompressed_ec_point(monkeypatch, tmp_path):
    monkeypatch.setattr(push, "VAPID_FILE", str(tmp_path / "vapid.pem"))
    monkeypatch.setattr(push, "_vapid_instance", None)
    import base64
    key = push.public_key_b64()
    raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert len(raw) == 65 and raw[0] == 0x04   # uncompressed EC point: 0x04 + 32-byte X + 32-byte Y


def test_the_same_vapid_key_is_reused_across_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(push, "VAPID_FILE", str(tmp_path / "vapid.pem"))
    monkeypatch.setattr(push, "_vapid_instance", None)
    first = push.public_key_b64()
    monkeypatch.setattr(push, "_vapid_instance", None)   # force a reload from disk, as a fresh process would do
    second = push.public_key_b64()
    assert first == second


def test_send_to_all_calls_webpush_once_per_subscription(monkeypatch, store):
    store.add(_sub("https://push.example/a"))
    store.add(_sub("https://push.example/b"))
    calls = []
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(push, "_vapid", lambda: "fake-key")

    import types
    fake_module = types.SimpleNamespace(
        webpush=lambda **kwargs: calls.append(kwargs),
        WebPushException=Exception,
    )
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", fake_module)

    sent = push.send_to_all(store, "Title", "Body")
    assert sent == 2
    assert len(calls) == 2
    assert all(json_has_title(c["data"]) for c in calls)
    # Delivered promptly to a sleeping phone, and never stalled forever on one slow push service.
    assert all(c["headers"] == {"Urgency": "high"} for c in calls)
    assert all(c["ttl"] == push.PUSH_TTL > 0 and c["timeout"] == push.PUSH_TIMEOUT for c in calls)


def json_has_title(data: str) -> bool:
    import json
    return json.loads(data)["title"] == "Title"


def test_send_to_all_removes_a_subscription_the_push_service_says_is_gone(monkeypatch, store):
    store.add(_sub("https://push.example/dead"))
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(push, "_vapid", lambda: "fake-key")

    import types

    class FakeWebPushException(Exception):
        def __init__(self):
            self.response = types.SimpleNamespace(status_code=410)

    def fake_webpush(**kwargs):
        raise FakeWebPushException()

    fake_module = types.SimpleNamespace(webpush=fake_webpush, WebPushException=FakeWebPushException)
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", fake_module)

    sent = push.send_to_all(store, "Title", "Body")
    assert sent == 0
    assert store.list() == []   # the dead subscription was cleaned up, not kept for another failed retry


def test_send_to_all_keeps_a_subscription_on_a_transient_error(monkeypatch, store):
    store.add(_sub("https://push.example/flaky"))
    monkeypatch.setattr(push, "available", lambda: True)
    monkeypatch.setattr(push, "_vapid", lambda: "fake-key")

    import types

    class FakeWebPushException(Exception):
        def __init__(self):
            self.response = types.SimpleNamespace(status_code=500)

    fake_module = types.SimpleNamespace(
        webpush=lambda **kwargs: (_ for _ in ()).throw(FakeWebPushException()),
        WebPushException=FakeWebPushException)
    monkeypatch.setitem(__import__("sys").modules, "pywebpush", fake_module)

    push.send_to_all(store, "Title", "Body")
    assert store.list() == [_sub("https://push.example/flaky")]   # kept: a 500 isn't "this subscription is gone"


def test_send_to_all_does_nothing_when_pywebpush_is_unavailable(monkeypatch, store):
    store.add(_sub())
    monkeypatch.setattr(push, "available", lambda: False)
    assert push.send_to_all(store, "Title", "Body") == 0
