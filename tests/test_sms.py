"""sms.py in isolation: requests.post is mocked throughout, so no real network call or real text message is ever
sent by these tests."""
import types

import pytest

import sms


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_TO_NUMBER"):
        monkeypatch.delenv(key, raising=False)


def _configure(monkeypatch, **overrides):
    values = {"TWILIO_ACCOUNT_SID": "SIDxxxx", "TWILIO_AUTH_TOKEN": "tokxxxx",
              "TWILIO_FROM_NUMBER": "+15550000000", "TWILIO_TO_NUMBER": "+15551111111", **overrides}
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_not_configured_when_any_field_is_missing(monkeypatch):
    _configure(monkeypatch, TWILIO_TO_NUMBER="")
    assert not sms.configured()
    assert "aren't set up" in sms.send("hello")


def test_configured_when_all_four_fields_are_set(monkeypatch):
    _configure(monkeypatch)
    assert sms.configured()


def test_send_posts_to_twilios_api_with_the_right_fields(monkeypatch):
    _configure(monkeypatch)
    calls = []

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {}

    def fake_post(url, auth=None, data=None, timeout=None):
        calls.append({"url": url, "auth": auth, "data": data, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(sms.requests, "post", fake_post)
    result = sms.send("Jarvis wants to pair.")
    assert result == ""
    assert len(calls) == 1
    assert calls[0]["auth"] == ("SIDxxxx", "tokxxxx")
    assert calls[0]["data"] == {"From": "+15550000000", "To": "+15551111111", "Body": "Jarvis wants to pair."}
    assert "SIDxxxx" in calls[0]["url"]


def test_a_long_message_is_truncated_to_twilios_limit(monkeypatch):
    _configure(monkeypatch)
    sent = {}

    class FakeResponse:
        status_code = 201
        text = ""

        def json(self):
            return {}

    monkeypatch.setattr(sms.requests, "post", lambda url, auth, data, timeout: (sent.update(data) or FakeResponse()))
    sms.send("x" * 5000)
    assert len(sent["Body"]) == sms.MAX_LENGTH


def test_a_twilio_error_response_is_reported_not_raised(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        status_code = 400
        text = '{"message": "The number is not a valid phone number"}'

        def json(self):
            return {"message": "The number is not a valid phone number"}

    monkeypatch.setattr(sms.requests, "post", lambda *a, **k: FakeResponse())
    result = sms.send("hello")
    assert "not a valid phone number" in result


def test_a_network_failure_is_reported_not_raised(monkeypatch):
    _configure(monkeypatch)

    def raise_it(*a, **k):
        raise sms.requests.RequestException("timed out")

    monkeypatch.setattr(sms.requests, "post", raise_it)
    result = sms.send("hello")
    assert "Couldn't send" in result
