"""phone_control.py in isolation: pairing, device tokens, idempotent command handling — no network involved."""
import time

import pytest

import phone_control


@pytest.fixture
def registry(tmp_path):
    return phone_control.DeviceRegistry(path=str(tmp_path / "devices.json"))


def test_a_paired_device_authenticates_with_its_own_token(registry):
    device_id, token, _key = registry.add("Ariel's iPhone")
    found = registry.authenticate(device_id, token)
    assert found is not None and found["name"] == "Ariel's iPhone"


def test_wrong_token_is_refused(registry):
    device_id, _, _key = registry.add("Phone")
    assert registry.authenticate(device_id, "not-the-real-token") is None


def test_unknown_device_id_is_refused(registry):
    assert registry.authenticate("nope", "whatever") is None


def test_the_stored_file_never_holds_the_raw_token(registry, tmp_path):
    device_id, token, _key = registry.add("Phone")
    raw = (tmp_path / "devices.json").read_text()
    assert token not in raw and device_id in raw


def test_devices_persist_across_registry_instances(tmp_path):
    path = str(tmp_path / "devices.json")
    device_id, token, _key = phone_control.DeviceRegistry(path=path).add("Phone")
    reloaded = phone_control.DeviceRegistry(path=path)
    assert reloaded.authenticate(device_id, token) is not None


def test_revoke_removes_one_device_and_blocks_it(registry):
    a_id, a_token, _a_key = registry.add("Phone A")
    b_id, b_token, _b_key = registry.add("Phone B")
    assert registry.revoke(a_id) == 1
    assert registry.authenticate(a_id, a_token) is None
    assert registry.authenticate(b_id, b_token) is not None


def test_revoke_with_no_id_clears_every_device(registry):
    registry.add("Phone A")
    registry.add("Phone B")
    assert registry.revoke() == 2
    assert registry.list() == []


def test_listed_devices_never_include_the_token_hash(registry):
    registry.add("Phone")
    for entry in registry.list():
        assert "token_hash" not in entry and "token" not in entry and "key_b64" not in entry


def test_each_device_gets_its_own_end_to_end_key(registry):
    a_id, _a_token, a_key = registry.add("Phone A")
    b_id, _b_token, b_key = registry.add("Phone B")
    assert a_key != b_key
    assert registry.key_for(a_id) == a_key
    assert registry.key_for(b_id) == b_key


def test_key_for_an_unpaired_device_is_none(registry):
    assert registry.key_for("nope") is None


@pytest.mark.parametrize("ip,private", [
    ("192.168.1.42", True), ("10.0.0.5", True), ("172.16.0.9", True), ("127.0.0.1", True),
    ("8.8.8.8", False), ("1.1.1.1", False), ("not-an-ip", False), ("", False),
])
def test_is_private_address(ip, private):
    assert phone_control.is_private_address(ip) is private


class _Server:
    """A PhoneControlServer with a recording `execute`, for pairing/command tests."""

    def __init__(self, tmp_path, fail=False):
        self.calls = []
        self.fail = fail

        def execute(command_type, payload):
            self.calls.append((command_type, payload))
            if self.fail:
                raise ValueError("boom")
            return f"did {command_type}"

        self.server = phone_control.PhoneControlServer(
            execute=execute, registry=phone_control.DeviceRegistry(path=str(tmp_path / "devices.json")))


def test_pairing_is_closed_until_begun(tmp_path):
    s = _Server(tmp_path).server
    assert not s.pairing_open()
    assert s.try_pair("000000", "Phone") is None


def test_correct_code_pairs_and_closes_the_window(tmp_path):
    s = _Server(tmp_path).server
    code = s.begin_pairing()
    assert s.pairing_open()
    paired = s.try_pair(code, "Ariel's iPhone")
    assert paired is not None
    device_id, token, _key = paired
    assert s.registry.authenticate(device_id, token)["name"] == "Ariel's iPhone"
    assert not s.pairing_open()   # a code pairs one phone, then it's closed


def test_wrong_code_is_rejected_and_counted(tmp_path):
    s = _Server(tmp_path).server
    real_code = s.begin_pairing()
    wrong = "000000" if real_code != "000000" else "111111"
    assert s.try_pair(wrong, "Phone") is None
    assert s.pairing_open()   # one wrong guess doesn't close it


def test_a_code_stops_working_after_too_many_wrong_guesses(tmp_path):
    s = _Server(tmp_path).server
    real_code = s.begin_pairing()
    wrong = "000000" if real_code != "000000" else "111111"
    for _ in range(phone_control.MAX_PAIR_ATTEMPTS):
        s.try_pair(wrong, "Phone")
    assert not s.pairing_open()
    assert s.try_pair(real_code, "Phone") is None   # even the real code, too late


def test_an_expired_code_no_longer_works(tmp_path, monkeypatch):
    s = _Server(tmp_path).server
    code = s.begin_pairing()
    future = time.time() + phone_control.PAIR_CODE_TTL + 1
    monkeypatch.setattr(phone_control.time, "time", lambda: future)
    assert not s.pairing_open()
    assert s.try_pair(code, "Phone") is None


def test_a_command_only_runs_once_even_if_the_message_is_resent(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    first = s.run_command("dev1", "cmd-1", "OPEN_APPLICATION", {"app_name": "Chrome"})
    second = s.run_command("dev1", "cmd-1", "OPEN_APPLICATION", {"app_name": "Chrome"})
    assert first == second == {"status": "SUCCEEDED", "message": "did OPEN_APPLICATION"}
    assert harness.calls == [("OPEN_APPLICATION", {"app_name": "Chrome"})]   # executed exactly once


def test_the_same_command_id_from_a_different_device_is_not_treated_as_a_duplicate(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    s.run_command("dev1", "cmd-1", "OPEN_APPLICATION", {"app_name": "Chrome"})
    s.run_command("dev2", "cmd-1", "OPEN_APPLICATION", {"app_name": "Chrome"})
    assert len(harness.calls) == 2


def test_a_failed_command_is_also_remembered_not_retried(tmp_path):
    harness = _Server(tmp_path, fail=True)
    s = harness.server
    first = s.run_command("dev1", "cmd-1", "OPEN_APPLICATION", {"app_name": "Nonexistent"})
    second = s.run_command("dev1", "cmd-1", "OPEN_APPLICATION", {"app_name": "Nonexistent"})
    assert first == second == {"status": "FAILED", "message": "boom"}
    assert len(harness.calls) == 1


# ---------- sessions: "connect my phone" after the first pairing (see PhoneSession) ----------

def _paired(harness):
    device_id, token, key = harness.server.registry.add("Ariel's iPhone")
    return device_id, token, key


def test_deciding_with_the_wrong_secret_does_nothing(tmp_path):
    s = _Server(tmp_path).server
    session = s.begin_session()
    assert s.decide_session(session.id, "not-the-real-secret", True) is False
    assert session.state == "pending"


def test_deciding_with_the_wrong_session_id_does_nothing(tmp_path):
    s = _Server(tmp_path).server
    session = s.begin_session()
    assert s.decide_session("not-the-real-id", session.secret, True) is False
    assert session.state == "pending"


def test_confirm_then_attach_with_a_real_device_succeeds(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, key = _paired(harness)
    session = s.begin_session()
    assert s.decide_session(session.id, session.secret, True) is True
    assert session.state == "approved"
    assert session.decided_event.is_set()
    got_key = s.attach_session(session.id, device_id, token, "conn-1")
    assert got_key == key
    assert session.state == "active"
    assert s.active_session_conn(session.id) == "conn-1"


def test_reject_sets_state_and_wakes_the_waiting_thread(tmp_path):
    s = _Server(tmp_path).server
    session = s.begin_session()
    assert s.decide_session(session.id, session.secret, False) is True
    assert session.state == "rejected"
    assert session.decided_event.is_set()


def test_a_second_decision_on_the_same_session_is_refused(tmp_path):
    s = _Server(tmp_path).server
    session = s.begin_session()
    assert s.decide_session(session.id, session.secret, True) is True
    assert s.decide_session(session.id, session.secret, False) is False   # already decided
    assert session.state == "approved"


def test_attach_is_refused_before_the_session_is_approved(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, _key = _paired(harness)
    session = s.begin_session()
    assert s.attach_session(session.id, device_id, token, "conn-1") is None


def test_attach_is_refused_with_a_wrong_device_token(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    device_id, _token, _key = _paired(harness)
    session = s.begin_session()
    s.decide_session(session.id, session.secret, True)
    assert s.attach_session(session.id, device_id, "wrong-token", "conn-1") is None


def test_attach_does_not_need_the_session_secret(tmp_path):
    """Deliberately: the secret only proves the push notification was answered (decide_session); it's kept out
    of the URL the service worker opens the page with, so attach must work from the device token alone."""
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, key = _paired(harness)
    session = s.begin_session()
    s.decide_session(session.id, session.secret, True)
    assert s.attach_session(session.id, device_id, token, "conn-1") == key


def test_reattaching_an_active_session_from_the_same_device_is_allowed(tmp_path):
    """A network blip shouldn't force a whole new notification-and-tap — see attach_session's docstring."""
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, key = _paired(harness)
    session = s.begin_session()
    s.decide_session(session.id, session.secret, True)
    assert s.attach_session(session.id, device_id, token, "conn-1") == key
    assert s.attach_session(session.id, device_id, token, "conn-2") == key   # reconnect, new relay connId
    assert s.active_session_conn(session.id) == "conn-2"


def test_reattaching_an_active_session_from_a_different_device_is_refused(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, _key = _paired(harness)
    other_id, other_token, _other_key = harness.server.registry.add("A different phone")
    session = s.begin_session()
    s.decide_session(session.id, session.secret, True)
    assert s.attach_session(session.id, device_id, token, "conn-1") is not None
    assert s.attach_session(session.id, other_id, other_token, "conn-2") is None


def test_ending_a_session_clears_it(tmp_path):
    harness = _Server(tmp_path)
    s = harness.server
    device_id, token, _key = _paired(harness)
    session = s.begin_session()
    s.decide_session(session.id, session.secret, True)
    s.attach_session(session.id, device_id, token, "conn-1")
    assert s.current_session_id() == session.id
    s.end_session(session.id)
    assert s.current_session_id() is None
    assert s.active_session_conn(session.id) is None


def test_a_session_expires_after_too_many_wrong_secret_guesses(tmp_path):
    s = _Server(tmp_path).server
    session = s.begin_session()
    for _ in range(phone_control.MAX_SESSION_DECIDE_ATTEMPTS):
        s.decide_session(session.id, "wrong", True)
    assert s.decide_session(session.id, session.secret, True) is False
